"""Rakenteen huomioiva pilkkominen.

Markdown jaetaan ensin osioihin otsikoiden mukaan (otsikkopolku säilytetään metatietona),
minkä jälkeen kukin osio pakataan kappale kerrallaan tavoitekokoon pienellä päällekkäisyydellä.
Tokenimäärä arvioidaan kaavalla merkit / 4, mikä riittää kokojen mitoitukseen.
"""

import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 4
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Chunk:
    index: int
    heading_path: str
    content: str
    token_count: int


def approx_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Palauttaa (otsikkopolku, sisältö) -parit. Koodilohkojen sisäiset otsikot ohitetaan."""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            sections.append((" > ".join(title for _, title in stack), content))
        body.clear()

    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2).strip()))
        else:
            body.append(line)
    flush()
    return sections


def _split_long(text: str, max_chars: int) -> list[str]:
    """Pilkkoo liian pitkän palan riveittäin, sitten lauseittain, sanoittain ja lopulta väkisin."""
    for sep in ("\n", ". ", " "):
        parts = text.split(sep)
        if len(parts) < 2:
            continue
        out: list[str] = []
        cur = ""
        for part in parts:
            candidate = f"{cur}{sep}{part}" if cur else part
            if len(candidate) <= max_chars:
                cur = candidate
            else:
                if cur:
                    out.append(cur)
                cur = part
        if cur:
            out.append(cur)
        result: list[str] = []
        for piece in out:
            result.extend(_split_long(piece, max_chars) if len(piece) > max_chars else [piece])
        return result
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _overlap_tail(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    tail = text[-overlap_chars:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def pack_paragraphs(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paragraphs:
        pieces.extend(_split_long(p, max_chars) if len(p) > max_chars else [p])

    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + 2 + len(piece) > max_chars:
            chunks.append(cur)
            tail = _overlap_tail(cur, overlap_chars)
            cur = (
                f"{tail}\n\n{piece}" if tail and len(tail) + 2 + len(piece) <= max_chars else piece
            )
        else:
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur.strip():
        chunks.append(cur)
    return chunks


def chunk_document(
    text: str, fmt: str, target_tokens: int = 500, overlap_tokens: int = 60
) -> list[Chunk]:
    max_chars = target_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    sections = split_markdown_sections(text) if fmt == "markdown" else [("", text)]

    chunks: list[Chunk] = []
    for heading_path, body in sections:
        for content in pack_paragraphs(body, max_chars, overlap_chars):
            chunks.append(Chunk(len(chunks), heading_path, content, approx_tokens(content)))
    return chunks


def embedding_text(file_name: str, chunk: Chunk) -> str:
    """Varsinaisesti embeddattava teksti: lyhyt kontekstiotsake ja pala.

    Otsakkeen ansiosta palan kuten "Määräaika on 31.3." löytää myös kysymyksellä,
    joka mainitsee dokumentin tai osion, johon pala kuuluu.
    """
    header = f"File: {file_name}"
    if chunk.heading_path:
        header += f"\nSection: {chunk.heading_path}"
    return f"{header}\n\n{chunk.content}"
