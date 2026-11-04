"""Live eval: does a real model read inspection photos the way the checks expect?

Excluded from the default run. `npm run eval:inspection`

test_recon.py proves the checks with a stubbed reading. This answers what the
stub cannot: that Gemini accepts the schema, numbers its findings by the photo
that shows them, and returns nothing for a photo with nothing to repair rather
than a list of guesses.

Damage *accuracy* needs real photographs of real cars, and this repo has none.
The photos are drawn here; dropping JPEGs into tests/evals/fixtures/inspections/
runs the last test on them without a code change.
"""

from __future__ import annotations

import io
import pathlib

import pytest
from PIL import Image, ImageDraw, ImageFont

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.lifecycle.recon import inspect

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "inspections"


def _png(draw_fn) -> bytes:  # type: ignore[no-untyped-def]
    img = Image.new("RGB", (900, 500), (235, 235, 235))
    draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _car_side(draw: ImageDraw.ImageDraw) -> None:
    """A plain side view: body, glass, two wheels."""
    draw.rounded_rectangle([90, 200, 810, 360], radius=40, fill=(30, 60, 120))
    draw.polygon([(250, 200), (330, 120), (590, 120), (680, 200)], fill=(30, 60, 120))
    draw.polygon([(275, 195), (340, 135), (450, 135), (450, 195)], fill=(170, 200, 230))
    draw.polygon([(470, 195), (470, 135), (580, 135), (650, 195)], fill=(170, 200, 230))
    for x in (230, 670):
        draw.ellipse([x - 65, 300, x + 65, 430], fill=(20, 20, 20))
        draw.ellipse([x - 30, 335, x + 30, 395], fill=(160, 160, 160))


def _scratched(draw: ImageDraw.ImageDraw) -> None:
    """The same car with a long scratch through the paint on the rear door,
    labelled as an inspector's photo would be."""
    _car_side(draw)
    draw.line(
        [(480, 250), (530, 262), (575, 255), (630, 272), (690, 266)], fill=(250, 250, 250), width=7
    )
    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default(size=26)
    draw.text(
        (90, 30),
        "Rear door: deep scratch through the paint, primer showing",
        fill="black",
        font=font,
    )


async def test_a_photo_with_no_car_has_nothing_to_repair(db: None, seeded: None) -> None:
    """The prompt's rule that matters most: an empty list is a correct answer."""
    image = _png(lambda d: d.rectangle([200, 120, 700, 380], fill=(200, 40, 40)))
    reading = await inspect(tenant_id=TENANT_A, photos=[(image, "image/png")])
    assert reading.findings == [], f"invented work on a red rectangle: {reading.findings}"


async def test_damage_is_found_on_the_photo_that_shows_it(db: None, seeded: None) -> None:
    clean, scratched = _png(_car_side), _png(_scratched)
    reading = await inspect(
        tenant_id=TENANT_A, photos=[(clean, "image/png"), (scratched, "image/png")]
    )
    assert reading.findings, "a labelled scratch was not found"
    assert {f.photo for f in reading.findings} == {2}, (
        f"findings point at the wrong photo: {[(f.photo, f.description) for f in reading.findings]}"
    )
    assert any(f.operation in ("paint_panel", "scratch_polish") for f in reading.findings), (
        reading.findings
    )
    assert reading.warnings == []


@pytest.mark.skipif(not FIXTURES.is_dir(), reason="no real inspection photos yet")
async def test_real_photos_are_read_without_warnings(db: None, seeded: None) -> None:
    photos = [(p.read_bytes(), "image/jpeg") for p in sorted(FIXTURES.glob("*.jpg"))[:8]]
    if not photos:
        pytest.skip("the folder is empty")
    reading = await inspect(tenant_id=TENANT_A, photos=photos)
    assert reading.warnings == [], reading.warnings
