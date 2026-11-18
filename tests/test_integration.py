"""Integraatiotestit oikeaa Postgres + pgvector -kantaa vasten, ilman Ollamaa."""

import shutil
from pathlib import Path

import pytest

from localrag import mcp_server
from localrag.config import Settings
from localrag.db import SchemaMismatchError, connect, ensure_schema, reset
from localrag.indexer import index_root
from localrag.search import hybrid_search

from .conftest import EXAMPLES_DIR, BagOfWordsEmbedder

pytestmark = pytest.mark.integration

EXAMPLE_FILES = sorted(p.name for p in (EXAMPLES_DIR / "docs").iterdir() if p.is_file())


@pytest.fixture
def env(test_database_url, tmp_path):
    embedder = BagOfWordsEmbedder()
    settings = Settings(
        _env_file=None,
        database_url=test_database_url,
        embedding_model=embedder.model,
        embedding_dim=embedder.dim,
    )
    conn = connect(settings)
    reset(conn)
    ensure_schema(conn, settings)
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLES_DIR / "docs", docs)
    yield settings, conn, embedder, docs
    conn.close()


def _top_file(settings, conn, embedder, query: str, **kwargs) -> str:
    hits = hybrid_search(conn, embedder, settings, query, **kwargs)
    assert hits, f"Ei osumia kyselylle {query!r}"
    return Path(hits[0].path).name


def _top_text_search_file(settings, conn, embedder, query: str) -> str:
    """Tekstihaun (FTS) paras osuma hybridihaun tuloksista.

    Testiembedderin vektorihaku on lähinnä kohinaa, joten täsmätermien osalta tarkistetaan
    tekstihaun haara. Semanttisen haun ja yhdistelyn laatua mittaa e2e-testi.
    """
    hits = hybrid_search(conn, embedder, settings, query, limit=20)
    top = [h for h in hits if h.fts_rank == 1]
    assert top, f"Tekstihaku ei löytänyt mitään kyselylle {query!r}"
    return Path(top[0].path).name


def test_indexes_all_example_files(env):
    settings, conn, embedder, docs = env
    stats = index_root(conn, docs, settings, embedder)
    assert stats.errors == []
    assert stats.indexed == len(EXAMPLE_FILES)
    assert stats.chunks >= len(EXAMPLE_FILES)

    parsers = {r["parser"] for r in conn.execute("SELECT parser FROM documents")}
    assert parsers == {"text", "pypdf"}


def test_reindex_processes_only_changes(env):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)

    again = index_root(conn, docs, settings, embedder)
    assert (again.indexed, again.unchanged, again.removed) == (0, len(EXAMPLE_FILES), 0)

    with (docs / "matkustusohje.md").open("a", encoding="utf-8") as f:
        f.write("\n## Lisäys\n\nPolkupyöräetu kattaa kaupunkipyörät.\n")
    (docs / "lomakaytanto-2025.txt").unlink()

    changed = index_root(conn, docs, settings, embedder)
    assert (changed.indexed, changed.removed) == (1, 1)
    assert _top_file(settings, conn, embedder, "polkupyöräetu") == "matkustusohje.md"
    paths = [r["path"] for r in conn.execute("SELECT path FROM documents")]
    assert not any(p.endswith("lomakaytanto-2025.txt") for p in paths)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("salasanan vähimmäispituus", "tietoturvaohje.pdf"),
        ("Lumikko-Guest", "perehdytys-ukk.txt"),
        ("LUM-2025-117", "palvelusopimus-virvatuli.pdf"),
        ("API rate limit", "revontuli-product-overview.md"),
        ("Revontuli 3.0 julkaisu siirretään", "kokousmuistio-2026-10-14.txt"),
        ("taksin käyttö", "matkustusohje.md"),
    ],
)
def test_text_search_finds_exact_terms(env, query, expected):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    assert _top_text_search_file(settings, conn, embedder, query) == expected


