"""Turning a document into paragraphs a draft can quote. Pure: no model, no database."""

from __future__ import annotations

import io
import uuid
from collections.abc import Sequence
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B
from dealerai.ai.models import EMBEDDING_DIMENSIONS
from dealerai.core.errors import Unusable
from dealerai.sales import knowledge


def test_a_heading_travels_with_its_paragraph() -> None:
    """'The buyer pays it' is useless alone and correct under its heading."""
    pieces = knowledge.chunk("# Export\n## Customs — Algeria\nThe buyer pays it.\n")
    assert pieces[0].heading == "Export › Customs — Algeria"
    assert knowledge.embeddable(pieces[0]).startswith("Export › Customs — Algeria")


def test_a_deeper_heading_keeps_the_path_above_it() -> None:
    pieces = knowledge.chunk(
        "# Export\nGeneral rules.\n\n## Algeria\nSpecific.\n\n## Morocco\nOther.\n"
    )
    assert [piece.heading for piece in pieces] == [
        "Export",
        "Export › Algeria",
        "Export › Morocco",
    ]


def test_a_sibling_heading_replaces_rather_than_nests() -> None:
    pieces = knowledge.chunk("# One\nA.\n\n# Two\nB.\n")
    assert [piece.heading for piece in pieces] == ["One", "Two"]


def test_text_before_the_first_heading_is_not_lost() -> None:
    pieces = knowledge.chunk("Pollux Motors export policy, 2026.\n\n# Shipping\nBy sea.\n")
    assert pieces[0].heading == ""
    assert "2026" in pieces[0].content


def test_a_document_with_no_headings_is_still_one_chunk() -> None:
    pieces = knowledge.chunk("Shipping takes about three weeks.")
    assert len(pieces) == 1
    assert pieces[0].heading == ""


def test_an_empty_document_has_no_chunks() -> None:
    assert knowledge.chunk("   \n\n  ") == []


def test_a_long_section_splits_on_paragraphs_never_mid_sentence() -> None:
    body = "\n\n".join(["A policy sentence that is quite long. " * 20] * 6)
    pieces = knowledge.chunk(f"# Policy\n{body}")
    assert len(pieces) > 1
    assert all(piece.content.strip().endswith(".") for piece in pieces)
    assert all(piece.heading == "Policy" for piece in pieces)


def test_a_paragraph_bigger_than_the_maximum_goes_through_whole() -> None:
    """Cutting it produces two chunks that are each wrong."""
    giant = "x" * (knowledge.MAX_CHUNK + 500)
    assert knowledge.chunk(f"# Policy\n{giant}")[0].content == giant


def test_a_stray_tail_joins_the_chunk_before_it() -> None:
    """'See annex B.' retrieved on its own answers nothing."""
    body = ("Sentence. " * 400) + "\n\nSee annex B."
    pieces = knowledge.chunk(f"# Policy\n{body}")
    assert len(pieces) == 1
    assert pieces[0].content.endswith("See annex B.")


def test_chunks_are_numbered_across_the_whole_document() -> None:
    pieces = knowledge.chunk("# One\nA.\n\n# Two\nB.\n\n# Three\nC.\n")
    assert [piece.index for piece in pieces] == [0, 1, 2]


def test_a_plain_text_file_is_read_as_written() -> None:
    assert knowledge.extract(b"# Export\nBy sea.", "text/plain") == "# Export\nBy sea."


def test_a_file_that_is_not_utf8_is_read_rather_than_refused() -> None:
    """A dealership's FAQ saved from Windows should not be a support ticket."""
    assert "Export" in knowledge.extract(b"Export policy \xff\xfe", "text/plain")


def test_an_unreadable_pdf_says_so_rather_than_raising_something_random() -> None:
    with pytest.raises(Unusable, match="could not be read"):
        knowledge.extract(b"%PDF-1.4 truncated", "application/pdf")


def test_a_video_is_refused_by_name() -> None:
    with pytest.raises(Unusable, match="video/mp4"):
        knowledge.extract(b"\x00", "video/mp4", "walkaround.mp4")


def test_a_real_docx_keeps_its_heading_levels() -> None:
    """Built here rather than committed as a fixture: the point is the mapping
    from Word's own styles to ours, and a binary fixture hides it."""
    import docx

    document = docx.Document()
    document.add_heading("Export policy", level=1)
    document.add_paragraph("Shipping is arranged by the buyer.")
    document.add_heading("Algeria", level=2)
    document.add_paragraph("A certificate of origin is required.")
    buffer = io.BytesIO()
    document.save(buffer)

    text = knowledge.extract(buffer.getvalue(), knowledge.DOCX)
    assert text.startswith("# Export policy")
    assert "## Algeria" in text
    pieces = knowledge.chunk(text)
    assert pieces[-1].heading == "Export policy › Algeria"


def test_a_docx_that_is_not_one_says_so() -> None:
    with pytest.raises(Unusable, match="Word file could not be read"):
        knowledge.extract(b"not a zip at all", knowledge.DOCX)


def test_a_real_pdf_is_read() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    # A blank page has no text; what matters is that it parses rather than
    # raising, so an empty document fails later with a sentence about text.
    assert knowledge.extract(buffer.getvalue(), knowledge.PDF) == ""


