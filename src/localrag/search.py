"""Hybridihaku: pgvectorin kosinietäisyys + Postgresin tekstihaku.

Tulokset yhdistetään Reciprocal Rank Fusionilla (RRF).
"""

import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import psycopg

from .config import Settings
from .embeddings import Embedder
from .reranking import Reranker, rerank_text
from .stopwords import STOPWORDS

HYBRID_SQL = """
WITH vec AS (
    SELECT id, row_number() OVER (ORDER BY dist) AS r
    FROM (
        SELECT c.id, c.embedding <=> %(qvec)s AS dist
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE (%(prefix)s::text IS NULL OR starts_with(d.path, %(prefix)s))
        ORDER BY c.embedding <=> %(qvec)s
        LIMIT %(k)s
    ) s
),
fts_query AS (
    -- Kyselyn lekseemit samalla 'simple'-konfiguraatiolla kuin dokumenttien tsvector.
    -- Täytesanat poistetaan, ja termit yhdistetään OR-ehdolla, koska luonnollisen kielen
    -- kysymys sisältää harvoin palan jokaista sanaa; ts_rank_cd nostaa silti useampaan
    -- termiin osuvat palat korkeammalle. Jos mitään ei jää, q on NULL eikä tekstihaku osu.
    SELECT NULLIF(array_to_string(ARRAY(
        SELECT quote_literal(lexeme)
        FROM unnest(tsvector_to_array(to_tsvector('simple', %(text)s))) AS lexeme
        WHERE lexeme <> ALL(%(stopwords)s::text[])
          AND strpos(lexeme, chr(92)) = 0
    ), ' | '), '')::tsquery AS q
),
fts AS (
    SELECT id, row_number() OVER (ORDER BY rank DESC) AS r
    FROM (
        SELECT c.id, ts_rank_cd(c.tsv, fq.q) AS rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        CROSS JOIN fts_query fq
        WHERE c.tsv @@ fq.q
          AND (%(prefix)s::text IS NULL OR starts_with(d.path, %(prefix)s))
        ORDER BY rank DESC
        LIMIT %(k)s
    ) s
)
SELECT c.id AS chunk_id, d.path, c.heading_path, c.chunk_index, c.content,
       vec.r AS vec_rank, fts.r AS fts_rank,
       COALESCE(1.0 / (%(rrf_k)s + vec.r), 0) + COALESCE(1.0 / (%(rrf_k)s + fts.r), 0) AS score
FROM vec
FULL OUTER JOIN fts ON vec.id = fts.id
JOIN chunks c ON c.id = COALESCE(vec.id, fts.id)
JOIN documents d ON d.id = c.document_id
ORDER BY score DESC
LIMIT %(limit)s
"""


@dataclass
class SearchHit:
    chunk_id: int
    path: str
    heading_path: str
    chunk_index: int
    content: str
    score: float
    vec_rank: int | None
    fts_rank: int | None
    rerank_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def hybrid_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    settings: Settings,
    query: str,
    limit: int = 8,
    path_prefix: str | None = None,
    reranker: Reranker | None = None,
    timings: dict[str, float] | None = None,
) -> list[SearchHit]:
    """Hybridihaku. Jos reranker annetaan, haetaan ensin rerank_candidates ehdokasta,
    järjestetään ne rerankerilla ja palautetaan limit parasta.

    Jos timings annetaan, siihen kirjataan vaiheiden kestot sekunteina
    (embedding, database, rerank).
    """
    timings = timings if timings is not None else {}
    candidates = max(limit, settings.rerank_candidates) if reranker else limit

    start = time.perf_counter()
    qvec = np.asarray(
        embedder.embed([settings.embedding_query_prefix + query])[0], dtype=np.float32
    )
    timings["embedding"] = time.perf_counter() - start

    start = time.perf_counter()
    with conn.transaction():
        conn.execute(f"SET LOCAL hnsw.ef_search = {int(settings.hnsw_ef_search)}")
        rows = conn.execute(
            HYBRID_SQL,
            {
                "qvec": qvec,
                "text": query,
                "stopwords": list(STOPWORDS) if settings.fts_stopwords else [],
                "prefix": path_prefix,
                "k": settings.search_candidates,
                "rrf_k": settings.rrf_k,
                "limit": candidates,
            },
        ).fetchall()
    timings["database"] = time.perf_counter() - start

    hits = [
        SearchHit(
            chunk_id=r["chunk_id"],
            path=r["path"],
            heading_path=r["heading_path"],
            chunk_index=r["chunk_index"],
            content=r["content"],
            score=float(r["score"]),
            vec_rank=r["vec_rank"],
            fts_rank=r["fts_rank"],
        )
        for r in rows
    ]
    if reranker and hits:
        start = time.perf_counter()
        texts = [rerank_text(Path(h.path).name, h.heading_path, h.content) for h in hits]
        for hit, score in zip(hits, reranker.score(query, texts), strict=True):
            hit.rerank_score = score
        hits.sort(key=lambda h: h.rerank_score, reverse=True)
        timings["rerank"] = time.perf_counter() - start
    return hits[:limit]
