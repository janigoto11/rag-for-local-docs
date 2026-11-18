from typing import Protocol

import httpx

from .config import Settings


class Embedder(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(self, settings: Settings):
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self._client = httpx.Client(base_url=settings.ollama_url, timeout=600)

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.post("/api/embed", json={"model": self.model, "input": texts})
        resp.raise_for_status()
        return resp.json()["embeddings"]


class OpenAIEmbedder:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ValueError("LOCALRAG_OPENAI_API_KEY is not set")
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self._client = httpx.Client(
            base_url=settings.openai_base_url,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            timeout=120,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.post(
            "/embeddings", json={"model": self.model, "input": texts, "dimensions": self.dim}
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


class EmbedderUnavailableError(RuntimeError):
    pass


def check_embedder(embedder: Embedder, settings: Settings) -> None:
    """Tarkistaa yhdellä testikutsulla, että embedding-palvelu vastaa ja malli on saatavilla."""
    try:
        embedder.embed(["yhteystesti"])
    except httpx.ConnectError as e:
        if settings.embedding_provider == "ollama":
            raise EmbedderUnavailableError(
                f"Ollamaan ei saada yhteyttä osoitteessa {settings.ollama_url}. "
                "Käynnistä palvelut: scripts/services.sh start"
            ) from e
        raise EmbedderUnavailableError(f"Embedding-palveluun ei saada yhteyttä: {e}") from e
    except httpx.HTTPStatusError as e:
        if settings.embedding_provider == "ollama" and e.response.status_code == 404:
            model = settings.embedding_model
            raise EmbedderUnavailableError(
                f"Ollamasta puuttuu malli {model}. Lataa se: ollama pull {model}"
            ) from e
        raise EmbedderUnavailableError(
            f"Embedding-palvelu palautti virheen {e.response.status_code}: {e.response.text[:300]}"
        ) from e


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    return OllamaEmbedder(settings)


def embed_batched(embedder: Embedder, texts: list[str], batch_size: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = embedder.embed(texts[i : i + batch_size])
        for v in batch:
            if len(v) != embedder.dim:
                raise ValueError(
                    f"Model {embedder.model} returned dim {len(v)}, "
                    f"config says {embedder.dim}. Fix LOCALRAG_EMBEDDING_DIM."
                )
        vectors.extend(batch)
    return vectors
