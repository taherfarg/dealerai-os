"""Live eval: the image path and the rejection rule.

Excluded from the default run. `npm run eval:vision`

Angle *accuracy* is not tested here — that needs real dealer photographs with
known angles, and this repo has none. The harness reads any JPEGs placed in
tests/evals/fixtures/photos/<angle>/, so dropping Pollux's catalogue in there
turns the accuracy check on without a code change. Until then this proves the
two things that can be proven: bytes reach the model as an image, and the
rejection rule is actually followed rather than merely written down.
"""

from __future__ import annotations

import io
import pathlib

import pytest
from PIL import Image, ImageDraw

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.media.vision import assess_photo

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "photos"


def _png(draw_fn) -> bytes:  # type: ignore[no-untyped-def]
    img = Image.new("RGB", (640, 480), (240, 240, 240))
    draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_a_non_vehicle_image_is_rejected(db: None, seeded: None) -> None:
    """Proves three things at once: the bytes arrive as an image, the response
    parses into the schema, and the model applies 'not a vehicle' rather than
    guessing an angle to fill the field."""
    image = _png(lambda d: d.rectangle([120, 120, 520, 360], fill=(200, 40, 40)))

    result = await assess_photo(tenant_id=TENANT_A, image=image, mime_type="image/png")

    assert result.rejected is True, f"a red rectangle was not rejected: {result}"
    assert result.rejection_reason
    assert result.angle == "unknown", (
        f"guessed angle {result.angle!r} for a shape with no vehicle in it — the "
        "prompt's 'choose unknown rather than guessing' rule is not landing"
    )


async def test_a_blank_frame_is_rejected(db: None, seeded: None) -> None:
    result = await assess_photo(
        tenant_id=TENANT_A, image=_png(lambda d: None), mime_type="image/png"
    )
    assert result.rejected is True
    assert result.quality_score < 0.5


@pytest.mark.skipif(not FIXTURES.is_dir(), reason="no labelled photo fixtures yet")
async def test_angle_accuracy_on_real_photographs(db: None, seeded: None) -> None:
    """Drop real photos into tests/evals/fixtures/photos/<angle>/ to enable.

    The plan's acceptance bar is 85% on 40 labelled photos.
    """
    cases = [(p, p.parent.name) for p in FIXTURES.rglob("*.jpg")]
    if len(cases) < 10:
        pytest.skip(f"only {len(cases)} fixtures; need a meaningful sample")

    correct = 0
    for path, expected in cases:
        result = await assess_photo(
            tenant_id=TENANT_A, image=path.read_bytes(), mime_type="image/jpeg"
        )
        correct += result.angle == expected

    accuracy = correct / len(cases)
    assert accuracy >= 0.85, f"angle accuracy {accuracy:.0%} over {len(cases)} photos"
