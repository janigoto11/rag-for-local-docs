"""Haun evaluointi kahdella tasolla.

Dokumenttitaso: löytyykö odotettu tiedosto k:n parhaan dokumentin joukosta?
Palataso: sisältääkö jokin k:n parhaasta palasta odotetun tekstin? Agentti saa haulta
paloja, ei dokumentteja, joten palataso kertoo paremmin, löytyykö vastaus oikeasti.

questions.yaml:
  - question: "Mikä on sopimuksen irtisanomisaika?"
    expected: ["sopimukset/vuokrasopimus.pdf"]   # polun osamerkkijonoja, mikä tahansa kelpaa
    expected_text: "kolmen kuukauden"            # valinnainen; merkkijono tai lista
"""

from dataclasses import dataclass
from pathlib import Path

import psycopg
import yaml

from .config import Settings
from .embeddings import Embedder
from .reranking import Reranker
from .search import hybrid_search


@dataclass
class EvalResult:
    question: str
    rank: int | None  # ensimmäisen osuvan dokumentin sijoitus (1-pohjainen), None jos ei löytynyt
    top_paths: list[str]
    # ensimmäisen odotetun tekstin sisältävän palan sijoitus; None jos ei löytynyt
    chunk_rank: int | None = None
    has_expected_text: bool = False


def normalize_text(text: str) -> str:
    """Vertailua varten: pienaakkoset ja välilyönnit yhdeksi (PDF:n rivinvaihdot ym.)."""
    return " ".join(text.split()).casefold()


def as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def load_questions(file: Path) -> list[dict]:
    items = yaml.safe_load(file.read_text(encoding="utf-8")) or []
    for item in items:
        if "question" not in item or "expected" not in item:
            raise ValueError(f"Kysymyksestä puuttuu 'question' tai 'expected': {item}")
    return items


def run_eval(
    conn: psycopg.Connection,
    embedder: Embedder,
    settings: Settings,
    file: Path,
    k: int,
    reranker: Reranker | None = None,
) -> list[EvalResult]:
    results = []
    for item in load_questions(file):
        hits = hybrid_search(
            conn, embedder, settings, item["question"], limit=k * 3, reranker=reranker
        )

        paths: list[str] = []
        for h in hits:  # dokumenttitason sijoitus: kukin dokumentti lasketaan kerran
            if h.path not in paths:
                paths.append(h.path)
        paths = paths[:k]
        rank = next(
            (i for i, p in enumerate(paths, 1) if any(e in p for e in item["expected"])), None
        )

        texts = [normalize_text(t) for t in as_list(item.get("expected_text"))]
        chunk_rank = None
        if texts:
            chunk_rank = next(
                (
                    i
                    for i, h in enumerate(hits[:k], 1)
                    if any(t in normalize_text(h.content) for t in texts)
                ),
                None,
            )
        results.append(EvalResult(item["question"], rank, paths, chunk_rank, bool(texts)))
    return results


def summarize(results: list[EvalResult]) -> dict[str, float]:
    n = len(results) or 1
    with_text = [r for r in results if r.has_expected_text]
    m = len(with_text) or 1
    return {
        "questions": len(results),
        "hit_rate": sum(r.rank is not None for r in results) / n,
        "mrr": sum(1 / r.rank for r in results if r.rank) / n,
        "chunk_questions": len(with_text),
        "chunk_hit_rate": sum(r.chunk_rank is not None for r in with_text) / m,
        "chunk_mrr": sum(1 / r.chunk_rank for r in with_text if r.chunk_rank) / m,
    }
