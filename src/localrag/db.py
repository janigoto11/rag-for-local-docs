import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from .config import Settings


class SchemaMismatchError(RuntimeError):
    pass


def connect(settings: Settings) -> psycopg.Connection:
    conn = psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def ensure_schema(conn: psycopg.Connection, settings: Settings) -> None:
    dim = int(settings.embedding_dim)
    with conn.transaction():
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key text PRIMARY KEY, value text NOT NULL)")
        rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        if rows:
            stored = (rows.get("embedding_model"), rows.get("embedding_dim"))
            wanted = (settings.embedding_model, str(dim))
            if stored != wanted:
                raise SchemaMismatchError(
                    f"Database was indexed with model={stored[0]} dim={stored[1]}, "
                    f"but config has model={wanted[0]} dim={wanted[1]}. "
                    "Run `localrag reset` and re-index."
                )
        else:
            conn.execute(
                "INSERT INTO meta (key, value) "
                "VALUES ('embedding_model', %s), ('embedding_dim', %s)",
                (settings.embedding_model, str(dim)),
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id          bigserial PRIMARY KEY,
                path        text NOT NULL UNIQUE,
                sha256      text NOT NULL,
                mtime_ns    bigint NOT NULL,
                size        bigint NOT NULL,
                parser      text NOT NULL,
                indexed_at  timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id            bigserial PRIMARY KEY,
                document_id   bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index   int NOT NULL,
                heading_path  text NOT NULL DEFAULT '',
                content       text NOT NULL,
                token_count   int NOT NULL,
                embedding     vector({dim}) NOT NULL,
                tsv           tsvector NOT NULL,
                UNIQUE (document_id, chunk_index)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw "
            "ON chunks USING hnsw (embedding vector_cosine_ops)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv)")


def reset(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute("DROP TABLE IF EXISTS chunks, documents, meta CASCADE")
