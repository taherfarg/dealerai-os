"""Live eval: does a real model read a dealership's brand into a usable draft?

Excluded from the default run. `npm run eval:brand`

test_brand.py proves the counting and the checks with a stubbed reading. This
answers what the stub cannot: given a logo and the colours counted in it, does
Gemini call the logo's fill the primary rather than its background — and does
it list the calls to action the captions use, in their own words and
languages, rather than better ones it would have written.

The logo is drawn here. With the design partner's real logo uploaded on the
Brand screen, the same check is the acceptance criterion's: ΔE 5 of the
colours on the sign.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from conftest import TENANT_A
from dealerai.agents.content.brand_ingest import read
from dealerai.config import get_settings
from dealerai.core import color

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

NAVY, GOLD = "#0A2540", "#C8A15A"

CAPTIONS = [
    "New arrival: 2026 Toyota Hilux Travo, 0 km, ready for export worldwide. "
    "DM to book a viewing #Dubai #Hilux",
    "BYD Seal 06 in white, Chinese specs. DM to book a viewing #BYD",
    "Shipping to Algiers this week, RoRo from Jebel Ali. Visit our showroom #Export",
    "وصلت حديثًا: تويوتا هايلكس ترافو ٢٠٢٦، صفر كيلومتر. راسلنا لحجز معاينة #دبي",
    "Nouvelle arrivée : Kia Sportage L 2026. Contactez-nous sur WhatsApp #Algérie",
]


def _logo() -> bytes:
    """A navy badge with a gold mark and a white wordmark, on white."""
    image = Image.new("RGB", (600, 300), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([20, 20, 580, 280], radius=40, fill=(10, 37, 64))
    draw.polygon([(80, 230), (150, 70), (220, 230)], fill=(200, 161, 90))
    try:
        font = ImageFont.truetype("arialbd.ttf", 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    draw.text((250, 115), "POLLUX", fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


async def test_a_logo_and_its_captions_become_a_usable_draft(db: None, seeded: None) -> None:
    draft = await read(tenant_id=TENANT_A, logo=(_logo(), "image/png"), posts=[], captions=CAPTIONS)

    primary = draft["colors"].get("primary")
    assert primary is not None, draft
    assert color.distance(primary, NAVY) < 5, f"primary {primary} is not the badge's navy"
    gold = [draft["colors"].get(r) for r in ("secondary", "accent") if draft["colors"].get(r)]
    assert any(color.distance(g, GOLD) < 5 for g in gold), f"no gold in {draft['colors']}"

    texts = {c["text"] for c in draft["cta_styles"]}
    assert "DM to book a viewing" in texts, draft["cta_styles"]
    assert {c["locale"] for c in draft["cta_styles"]} >= {"en", "ar"}, draft["cta_styles"]
    for cta in draft["cta_styles"]:
        assert any(cta["text"].casefold() in c.casefold() for c in CAPTIONS), cta
    assert draft["tone"]["voice"]
