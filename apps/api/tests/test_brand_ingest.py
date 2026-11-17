"""T3.1: the dealership's brand, read from its own assets and confirmed by a person.

The acceptance criterion, in its two halves: the palette lands within ΔE 5 of
the real colours — so colours are counted from pixels, and ΔE is CIEDE2000,
checked against its published reference pairs — and the profile cannot reach
the confirmed state without a human action, which Postgres enforces.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from PIL import Image, ImageDraw, ImageFilter

from conftest import MANAGER, OWNER, TENANT_A, reseed_with_people
from dealerai.agents.content import brand_ingest
from dealerai.agents.content.brand_ingest import SeenCta, counted, quoted_ctas, reading_schema
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.core import color
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.routes.brand import split_captions

NAVY, GOLD = "#0A2540", "#C8A15A"

# --------------------------------------------------------------------------
# colour, measured — pure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        # Sharma, Wu & Dalal (2005), pairs 1, 7, 13, 25 and 34.
        ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
        ((50, 0, 0), (50, -1, 2), 2.3669),
        ((50, 2.49, -0.001), (50, -2.49, 0.0009), 7.1792),
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
        ((22.7233, 20.0904, -46.694), (23.0331, 14.973, -42.5619), 2.0373),
    ],
)
def test_delta_e_is_ciede2000(first: color.Lab, second: color.Lab, expected: float) -> None:
    assert color.delta_e(first, second) == pytest.approx(expected, abs=1e-4)


def _logo(fmt: str = "PNG", *, blur: bool = False) -> bytes:
    """Navy and gold on transparency, with a white wordmark too small to be a
    brand colour."""
    image = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([10, 10, 390, 190], radius=30, fill=(10, 37, 64, 255))
    draw.ellipse([40, 40, 160, 160], fill=(200, 161, 90, 255))
    draw.text((200, 90), "POLLUX", fill=(255, 255, 255, 255))
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(1.2))
    if fmt == "JPEG":
        # A logo saved as a JPEG has no transparency: it sits on white.
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.split()[3])
        image = flat
    buf = io.BytesIO()
    image.save(buf, format=fmt, quality=70)
    return buf.getvalue()


def test_a_flat_logo_is_counted_exactly() -> None:
    swatches = color.palette(_logo())
    assert [s.hex for s in swatches] == [NAVY, GOLD], "transparency is not a colour"
    assert swatches[0].share > swatches[1].share


def test_a_blurred_jpeg_logo_stays_within_delta_e_5() -> None:
    """The acceptance bar: a logo as dealers actually send it — compressed,
    soft-edged, on white — still gives its brand colours within ΔE 5."""
    found = [s.hex for s in color.palette(_logo("JPEG", blur=True))]
    for brand in (NAVY, GOLD):
        assert min(color.distance(brand, hex_) for hex_ in found) < 5, (brand, found)


def test_photographs_do_not_outvote_the_logo() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (800, 800), (120, 160, 210)).save(buf, format="PNG")  # a sky
    pooled = color.combined([_logo(), buf.getvalue()])
    assert {s.hex for s in pooled} >= {NAVY, GOLD}


# --------------------------------------------------------------------------
# what is counted and quoted from captions — pure
# --------------------------------------------------------------------------

CAPTIONS = [
    "New arrival 🚙 2026 Hilux Travo, ready for export. DM to book a viewing #Dubai #Hilux",
    "BYD Seal 06 in white. DM to book a viewing #BYD",
    "Shipping to Algiers this week. Visit our showroom #Export",
    "وصلت حديثًا 🔥 تويوتا هايلكس ٢٠٢٦. راسلنا لحجز معاينة #دبي",
]


def test_emoji_and_hashtag_habits_are_counted() -> None:
    habits = counted(CAPTIONS)
    assert habits["emoji"] == "frequent", "two of four captions"
    assert habits["hashtag_max"] == 2
    assert counted(["No emoji here."] * 10)["emoji"] == "none"


def test_only_a_call_to_action_the_dealer_wrote_is_proposed() -> None:
    kept, warnings = quoted_ctas(
        [
            SeenCta(text="DM to book a viewing", locale="en"),
            SeenCta(text="dm to book a  viewing", locale="en"),  # the same, twice
            SeenCta(text="راسلنا لحجز معاينة", locale="en"),  # its letters are Arabic
            SeenCta(text="Call us today!", locale="en"),  # never written
        ],
        CAPTIONS,
    )
    assert kept == [
        {"text": "DM to book a viewing", "locale": "en"},
        {"text": "راسلنا لحجز معاينة", "locale": "ar"},
    ]
    assert warnings == ["'Call us today!' is not in any caption, so it is not proposed"]


def test_captions_are_split_as_they_were_pasted() -> None:
    assert split_captions("one\n\ntwo\n---\nthree\n\n\n") == ["one", "two", "three"]


def test_the_model_may_only_pick_counted_colours() -> None:
    schema = reading_schema([NAVY, GOLD])
    primary = schema.model_json_schema()["properties"]["primary"]
    assert primary["enum"] == [NAVY, GOLD]
    assert "primary" not in reading_schema([]).model_json_schema()["properties"]


# --------------------------------------------------------------------------
# the API — a draft, and a person's confirmation
# --------------------------------------------------------------------------

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


@pytest.fixture
def people(_migrated: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    asyncio.run(reseed_with_people())


@pytest.fixture
def client(people: None) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


READING: dict[str, Any] = {
    "primary": NAVY,
    "secondary": GOLD,
    "typography": {"heading_style": "sans", "heading_family": "Montserrat", "heading_weight": 800},
    "voice": "confident",
    "person": "we",
    "formality": "medium",
    "ctas": [
        {"text": "DM to book a viewing", "locale": "en"},
        {"text": "Book your test drive now", "locale": "en"},
    ],
    "photography_style": "Studio, three-quarter front, white floor.",
}


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    class Models:
        async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
            calls.append(kwargs)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model", parts=[types.Part(text=json.dumps(READING))]
                        ),
                        finish_reason=types.FinishReason.STOP,
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=2000, candidates_token_count=300, total_token_count=2300
                ),
            )

    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": Models()})()})()
    )
    return calls


def _read(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/v1/brand/read",
        files={"logo": ("logo.png", _logo(), "image/png")},
        data={"captions": "\n\n".join(CAPTIONS)},
        headers=auth(OWNER),
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_the_brand_is_the_owners(client: TestClient) -> None:
    assert client.get("/v1/brand", headers=auth(MANAGER)).status_code == 403
    brand = client.get("/v1/brand", headers=auth(OWNER)).json()
    assert brand["confirmed"] is False, "a new dealership's brand is nobody's yet"


def test_reading_writes_a_draft_and_nothing_agents_read(
    client: TestClient, model: list[Any]
) -> None:
    before = client.get("/v1/brand", headers=auth(OWNER)).json()
    brand = _read(client)
    draft = brand["draft"]
    assert draft["colors"] == {"primary": NAVY, "secondary": GOLD}
    assert [p["hex"] for p in draft["palette"]][:2] == [NAVY, GOLD]
    assert draft["cta_styles"] == [{"text": "DM to book a viewing", "locale": "en"}]
    assert "'Book your test drive now' is not in any caption" in draft["warnings"][0]
    assert draft["tone"] == {
        "voice": "confident",
        "person": "we",
        "formality": "medium",
        "emoji": "frequent",
    }
    assert draft["typography"]["heading"] == {
        "family": "Montserrat",
        "weight": 800,
        "style": "sans",
    }
    assert draft["logo_asset_id"] is not None
    assert brand["confirmed"] is False
    assert brand["colors"] == before["colors"], "what agents read is untouched"

    # The counted colours went to the model, so it chose from the pixels.
    sent = str(model[0]["contents"])
    assert NAVY in sent and GOLD in sent


def test_a_person_confirms_and_only_then_it_is_the_brand(
    client: TestClient, model: list[Any]
) -> None:
    draft = _read(client)["draft"]
    confirmed = client.post(
        "/v1/brand/confirm",
        json={
            "colors": {**draft["colors"], "accent": "#e5484d"},
            "typography": {"heading": {"family": "Montserrat", "weight": 800}},
            "tone": draft["tone"],
            "cta_styles": draft["cta_styles"] + [{"text": "راسلنا لحجز معاينة", "locale": "ar"}],
            "hashtag_rules": draft["hashtag_rules"],
            "logo_asset_id": draft["logo_asset_id"],
        },
        headers=auth(OWNER),
    )
    assert confirmed.status_code == 200, confirmed.text
    brand = confirmed.json()
    assert brand["confirmed"] is True and brand["confirmed_by"] is not None
    assert brand["colors"] == {"primary": NAVY, "secondary": GOLD, "accent": "#E5484D"}
    assert brand["draft"] is None
    assert len(brand["cta_styles"]) == 2


@pytest.mark.parametrize(
    "body",
    [
        {"colors": {"primary": "navy"}},  # not a colour
        {"colors": {"primary": NAVY}, "logo_asset_id": str(uuid.uuid4())},  # not theirs
    ],
)
def test_a_confirmation_that_makes_no_sense_is_refused(
    client: TestClient, body: dict[str, Any]
) -> None:
    assert client.post("/v1/brand/confirm", json=body, headers=auth(OWNER)).status_code in (
        400,
        422,
    )


def test_nothing_but_a_person_can_confirm_a_brand(people: None) -> None:
    """The second half of the criterion, in Postgres: a confirmed state with
    nobody's name on it is refused, whatever code tries to write it."""

    async def attempt() -> None:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            await conn.execute(
                "update brand_profiles set confirmed_at = now() where tenant_id = $1", TENANT_A
            )
        finally:
            await conn.close()

    async def ensure_row() -> None:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            await conn.execute(
                """insert into brand_profiles (tenant_id, display_name) values ($1, 'Alpha')
                   on conflict (tenant_id) do nothing""",
                TENANT_A,
            )
        finally:
            await conn.close()

    asyncio.run(ensure_row())
    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(attempt())


def test_a_brand_guide_goes_to_the_knowledge_base(client: TestClient) -> None:
    response = client.post(
        "/v1/documents",
        files={"file": ("guide.txt", b"Our voice is confident and warm.", "text/plain")},
        data={"kind": "brand_guide", "title": "Brand guide"},
        headers=auth(OWNER),
    )
    assert response.status_code == 202, response.text
    assert response.json()["kind"] == "brand_guide"


def test_reading_needs_something_to_read(client: TestClient) -> None:
    response = client.post("/v1/brand/read", data={"captions": "  "}, headers=auth(OWNER))
    assert response.status_code == 422
    assert brand_ingest.MAX_POSTS == 6
