"""Turning a document into paragraphs a draft can quote. Pure: no model, no database."""

from __future__ import annotations

import io

import pytest

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
