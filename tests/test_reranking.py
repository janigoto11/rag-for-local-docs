"""Rerankerin konfiguraatio ilman mallin latausta (ei verkkoa, ei tietokantaa)."""

import pytest
from fastembed.rerank.cross_encoder import TextCrossEncoder

from localrag.config import Settings
from localrag.reranking import RerankerUnavailableError, get_reranker, rerank_text


def test_reranker_is_off_by_default():
    assert get_reranker(Settings(_env_file=None)) is None


def test_default_rerank_model_is_supported_by_fastembed():
    supported = {m["model"] for m in TextCrossEncoder.list_supported_models()}
    assert Settings(_env_file=None).rerank_model in supported


def test_unknown_model_gives_clear_error(tmp_path):
    settings = Settings(
        _env_file=None,
        reranker="fastembed",
        rerank_model="no-such/reranker",
        model_cache_dir=str(tmp_path),
    )
    with pytest.raises(RerankerUnavailableError, match="no-such/reranker"):
        get_reranker(settings)


def test_rerank_text_includes_context():
    assert rerank_text("ohje.pdf", "Page 2", "Sisältö") == "ohje.pdf - Page 2\nSisältö"
    assert rerank_text("ohje.txt", "", "Sisältö") == "ohje.txt\nSisältö"