# ---------------------------------------------------------------------------
# Retrieval. The embedder is stubbed so the vectors are ours to choose; what is
# being tested is the fusion, and the filters that keep it honest.
# ---------------------------------------------------------------------------


def _vector(seed: float) -> list[float]:
    """A vector that is close to itself and far from the others."""
    return [seed] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


@pytest.fixture
def stub_embed(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Whatever the question was, embed it as the vector we chose for it."""
    state: dict[str, Any] = {"calls": [], "answer": _vector(1.0)}

    async def fake(texts: Sequence[str], **kwargs: Any) -> list[list[float]]:
        state["calls"].append(list(texts))
        return [state["answer"] for _ in texts]

    monkeypatch.setattr(knowledge, "embed", fake)
    return state


async def _a_document(
    su: asyncpg.Connection,
    chunks: list[tuple[str, list[float]]],
    *,
    status: str = "ready",
    tenant_id: uuid.UUID = TENANT_A,
    title: str = "Export policy",
) -> uuid.UUID:
    from dealerai.ai.embeddings import literal

    document_id = await su.fetchval(
        """insert into documents (tenant_id, kind, title, source, status)
           values ($1, 'export_policy', $2, 'upload', $3) returning id""",
        tenant_id,
        title,
        status,
    )
    for index, (content, vector) in enumerate(chunks):
        await su.execute(
            """insert into doc_chunks (tenant_id, document_id, chunk_index, content, embedding)
               values ($1, $2, $3, $4, $5::vector)""",
            tenant_id,
            document_id,
            index,
            content,
            literal(vector),
        )
    return uuid.UUID(str(document_id))


async def test_the_nearest_paragraph_comes_back_first(
    db: None, su: asyncpg.Connection, seeded: None, stub_embed: dict[str, Any]
) -> None:
    await _a_document(
        su,
        [
            ("Shipping runs weekly from Jebel Ali.", _vector(1.0)),
            ("Warranty is two years or 60,000 km.", _vector(-1.0)),
        ],
    )
    passages = await knowledge.search(TENANT_A, "when do you ship")
    assert passages[0].content.startswith("Shipping")
    assert passages[0].title == "Export policy"


async def test_a_word_only_a_text_search_can_find_still_ranks(
    db: None, su: asyncpg.Connection, seeded: None, stub_embed: dict[str, Any]
) -> None:
    """'Annex B' is a token, not a meaning. Vectors are poor at it, and this is
    exactly what the second half of the fusion is for."""
    await _a_document(
        su,
        [
            ("Nothing relevant about shipping at all.", _vector(1.0)),
            ("Annex B lists the customs codes.", _vector(-1.0)),
        ],
    )
    passages = await knowledge.search(TENANT_A, "Annex B")
    assert any("Annex B" in passage.content for passage in passages)


async def test_a_document_still_processing_is_never_quoted(
    db: None, su: asyncpg.Connection, seeded: None, stub_embed: dict[str, Any]
) -> None:
    await _a_document(su, [("Shipping runs weekly.", _vector(1.0))], status="processing")
    assert await knowledge.search(TENANT_A, "shipping") == []


async def test_a_deleted_document_stops_being_quoted_immediately(
    db: None, su: asyncpg.Connection, seeded: None, stub_embed: dict[str, Any]
) -> None:
    document_id = await _a_document(su, [("Shipping runs weekly.", _vector(1.0))])
    assert await knowledge.search(TENANT_A, "shipping")
    await su.execute("delete from documents where id = $1", document_id)
    assert await knowledge.search(TENANT_A, "shipping") == []


async def test_another_workspaces_policy_is_invisible(
    db: None, su: asyncpg.Connection, seeded: None, stub_embed: dict[str, Any]
) -> None:
    """The one that matters most: retrieval is a query somebody could write
    without a tenant filter, and the failure would be silent."""
    await _a_document(su, [("Beta's secret shipping terms.", _vector(1.0))], tenant_id=TENANT_B)
    assert await knowledge.search(TENANT_A, "shipping") == []


async def test_only_as_many_passages_as_asked_for(
    db: None, su: asyncpg.Connection, seeded: None, stub_embed: dict[str, Any]
) -> None:
    await _a_document(su, [(f"Clause {n} about shipping.", _vector(1.0)) for n in range(6)])
    assert len(await knowledge.search(TENANT_A, "shipping", use=2)) == 2


async def test_an_empty_question_costs_nothing(
    db: None, seeded: None, stub_embed: dict[str, Any]
) -> None:
    """Guards against embedding a blank string every time the model calls the
    tool with no arguments."""
    assert await knowledge.search(TENANT_A, "   ") == []
    assert stub_embed["calls"] == []


async def test_a_question_is_embedded_as_a_question(
    db: None,
    su: asyncpg.Connection,
    seeded: None,
    stub_embed: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query and a document go into the same space by different instructions,
    and using one for both measurably costs recall."""
    kinds: list[str] = []

    async def fake(texts: Sequence[str], **kwargs: Any) -> list[list[float]]:
        kinds.append(str(kwargs["kind"]))
        return [_vector(1.0)]

    monkeypatch.setattr(knowledge, "embed", fake)
    await _a_document(su, [("Shipping runs weekly.", _vector(1.0))])
    await knowledge.search(TENANT_A, "shipping")
    assert kinds == ["query"]
