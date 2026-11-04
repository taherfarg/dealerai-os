"""Live eval: does a real model read a transfer receipt well enough to record?

Excluded from the default run. `npm run eval:receipt`

test_deals.py proves the checks with a stubbed reading. This answers what the
stub cannot: whether Gemini, given a SWIFT copy of the kind a buyer in Algiers
sends on WhatsApp, reads the instructed amount as printed — not a charge — and
supplies no exchange rate the paper does not print.

The receipt is drawn here: a real one names a real payer and a real account.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from PIL import Image, ImageDraw, ImageFont

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.lifecycle.deals import read_receipt

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

LINES = [
    "BANQUE NATIONALE D'ALGERIE          SWIFT MT103 - CUSTOMER TRANSFER",
    ":20:  Reference  BNA26110400451",
    ":32A: 261104USD5450,00",
    ":33B: USD5450,00",
    ":50K: SARL ATLAS AUTO, ALGER",
    ":59:  POLLUX MOTORS FZE, DUBAI",
    ":70:  DEPOSIT TOYOTA HILUX TRAVO STOCK 6041",
    ":71A: OUR",
    ":71F: USD25,00",
]


def _receipt() -> bytes:
    try:
        font = ImageFont.truetype("cour.ttf", 22)
    except OSError:
        font = ImageFont.load_default(size=22)
    img = Image.new("RGB", (1100, 60 + 36 * len(LINES)), "white")
    draw = ImageDraw.Draw(img)
    for i, text in enumerate(LINES):
        draw.text((40, 30 + 36 * i), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_a_swift_copy_is_read_at_its_instructed_amount(db: None, seeded: None) -> None:
    proposal = await read_receipt(tenant_id=TENANT_A, data=_receipt(), mime_type="image/png")
    assert proposal.currency == "USD"
    assert proposal.amount_minor == 545_000, (proposal.amount_minor, proposal.warnings)
    assert proposal.paid_on == date(2026, 11, 4)
    assert proposal.fx_rate is None, "no rate printed, none supplied"
    assert proposal.warnings == [], proposal.warnings
