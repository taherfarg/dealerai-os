"""Photo QA, angle detection and ranking for vehicle media.

The first thing that happens to a dealer's uploaded photos. Everything
downstream — which shot becomes the hero, which template can be used, whether a
car is publishable at all — reads what this produces, so it errs toward
rejecting rather than passing.

Nothing here invents a fact about the car. It judges the photograph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import structlog
from google.genai import types
from pydantic import BaseModel, Field

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..ai.prompts import load

log = structlog.get_logger()

#: Must match the CHECK constraint on vehicle_media.angle. A value this list
#: allows and the database does not is an insert failure at 2am.
Angle = Literal[
    "front",
    "front_three_quarter",
    "side",
    "rear_three_quarter",
    "rear",
    "interior_front",
    "interior_rear",
    "dashboard",
    "detail",
    "engine",
    "wheel",
    "unknown",
]

#: Below this, a photo is not offered to the compositor. Deliberately generous:
#: the model rejects outright for real defects, and this only filters the
#: merely-mediocre.
MIN_USABLE_SCORE = 0.35

#: What a hero shot is, best first. The front three-quarter is the automotive
#: convention for a reason — it shows length, face and stance in one frame.
#:
#: Every exterior angle is listed, including plain `rear`. Omitting one lumps it
#: in with interiors and detail shots, and a high-scoring dashboard photo then
#: beats a mediocre exterior for the hero slot — which is how a car listing ends
#: up leading with a picture of a steering wheel.
HERO_PREFERENCE: tuple[Angle, ...] = (
    "front_three_quarter",
    "front",
    "rear_three_quarter",
    "side",
    "rear",
)


class PhotoAssessment(BaseModel):
    """Schema-constrained output. The model cannot return an angle we do not
    accept, which is why `Angle` is a Literal rather than a free string."""

    angle: Angle = Field(
        description="Camera position relative to the vehicle. 'unknown' if genuinely unclear."
    )
    quality_score: float = Field(
        ge=0, le=1, description="Compositional and technical quality, 0 worst to 1 best."
    )
    rejected: bool = Field(description="True if this photo should never be published.")
    rejection_reason: str | None = Field(
        default=None, description="Short reason when rejected, else null."
    )
    shows_other_branding: bool = Field(
        default=False,
        description="True if another dealer's plate, watermark, sticker or showroom is visible.",
    )


@dataclass(frozen=True, slots=True)
class RankedPhoto:
    media_id: UUID
    assessment: PhotoAssessment
    is_hero: bool
    sort_order: int


def _system() -> SystemLayers:
    return SystemLayers(role=load("photo_qa"))


async def assess_photo(
    *,
    tenant_id: UUID,
    image: bytes,
    mime_type: str,
    run_id: UUID | None = None,
) -> PhotoAssessment:
    """Judge one photograph."""
    # A single Content, not a list of one. ContentListUnion accepts a bare
    # Content, and a list literal is inferred as list[Content] — which no arm of
    # that union accepts, because list is invariant.
    turn = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(data=image, mime_type=mime_type),
            types.Part.from_text(text="Assess this photograph of a vehicle."),
        ],
    )

    result = await complete(
        TaskKind.VISION,
        tenant_id=tenant_id,
        system=_system(),
        messages=turn,
        output_schema=PhotoAssessment,
        run_id=run_id,
        trace_name="photo_qa",
    )
    assert isinstance(result.parsed, PhotoAssessment)  # noqa: S101 - schema-constrained
    return result.parsed


def rank(assessments: dict[UUID, PhotoAssessment]) -> list[RankedPhoto]:
    """Order a vehicle's photos and pick exactly one hero.

    `is_hero` is decided here, in code, rather than asked of the model. Two
    heroes or none is a broken vehicle page, and a per-photo model call has no
    way to know what the other photos look like.
    """
    usable = {
        media_id: a
        for media_id, a in assessments.items()
        if not a.rejected and not a.shows_other_branding and a.quality_score >= MIN_USABLE_SCORE
    }

    def hero_rank(item: tuple[UUID, PhotoAssessment]) -> tuple[int, float]:
        _, a = item
        try:
            preference = HERO_PREFERENCE.index(a.angle)
        except ValueError:
            preference = len(HERO_PREFERENCE)
        # Sorted ascending: lower preference index first, higher score first.
        return (preference, -a.quality_score)

    ordered = sorted(usable.items(), key=hero_rank)

    # A vehicle with no usable photo has no hero. Promoting the least-bad
    # rejected shot would put a blurry car on Instagram, which is the outcome
    # this whole module exists to prevent.
    hero_id = ordered[0][0] if ordered else None

    ranked = [
        RankedPhoto(media_id=mid, assessment=a, is_hero=(mid == hero_id), sort_order=i)
        for i, (mid, a) in enumerate(ordered)
    ]

    # Rejected photos keep their assessment and sort last, so a human can see
    # why something was dropped instead of wondering where it went.
    rejected = [
        RankedPhoto(media_id=mid, assessment=a, is_hero=False, sort_order=len(ranked) + i)
        for i, (mid, a) in enumerate(
            sorted(
                (item for item in assessments.items() if item[0] not in usable),
                key=lambda item: -item[1].quality_score,
            )
        )
    ]
    return ranked + rejected
