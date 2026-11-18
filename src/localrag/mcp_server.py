"""MCP-palvelin, joka tarjoaa indeksin LLM-agenttien käyttöön (Claude Desktop, Claude Code ym.).

Toimii stdio-yhteydellä, joten stdoutiin ei saa tulostaa mitään; lokit menevät stderriin.
"""

import logging
import sys
from pathlib import Path

import psycopg
from mcp.server.mcpserver import MCPServer

from .config import get_settings
from .db import connect, ensure_schema
from .embeddings import Embedder, get_embedder
from .parsing import parse
from .reranking import get_reranker
from .search import hybrid_search

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

mcp = MCPServer(
    "local-docs",
    instructions="Hae ja lue käyttäjän paikallisia dokumentteja, jotka localrag on indeksoinut.",
)

_conn: psycopg.Connection | None = None
_embedder: Embedder | None = None


def _get_conn() -> psycopg.Connection:
    global _conn
    if _conn is None or _conn.closed:
        settings = get_settings()
        _conn = connect(settings)
        ensure_schema(_conn, settings)
    return _conn


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = get_embedder(get_settings())
    return _embedder


@mcp.tool()
def search_documents(query: str, path_prefix: str | None = None, limit: int = 8) -> list[dict]:
    """Hakee käyttäjän indeksoiduista paikallisista dokumenteista (semanttinen + avainsanahaku).

    Palauttaa osuvimmat tekstipalat tiedostopolun ja osion otsikon kera.
    Vinkkejä: käytä täsmällisiä termejä ja nimiä; kokeile useita muotoiluja (myös suomeksi
    ja englanniksi), jos ensimmäiset tulokset ovat heikkoja; rajaa kansioon path_prefixillä;
    kutsu read_documentia, kun tarvitset koko tiedoston etkä vain katkelmia.
    """
    settings = get_settings()
    hits = hybrid_search(
        _get_conn(),
        _get_embedder(),
        settings,
        query,
        min(limit, 30),
        path_prefix,
        get_reranker(settings),
    )
    return [
        {
            "path": h.path,
            "section": h.heading_path,
            "chunk_index": h.chunk_index,
            "score": round(h.rerank_score if h.rerank_score is not None else h.score, 4),
            "content": h.content,
        }
        for h in hits
    ]


@mcp.tool()
def list_documents(path_prefix: str | None = None, limit: int = 200) -> list[dict]:
    """Listaa indeksoidut dokumentit, valinnaisesti kansiopolun alta."""
    rows = (
        _get_conn()
        .execute(
            """
        SELECT d.path, d.parser, d.indexed_at, count(c.id) AS chunks
        FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
        WHERE (%(prefix)s::text IS NULL OR starts_with(d.path, %(prefix)s))
        GROUP BY d.id ORDER BY d.path LIMIT %(limit)s
        """,
            {"prefix": path_prefix, "limit": min(limit, 1000)},
        )
        .fetchall()
    )
    return [
        {
            "path": r["path"],
            "parser": r["parser"],
            "chunks": r["chunks"],
            "indexed_at": r["indexed_at"].isoformat(),
        }
        for r in rows
    ]


@mcp.tool()
def read_document(path: str, offset: int = 0, max_chars: int = 40000) -> str:
    """Lukee indeksoidun dokumentin koko tekstin (vain indeksoidut tiedostot ovat luettavissa).

    Pitkiä dokumentteja voi lukea osissa offset-parametrin avulla.
    """
    row = _get_conn().execute("SELECT 1 FROM documents WHERE path = %s", (path,)).fetchone()
    if row is None:
        return f"Not an indexed document: {path}"
    parsed = parse(Path(path))
    if parsed is None:
        return f"Could not parse: {path}"
    text = parsed.text
    part = text[offset : offset + max_chars]
    end = offset + len(part)
    if end < len(text):
        part += f"\n\n[... truncated, {len(text) - end} chars left; use offset={end}]"
    return part


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
