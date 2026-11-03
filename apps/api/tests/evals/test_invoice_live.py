"""Live eval: does a real model read a purchase invoice well enough to check?

Excluded from the default run. `npm run eval:invoice`

test_acquisition.py proves the checks — quotes, totals, rates — with a stubbed
reading. This answers what the stub cannot: whether Gemini, given a photograph
of an auction invoice, returns amounts *as printed* and quotes that contain
them, so the checks pass on a good reading rather than rejecting everything.

The invoice is drawn here rather than kept as a file: a real auction receipt
carries a real buyer's name and a real VIN, and neither belongs in a repository.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.lifecycle.invoices import read

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

LINES = [
    "COPART  -  BUYER INVOICE",
    "Invoice No: INV-88123          Date: 2026-10-01",
    "Lot 41871233   2024 TOYOTA LAND CRUISER   VIN JTMABBBJ0RA000001",
    "",
    "Sale Price ............................ 12,500.00",
    "Buyer Fee ................................ 675.00",
    "Gate Fee .................................. 79.00",
    "Virtual Bid Fee .......................... 129.00",
    "Environmental Fee .......................... 15.00",
    "",
    "TOTAL DUE (USD) ....................... 13,398.00",
    "Paid by wire transfer",
]


def _invoice(lines: list[str]) -> bytes:
    """A plain receipt, as a phone would photograph a printout."""
    try:
        font = ImageFont.truetype("cour.ttf", 22)
    except OSError:
        font = ImageFont.load_default(size=22)
    img = Image.new("RGB", (1000, 60 + 36 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, text in enumerate(lines):
        draw.text((40, 30 + 36 * i), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_an_auction_invoice_is_read_whole(db: None, seeded: None) -> None:
    proposal = await read(tenant_id=TENANT_A, data=_invoice(LINES), mime_type="image/png")

    assert proposal.currency == "USD"
    amounts = sorted(line.amount_minor for line in proposal.lines)
    assert amounts == sorted([1_250_000, 67_500, 7_900, 12_900, 1_500]), (
        f"read {amounts}; warnings: {proposal.warnings}"
    )
    assert proposal.total_minor == 1_339_800
    assert proposal.warnings == [], proposal.warnings
    assert proposal.reference == "INV-88123"


async def test_the_sale_price_is_the_purchase_line(db: None, seeded: None) -> None:
    proposal = await read(tenant_id=TENANT_A, data=_invoice(LINES), mime_type="image/png")
    purchase = [line for line in proposal.lines if line.category == "purchase"]
    assert [line.amount_minor for line in purchase] == [1_250_000]


async def test_no_exchange_rate_is_invented(db: None, seeded: None) -> None:
    """The invoice prints none. A model that knows the dirham peg must not
    supply it — a rate is a fact with a source, and this document is not one."""
    proposal = await read(tenant_id=TENANT_A, data=_invoice(LINES), mime_type="image/png")
    assert proposal.fx_rate is None


async def test_a_line_left_out_is_caught_by_the_total(db: None, seeded: None) -> None:
    """Take a line off the printout but keep its total: a faithful reading must
    now fail to add up, and the proposal must say so."""
    tampered = [line for line in LINES if not line.startswith("Gate Fee")]
    proposal = await read(tenant_id=TENANT_A, data=_invoice(tampered), mime_type="image/png")
    assert any("missing" in warning for warning in proposal.warnings), proposal.warnings
