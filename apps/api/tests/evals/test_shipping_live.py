"""Live eval: does a real model read a bill of lading well enough to match it?

Excluded from the default run. `npm run eval:shipping`

test_inbound.py proves the matching with a stubbed reading. This answers what
the stub cannot: whether Gemini, not told the VIN, reads every VIN on the paper
as printed, with the line it is on, so the right car matches and only it.

The document is drawn here rather than kept as a file: a real bill of lading
names a real shipper and a real consignee.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from PIL import Image, ImageDraw, ImageFont

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.lifecycle.inbound import read

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

OURS = "1C4RJFBG5MC000123"
THEIRS = "5YJ3E1EA7KF000456"
TODAY = date(2026, 11, 4)

LINES = [
    "MSC MEDITERRANEAN SHIPPING COMPANY          BILL OF LADING",
    "B/L No. MEDU8812345                        Shipped on board: 2026-10-20",
    "Vessel: MSC AURORA   Voyage: 644E          Container: MSCU1234567 (40' HC)",
    "Port of loading: HOUSTON, TX, USA          Port of discharge: JEBEL ALI, UAE",
    "ETA Jebel Ali: 2026-11-18",
    "",
    "Description of goods: 2 used motor vehicles",
    f"  1. 2021 JEEP GRAND CHEROKEE   VIN {OURS}",
    f"  2. 2019 TESLA MODEL 3         VIN {THEIRS}",
    "",
    "Freight prepaid",
]


def _document(lines: list[str]) -> bytes:
    try:
        font = ImageFont.truetype("cour.ttf", 22)
    except OSError:
        font = ImageFont.load_default(size=22)
    img = Image.new("RGB", (1100, 60 + 36 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, text in enumerate(lines):
        draw.text((40, 30 + 36 * i), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_a_bill_of_lading_is_read_and_matched(db: None, seeded: None) -> None:
    proposal = await read(
        tenant_id=TENANT_A, data=_document(LINES), mime_type="image/png", car_vin=OURS, today=TODAY
    )
    assert proposal.kind == "bill_of_lading"
    assert sorted(proposal.vins) == sorted([OURS, THEIRS]), proposal.warnings
    assert proposal.matches
    assert proposal.reference == "MEDU8812345"
    assert proposal.departed_on == date(2026, 10, 20)
    assert proposal.eta == date(2026, 11, 18)
    assert proposal.milestone == "departed"
    assert proposal.warnings == [], proposal.warnings


async def test_a_car_not_on_the_paper_does_not_match(db: None, seeded: None) -> None:
    """The same paper, another car: nothing about it may be applied."""
    proposal = await read(
        tenant_id=TENANT_A,
        data=_document(LINES),
        mime_type="image/png",
        car_vin="JTMABBBJ0RA000001",
        today=TODAY,
    )
    assert not proposal.matches
