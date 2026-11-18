from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LOCALRAG_", extra="ignore")

    database_url: str = "postgresql://localrag:localrag@localhost:5433/localrag"

    embedding_provider: Literal["ollama", "openai"] = "ollama"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    # Jotkin mallit (esim. nomic-embed-text, e5) odottavat tehtäväkohtaisia etuliitteitä.
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""
    embed_batch_size: int = 32

    ollama_url: str = "http://localhost:11434"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    chunk_target_tokens: int = 500
    chunk_overlap_tokens: int = 60

    max_file_mb: int = 50

    search_candidates: int = 50
    # Poistetaanko täytesanat (stopwords.py) tekstihaun kyselystä
    fts_stopwords: bool = True
    rrf_k: int = 60

    # Reranker: "none" tai "fastembed" (paikallinen cross-encoder, ks. reranking.py)
    reranker: Literal["none", "fastembed"] = "none"
    rerank_model: str = "BAAI/bge-reranker-v2-m3-int8"
    rerank_candidates: int = 10
    model_cache_dir: str = "~/.cache/localrag/models"
    hnsw_ef_search: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