@pytest.mark.xfail(
    strict=True,
    reason="Tunnettu rajoite: 'simple'-tekstihaku ei ymmärrä suomen taivutusta "
    "(dokumentissa 'irtisanomisajan'). Korjataan vaiheessa 2, minkä jälkeen merkintä poistetaan.",
)
def test_text_search_handles_finnish_inflection(env):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    assert _top_text_search_file(settings, conn, embedder, "irtisanomisaika") == (
        "palvelusopimus-virvatuli.pdf"
    )


def _text_search_files(settings, conn, embedder, query: str) -> set[str]:
    hits = hybrid_search(conn, embedder, settings, query, limit=50)
    return {Path(h.path).name for h in hits if h.fts_rank is not None}


def test_stopwords_do_not_drive_text_search(env):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    query = "Missä maissa Revontulta myydään?"  # UKK:hon osuisi vain "Missä toimisto on"

    assert "perehdytys-ukk.txt" not in _text_search_files(settings, conn, embedder, query)

    without = settings.model_copy(update={"fts_stopwords": False})
    assert "perehdytys-ukk.txt" in _text_search_files(without, conn, embedder, query)


def test_query_of_only_stopwords_falls_back_to_vector_search(env):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    hits = hybrid_search(conn, embedder, settings, "Mikä on missä ja miten?")
    assert hits
    assert all(h.fts_rank is None for h in hits)


class KeywordReranker:
    """Testireranker: palat, joissa on avainsana, nousevat kärkeen."""

    model = "test-keyword-reranker"

    def __init__(self, keyword: str):
        self.keyword = keyword.casefold()
        self.calls: list[int] = []

    def score(self, query: str, texts):
        self.calls.append(len(texts))
        return [1.0 if self.keyword in t.casefold() else 0.0 for t in texts]


def test_reranker_reorders_candidates(env):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    reranker = KeywordReranker("Lumikko-Guest")

    timings: dict[str, float] = {}
    hits = hybrid_search(
        conn, embedder, settings, "salasana", limit=3, reranker=reranker, timings=timings
    )

    assert reranker.calls == [settings.rerank_candidates]
    assert len(hits) == 3
    assert Path(hits[0].path).name == "perehdytys-ukk.txt"
    assert hits[0].rerank_score == 1.0
    assert all(h.rerank_score is not None for h in hits)
    assert set(timings) == {"embedding", "database", "rerank"}


def test_pdf_hits_carry_page_number(env):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    hit = hybrid_search(conn, embedder, settings, "USB-muistitikkujen käyttö")[0]
    assert Path(hit.path).name == "tietoturvaohje.pdf"
    assert hit.heading_path == "Page 3"


def test_path_prefix_limits_results(env):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    prefix = str(docs / "lomakaytanto")
    hits = hybrid_search(conn, embedder, settings, "Revontuli", path_prefix=prefix)
    assert hits
    assert all(h.path.startswith(prefix) for h in hits)


def test_mcp_tools(env, monkeypatch):
    settings, conn, embedder, docs = env
    index_root(conn, docs, settings, embedder)
    monkeypatch.setattr(mcp_server, "_conn", conn)
    monkeypatch.setattr(mcp_server, "_embedder", embedder)
    monkeypatch.setattr(mcp_server, "get_settings", lambda: settings)

    assert len(mcp_server.list_documents()) == len(EXAMPLE_FILES)

    hits = mcp_server.search_documents("USB-muistitikkujen käyttö", limit=3)
    assert hits[0]["path"].endswith("tietoturvaohje.pdf")
    assert hits[0]["section"] == "Page 3"

    text = mcp_server.read_document(str(docs / "lomakaytanto-2026.md"))
    assert "15.3." in text
    assert mcp_server.read_document("/etc/passwd").startswith("Not an indexed document")


def test_changed_embedding_model_is_rejected(env):
    settings, conn, _, _ = env
    other = settings.model_copy(update={"embedding_model": "some-other-model"})
    with pytest.raises(SchemaMismatchError):
        ensure_schema(conn, other)
