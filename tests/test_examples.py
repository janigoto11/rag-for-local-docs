"""Demokorpuksen ja sen eval-kysymysten eheys (ei vaadi tietokantaa).

Varmistaa, että jokainen odotettu teksti on kokonaisena jossain palassa ja vain oikeissa
tiedostoissa. Jos pilkkomista muutetaan niin, että teksti katkeaa palojen rajalle,
palatason eval ei voisi enää koskaan onnistua, ja tämä testi kertoo siitä.
"""

import pytest

from localrag.chunking import chunk_document
from localrag.config import Settings
from localrag.evaluation import as_list, load_questions, normalize_text
from localrag.parsing import parse

from .conftest import EXAMPLES_DIR

QUESTIONS = load_questions(EXAMPLES_DIR / "questions.yaml")


@pytest.fixture(scope="module")
def chunks_by_file() -> dict[str, list[str]]:
    settings = Settings(_env_file=None)
    result = {}
    for path in sorted((EXAMPLES_DIR / "docs").iterdir()):
        parsed = parse(path)
        assert parsed is not None, f"Ei voitu parsia: {path.name}"
        chunks = chunk_document(
            parsed.text, parsed.format, settings.chunk_target_tokens, settings.chunk_overlap_tokens
        )
        result[path.name] = [normalize_text(c.content) for c in chunks]
    return result


def test_every_question_has_expected_text():
    missing = [q["question"] for q in QUESTIONS if not as_list(q.get("expected_text"))]
    assert missing == []


@pytest.mark.parametrize("item", QUESTIONS, ids=lambda q: q["question"][:40])
def test_expected_text_is_found_only_in_expected_files(item, chunks_by_file):
    for text in map(normalize_text, as_list(item.get("expected_text"))):
        files = {name for name, chunks in chunks_by_file.items() if any(text in c for c in chunks)}
        assert files, f"Teksti {text!r} ei ole kokonaisena missään palassa"
        unexpected = {f for f in files if not any(e in f for e in item["expected"])}
        assert not unexpected, f"Teksti {text!r} löytyy myös tiedostoista {unexpected}"


def test_expected_files_exist():
    names = [p.name for p in (EXAMPLES_DIR / "docs").iterdir()]
    for item in QUESTIONS:
        for expected in item["expected"]:
            assert any(expected in n for n in names), f"Ei tiedostoa: {expected}"


def test_pdf_sources_match_generated_pdfs():
    sources = {p.stem for p in (EXAMPLES_DIR / "pdf-sources").glob("*.md")}
    pdfs = {p.stem for p in (EXAMPLES_DIR / "docs").glob("*.pdf")}
    assert sources == pdfs, "Aja: uv run python scripts/generate_example_pdfs.py"
