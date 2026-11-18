"""E2E-laatutesti oikealla embedding-mallilla (.env-asetukset, oletuksena Ollama + bge-m3).

Ajo: uv run pytest -m e2e

Testi indeksoi demokorpuksen testikantaan ja ajaa examples/questions.yaml-kysymykset.
Yksittäisiä sijoituksia ei tarkisteta, koska ne vaihtelevat mallin ja pilkkomisen mukaan;
sen sijaan vaaditaan, että riittävän moni kysymys osuu oikeaan dokumenttiin.
"""

from pathlib import Path

import pytest

from localrag.config import Settings
from localrag.db import connect, ensure_schema, reset
from localrag.embeddings import EmbedderUnavailableError, check_embedder, get_embedder
from localrag.evaluation import run_eval, summarize
from localrag.indexer import index_root
from localrag.reranking import RerankerUnavailableError, get_reranker

from .conftest import EXAMPLES_DIR

pytestmark = pytest.mark.e2e

K = 3
# Rajat ovat lattioita, joiden alle laatu ei saa pudota. Nosta niitä, kun haku paranee.
MIN_HIT_RATE = 0.9  # dokumenttitaso
MIN_CHUNK_HIT_RATE = 0.8  # palataso: vastauksen sisältävä pala k:n parhaan joukossa


def test_example_questions_find_expected_answers(test_database_url):
    settings = Settings(database_url=test_database_url)
    embedder = get_embedder(settings)
    try:
        check_embedder(embedder, settings)
    except EmbedderUnavailableError as e:
        pytest.skip(str(e))
    try:
        reranker = get_reranker(settings)
    except RerankerUnavailableError as e:
        pytest.skip(str(e))

    conn = connect(settings)
    try:
        reset(conn)
        ensure_schema(conn, settings)
        stats = index_root(conn, EXAMPLES_DIR / "docs", settings, embedder)
        assert stats.errors == []

        results = run_eval(conn, embedder, settings, EXAMPLES_DIR / "questions.yaml", K, reranker)
    finally:
        conn.close()

    s = summarize(results)
    print(
        f"\n{settings.embedding_model}, reranker: {reranker.model if reranker else 'ei'}, "
        f"täytesanasuodatus: {settings.fts_stopwords}"
        f"\n  dokumentit hit@{K}={s['hit_rate']:.2f} mrr={s['mrr']:.2f}"
        f"\n  palat      hit@{K}={s['chunk_hit_rate']:.2f} mrr={s['chunk_mrr']:.2f}"
    )
    doc_misses = [
        f"  - {r.question} -> {[Path(p).name for p in r.top_paths]}"
        for r in results
        if r.rank is None
    ]
    chunk_misses = [
        f"  - {r.question}" for r in results if r.has_expected_text and r.chunk_rank is None
    ]
    report = "\n".join(
        ["Dokumenttitason ohilyönnit:", *doc_misses, "Palatason ohilyönnit:", *chunk_misses]
    )
    print(report)
    assert s["hit_rate"] >= MIN_HIT_RATE, report
    assert s["chunk_hit_rate"] >= MIN_CHUNK_HIT_RATE, report
