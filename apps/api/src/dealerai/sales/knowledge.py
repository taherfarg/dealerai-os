"""Turning a dealer's document into something a draft can quote.

Chunking is on headings first and size second, and the heading path is
prepended to every chunk. A paragraph that says "the buyer pays it" is useless
on its own and correct under "Export › Customs — Algeria"; retrieval returns
paragraphs, so the paragraph has to carry its own context.

Inventory is never embedded (DealerAI OS 04 § 1). Prices and stock are SQL, and
a vector that thinks it knows a price is the one thing this product may not
have.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from uuid import UUID

from ..ai.embeddings import embed, literal
from ..core.errors import Unusable
from ..db.queries import copilot as q
from ..db.session import tenant_session

#: Roughly four characters to a token — near enough for a size bound, and there
#: is no tokenizer in this process. The spec's 400–800 tokens becomes this.
CHARS_PER_TOKEN = 4
MIN_CHUNK = 400 * CHARS_PER_TOKEN
MAX_CHUNK = 800 * CHARS_PER_TOKEN

TEXT_TYPES = frozenset({"text/plain", "text/markdown", "text/csv"})
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ACCEPTED = frozenset({PDF, DOCX, *TEXT_TYPES})

#: A markdown heading, or a Setext one underlined with === or ---. Word gives us
#: its own heading levels and they are converted to markdown on extraction.
_HEADING = re.compile(r"^(#{1,4})[ \t]+(.*)$|^([^\n#][^\n]{0,70})\n[=-]{3,}[ \t]*$", re.M)


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    #: The heading path this paragraph sits under, "Export › Customs — Algeria".
    heading: str
    content: str


def extract(data: bytes, mime: str, filename: str | None = None) -> str:
    """The document's text, or a 422 a person can act on."""
    if mime == PDF:
        return _from_pdf(data)
    if mime == DOCX:
        return _from_docx(data)
    if mime in TEXT_TYPES:
        return data.decode("utf-8", errors="replace").strip()
    raise Unusable(f"{filename or 'this file'} is a {mime}; upload a PDF, a Word file or text")


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 - pypdf raises a dozen unrelated types
        raise Unusable(f"this PDF could not be read: {exc}") from exc


def _from_docx(data: bytes) -> str:
    """Word's own heading levels, converted to markdown ones.

    The structure is already in the file; guessing at it from capitalisation
    when Word has told us would be inventing a problem.
    """
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
        lines = []
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style else ""
            level = re.match(r"Heading (\d)", style or "")
            lines.append(f"{'#' * min(int(level.group(1)), 4)} {text}" if level else text)
    except Unusable:
        raise
    except Exception as exc:  # noqa: BLE001 - python-docx raises much the same spread
        raise Unusable(f"this Word file could not be read: {exc}") from exc
    return "\n\n".join(lines)


def chunk(text: str) -> list[Chunk]:
    """Split on headings, then on size, keeping the heading path on each piece."""
    chunks: list[Chunk] = []
    for heading, body in _sections(text):
        for piece in _split(body):
            chunks.append(Chunk(index=len(chunks), heading=heading, content=piece))
    return chunks


def embeddable(piece: Chunk) -> str:
    """What is actually embedded: the heading path, then the text."""
    return f"{piece.heading}\n{piece.content}" if piece.heading else piece.content


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading path, body). One unnamed section for a document with no headings."""
    matches = list(_HEADING.finditer(text))
    if not matches:
        stripped = text.strip()
        return [("", stripped)] if stripped else []

    out: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        out.append(("", preamble))

    path: list[str] = []
    for position, match in enumerate(matches):
        # A Setext heading has no hashes, so it is a level-1 heading.
        level = len(match.group(1) or "#")
        title = (match.group(2) or match.group(3) or "").strip()
        path = path[: level - 1] + [title]
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            out.append((" › ".join(path), body))
    return out


def _split(body: str) -> list[str]:
    """Paragraphs joined up to MAX_CHUNK, never breaking one in half.

    A paragraph longer than the maximum goes through whole. Cutting a sentence
    at 3,200 characters produces two chunks that are each wrong, and a policy
    clause that long is exactly the one somebody will ask about.
    """
    pieces: list[str] = []
    current = ""
    for paragraph in re.split(r"\n{2,}", body):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > MAX_CHUNK:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    # A tail too small to stand alone belongs with the piece before it: "See
    # annex B." retrieved on its own answers nothing.
    if len(pieces) > 1 and len(pieces[-1]) < MIN_CHUNK // 2:
        # Popped first: `pieces[-2] = ... pieces.pop()` evaluates the pop before
        # the index, so with two pieces it assigns past the end of the shrunken
        # list. Python is right and the one-liner was wrong.
        tail = pieces.pop()
        pieces[-1] = f"{pieces[-1]}\n\n{tail}"
    return pieces


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

#: Retrieved, then used. Fetching more than we show is what makes the fusion
#: worth doing — the fourth vector hit is often the first text hit.
RETRIEVE = 8
USE = 4


@dataclass(frozen=True, slots=True)
class Passage:
    chunk_id: int
    document_id: str
    title: str
    heading: str
    content: str
    score: float


async def search(
    tenant_id: UUID, query: str, *, use: int = USE, run_id: UUID | None = None
) -> list[Passage]:
    """The paragraphs most likely to answer this question, in this tenant only.

    Hybrid, because the question arrives in Arabic and the policy is written in
    English: vector search crosses the language, and full-text search catches
    what vectors are worst at — an exact token like "Annex B", a port name, an
    HS code.
    """
    text = query.strip()
    if not text:
        return []  # an empty question is not worth a vector
    vectors = await embed([text], tenant_id=tenant_id, kind="query", run_id=run_id)
    async with tenant_session(tenant_id) as conn:
        rows = await conn.fetch(
            q.SEARCH_KNOWLEDGE, tenant_id, literal(vectors[0]), text, RETRIEVE, use
        )
    return [
        Passage(
            chunk_id=row["id"],
            document_id=str(row["document_id"]),
            title=row["title"] or "",
            heading=row["heading"] or "",
            content=row["content"],
            score=row["score"],
        )
        for row in rows
    ]
