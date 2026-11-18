"""Tulosten uudelleenjärjestys (reranking) cross-encoder-mallilla.

Hybridihaku hakee ensin joukon ehdokkaita (LOCALRAG_RERANK_CANDIDATES), ja reranker
pisteyttää jokaisen ehdokkaan lukemalla kysymyksen ja palan yhdessä. Tämä on tarkempaa kuin
embeddingien vertailu, koska malli näkee molemmat tekstit samaan aikaan, mutta myös hitaampaa,
joten sitä käytetään vain kärkiehdokkaisiin.

Oletusmalli BAAI/bge-reranker-v2-m3 on monikielinen (myös suomi) ja ajetaan paikallisesti
ONNX Runtimella fastembed-kirjaston kautta. Malli ladataan ensimmäisellä käyttökerralla.
"""

import logging
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .config import Settings

log = logging.getLogger(__name__)


class Reranker(Protocol):
    model: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


class RerankerUnavailableError(RuntimeError):
    pass


class FastembedReranker:
    def __init__(self, model: str, cache_dir: Path):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as e:
            raise RerankerUnavailableError(
                "fastembed-kirjasto puuttuu. Asenna riippuvuudet: uv sync"
            ) from e
        supported = {m["model"] for m in TextCrossEncoder.list_supported_models()}
        if model not in supported:
            raise RerankerUnavailableError(
                f"fastembed ei tue reranker-mallia {model}. Tuetut: {', '.join(sorted(supported))}"
            )
        self.model = model
        cache_dir.mkdir(parents=True, exist_ok=True)
        log.info("Ladataan reranker-malli %s (%s)", model, cache_dir)
        try:
            self._encoder = TextCrossEncoder(model_name=model, cache_dir=str(cache_dir))
        except Exception as e:  # lataus tai mallin avaus epäonnistui
            raise RerankerUnavailableError(
                f"Reranker-mallin {model} lataus epäonnistui ({e}). Tarkista verkkoyhteys "
                "tai poista reranker käytöstä: LOCALRAG_RERANKER=none"
            ) from e

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        return [float(s) for s in self._encoder.rerank(query, list(texts))]


@lru_cache(maxsize=2)
def _load_fastembed(model: str, cache_dir: str) -> FastembedReranker:
    # Mallin lataus kestää sekunteja, joten sama instanssi käytetään koko prosessin ajan.
    return FastembedReranker(model, Path(cache_dir))


def get_reranker(settings: Settings) -> Reranker | None:
    if settings.reranker == "none":
        return None
    cache_dir = Path(settings.model_cache_dir).expanduser()
    return _load_fastembed(settings.rerank_model, str(cache_dir))


def rerank_text(file_name: str, heading_path: str, content: str) -> str:
    """Rerankerille annettava teksti: sama kontekstiotsake kuin embeddingeissä."""
    header = f"{file_name} - {heading_path}" if heading_path else file_name
    return f"{header}\n{content}"
