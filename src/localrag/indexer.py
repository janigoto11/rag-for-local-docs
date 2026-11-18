"""Hakemistopuun inkrementaalinen indeksointi."""

import hashlib
import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import psycopg

from .chunking import chunk_document, embedding_text
from .config import Settings
from .embeddings import Embedder, embed_batched
from .parsing import is_supported, parse

log = logging.getLogger(__name__)

IGNORED_DIRS = {
    "node_modules",
    "__pycache__",
    "venv",
    "dist",
    "build",
    "target",
    "out",
    "coverage",
}


@dataclass
class IndexStats:
    scanned: int = 0
    indexed: int = 0
    unchanged: int = 0
    skipped: int = 0
    removed: int = 0
    chunks: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def iter_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in IGNORED_DIRS)
        for name in sorted(filenames):
            if not name.startswith("."):
                yield Path(dirpath) / name


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _index_file(
    conn: psycopg.Connection,
    path: Path,
    sha: str,
    st: os.stat_result,
    settings: Settings,
    embedder: Embedder,
) -> int:
    parsed = parse(path)
    if parsed is None or not parsed.text.strip():
        return 0
    chunks = chunk_document(
        parsed.text, parsed.format, settings.chunk_target_tokens, settings.chunk_overlap_tokens
    )
    if not chunks:
        return 0
    texts = [settings.embedding_document_prefix + embedding_text(path.name, c) for c in chunks]
    vectors = embed_batched(embedder, texts, settings.embed_batch_size)

    with conn.transaction():
        doc_id = conn.execute(
            """
            INSERT INTO documents (path, sha256, mtime_ns, size, parser, indexed_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (path) DO UPDATE SET
                sha256 = EXCLUDED.sha256, mtime_ns = EXCLUDED.mtime_ns, size = EXCLUDED.size,
                parser = EXCLUDED.parser, indexed_at = now()
            RETURNING id
            """,
            (str(path), sha, st.st_mtime_ns, st.st_size, parsed.parser),
        ).fetchone()["id"]
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks
                    (document_id, chunk_index, heading_path, content, token_count, embedding, tsv)
                VALUES (%s, %s, %s, %s, %s, %s, to_tsvector('simple', %s))
                """,
                [
                    (
                        doc_id,
                        c.index,
                        c.heading_path,
                        c.content,
                        c.token_count,
                        np.asarray(v, dtype=np.float32),
                        f"{path.name}\n{c.heading_path}\n{c.content}",
                    )
                    for c, v in zip(chunks, vectors, strict=True)
                ],
            )
    return len(chunks)


def index_root(
    conn: psycopg.Connection,
    root: Path,
    settings: Settings,
    embedder: Embedder,
    on_progress: Callable[[str, Path], None] | None = None,
) -> IndexStats:
    root = root.expanduser().resolve()
    stats = IndexStats()
    prefix = str(root) + os.sep
    existing = {
        r["path"]: r
        for r in conn.execute(
            "SELECT path, sha256, mtime_ns, size FROM documents WHERE starts_with(path, %s)",
            (prefix,),
        )
    }
    seen: set[str] = set()
    max_bytes = settings.max_file_mb * 1024 * 1024

    for path in iter_files(root):
        if not is_supported(path):
            continue
        stats.scanned += 1
        key = str(path)
        seen.add(key)
        try:
            st = path.stat()
            if st.st_size > max_bytes:
                stats.skipped += 1
                continue
            old = existing.get(key)
            if old and old["mtime_ns"] == st.st_mtime_ns and old["size"] == st.st_size:
                stats.unchanged += 1
                continue
            sha = file_sha256(path)
            if old and old["sha256"] == sha:
                conn.execute(
                    "UPDATE documents SET mtime_ns = %s, size = %s WHERE path = %s",
                    (st.st_mtime_ns, st.st_size, key),
                )
                stats.unchanged += 1
                continue
            if on_progress:
                on_progress("index", path)
            n = _index_file(conn, path, sha, st, settings, embedder)
            if n:
                stats.indexed += 1
                stats.chunks += n
            else:
                stats.skipped += 1
        except Exception as e:  # jatketaan: yksi viallinen tiedosto ei saa kaataa koko ajoa
            log.exception("Failed to index %s", path)
            stats.errors.append((key, str(e)))

    removed = [p for p in existing if p not in seen]
    if removed:
        conn.execute("DELETE FROM documents WHERE path = ANY(%s)", (removed,))
        stats.removed = len(removed)
    return stats
