from localrag.chunking import (
    chunk_document,
    embedding_text,
    pack_paragraphs,
    split_markdown_sections,
)


def test_sections_follow_heading_hierarchy():
    md = "# A\nintro\n## B\nb text\n### C\nc text\n## D\nd text\n"
    sections = split_markdown_sections(md)
    assert sections == [
        ("A", "intro"),
        ("A > B", "b text"),
        ("A > B > C", "c text"),
        ("A > D", "d text"),
    ]


def test_headings_inside_code_fences_are_ignored():
    md = "# Real\n```bash\n# not a heading\necho hi\n```\n"
    sections = split_markdown_sections(md)
    assert len(sections) == 1
    assert sections[0][0] == "Real"
    assert "# not a heading" in sections[0][1]


def test_chunks_respect_max_size():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 80 for i in range(30))
    chunks = pack_paragraphs(text, max_chars=1000, overlap_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)


def test_long_paragraph_is_split():
    text = "sentence number one. " * 500
    chunks = pack_paragraphs(text, max_chars=400, overlap_chars=0)
    assert all(len(c) <= 400 for c in chunks)
    assert "".join(chunks).count("sentence") == 500


def test_overlap_carries_tail_of_previous_chunk():
    paras = [f"p{i} " + "x " * 100 for i in range(4)]
    chunks = pack_paragraphs("\n\n".join(paras), max_chars=500, overlap_chars=60)
    assert len(chunks) >= 2
    assert chunks[1].startswith("x")  # alkaa palan 0 päällekkäisellä osuudella


def test_chunk_document_indexes_and_context_header():
    md = "# Guide\n## Setup\nInstall it.\n## Usage\nRun it.\n"
    chunks = chunk_document(md, "markdown")
    assert [c.index for c in chunks] == [0, 1]
    assert chunks[1].heading_path == "Guide > Usage"
    text = embedding_text("guide.md", chunks[1])
    assert text.startswith("File: guide.md\nSection: Guide > Usage")
