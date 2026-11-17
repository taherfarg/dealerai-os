"""Reading a dealership's brand from its own logo, posts and captions — into a
draft a person confirms. docs/09 § T3.1.

What is counted, and what is asked:

* **The palette is counted.** Colours come from the pixels (core/color.py),
  exact to the hex. The model only says which of the counted colours is the
  primary, the secondary, the accent — and its schema offers nothing else, so
  it cannot hand back a plausible #0A2540 that is not on the sign.
* **Emoji and hashtag habits are counted** from the captions.
* **Calls to action are quoted.** The model lists the ones the dealer already
  uses; a call to action that does not appear in a caption is not proposed.
  These become the only CTAs the copywriter may write (copywriter.copy_schema),
  so one the dealer never said must not slip in here.
* **The voice and the typefaces are judged** — by the model, from the
  captions and the images. They are the part a person is most likely to
  change, and the screen says so.

Nothing here writes the profile agents read. The result is a draft; only a
person confirming it moves it there (routes/brand.py).

Not a registered agent: brand ingestion is onboarding, done when a person
asks for it, and a Director that could plan it could re-brand a dealership.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal
from uuid import UUID

import structlog
from google.genai import types
from pydantic import BaseModel, Field, create_model

from ...ai.gateway import SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...core import color

log = structlog.get_logger()

MAX_POSTS = 6
MAX_CAPTIONS = 40
#: The brand guard's own ceiling; a habit above it is not adopted.
MAX_HASHTAGS = 8

Locale = Literal["en", "ar", "fr"]

_EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff⭐❤]")
_ARABIC = re.compile("[؀-ۿ]")
_HASHTAG = re.compile(r"#[\w؀-ۿ]+")


class Fonts(BaseModel):
    heading_style: Literal["sans", "serif", "display", "script", "mono"]
    heading_family: str | None = Field(
        default=None, max_length=60, description="The closest Google Fonts family, if any."
    )
    heading_weight: int = Field(default=700, description="100 to 900.")
    body_family: str | None = Field(default=None, max_length=60)
    arabic_family: str | None = Field(
        default=None, max_length=60, description="Only if Arabic lettering is visible."
    )


class SeenCta(BaseModel):
    text: str = Field(max_length=90, description="Copied exactly from a caption.")
    locale: Locale


def reading_schema(candidates: list[str]) -> type[BaseModel]:
    """What the model may answer. Colour roles are fields only when there are
    counted colours to choose from, and then only those colours."""
    fields: dict[str, Any] = {
        "typography": (Fonts | None, None),
        "voice": (
            Literal["confident", "warm", "playful", "premium", "straightforward", "technical"],
            ...,
        ),
        "person": (Literal["we", "I", "brand_name"], ...),
        "formality": (Literal["low", "medium", "high"], ...),
        "ctas": (list[SeenCta], Field(default_factory=list)),
        "photography_style": (str | None, Field(default=None, max_length=200)),
    }
    if candidates:
        choice: Any = Literal[tuple(candidates)]
        fields["primary"] = (choice, ...)
        for role in ("secondary", "accent", "bg", "text"):
            fields[role] = (choice | None, None)
    model: type[BaseModel] = create_model("BrandReading", **fields)
    return model


# --------------------------------------------------------------------------
# what is counted — pure
# --------------------------------------------------------------------------


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def counted(captions: list[str]) -> dict[str, Any]:
    """Emoji and hashtag habits, from the captions themselves."""
    if not captions:
        return {}
    with_emoji = sum(1 for c in captions if _EMOJI.search(c)) / len(captions)
    emoji = "none" if with_emoji < 0.1 else "sparse" if with_emoji < 0.5 else "frequent"
    tags = sorted(len(_HASHTAG.findall(c)) for c in captions)
    # The 90th percentile: what the dealer usually does, not its one outlier.
    usual = tags[min(len(tags) - 1, math.ceil(0.9 * len(tags)) - 1)]
    return {"emoji": emoji, "hashtag_max": min(max(usual, 0), MAX_HASHTAGS)}


def quoted_ctas(ctas: list[SeenCta], captions: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """Keep the calls to action a caption actually contains, once each, with
    the language its letters say rather than the one the model guessed."""
    haystack = [_plain(c) for c in captions]
    kept: list[dict[str, str]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for cta in ctas:
        text = cta.text.strip()
        key = _plain(text)
        if not key or key in seen:
            continue
        if not any(key in caption for caption in haystack):
            warnings.append(f"{text!r} is not in any caption, so it is not proposed")
            continue
        seen.add(key)
        locale = "ar" if _ARABIC.search(text) else cta.locale
        kept.append({"text": text, "locale": locale})
    return kept, warnings


# --------------------------------------------------------------------------
# the reading
# --------------------------------------------------------------------------


async def read(
    *,
    tenant_id: UUID,
    logo: tuple[bytes, str] | None,
    posts: list[tuple[bytes, str]],
    captions: list[str],
) -> dict[str, Any]:
    """Read the dealer's assets into a draft profile. One vision call."""
    captions = [c.strip() for c in captions if c.strip()][:MAX_CAPTIONS]
    posts = posts[:MAX_POSTS]
    warnings: list[str] = []

    # The logo is the palette's authority; posts add what the logo lacks,
    # weighted as one voice between them, never outvoting it.
    logo_palette = color.palette(logo[0]) if logo else []
    post_palette = color.combined([data for data, _ in posts]) if posts else []
    swatches: list[color.Swatch] = list(logo_palette)
    for swatch in post_palette:
        if all(color.distance(swatch.hex, s.hex) >= color.SAME for s in swatches):
            swatches.append(swatch)
    candidates = [s.hex for s in swatches[:12]]
    if not logo:
        warnings.append("no logo was given: the colours come from the posts alone")

    parts: list[types.Part] = []
    if logo:
        parts += [
            types.Part.from_text(text="The logo:"),
            types.Part.from_bytes(data=logo[0], mime_type=logo[1]),
        ]
    for number, (data, mime) in enumerate(posts, start=1):
        parts += [
            types.Part.from_text(text=f"Past post {number}:"),
            types.Part.from_bytes(data=data, mime_type=mime),
        ]
    if candidates:
        parts.append(
            types.Part.from_text(
                text="Colours counted in these images, most used first: "
                + ", ".join(f"{s.hex} ({s.share:.0%})" for s in swatches[:12])
            )
        )
    if captions:
        parts.append(
            types.Part.from_text(
                text="Past captions, as the dealer posted them:\n<untrusted>\n"
                + "\n---\n".join(captions)
                + "\n</untrusted>"
            )
        )
    parts.append(types.Part.from_text(text="Read this dealership's brand."))

    schema = reading_schema(candidates)
    result = await complete(
        TaskKind.VISION,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("brand_ingest")),
        messages=types.Content(role="user", parts=parts),
        output_schema=schema,
        trace_name="brand_ingest",
    )
    reading = result.parsed
    assert isinstance(reading, schema)  # noqa: S101 - schema-constrained
    answer = reading.model_dump()

    ctas, cta_warnings = quoted_ctas(
        [SeenCta.model_validate(c) for c in answer.get("ctas") or []], captions
    )
    warnings += cta_warnings
    habits = counted(captions)
    fonts = answer.get("typography") or {}
    typography: dict[str, Any] = {}
    if fonts.get("heading_family"):
        typography["heading"] = {
            "family": fonts["heading_family"],
            "weight": min(max(int(fonts.get("heading_weight") or 700), 100), 900),
            "style": fonts.get("heading_style"),
        }
    if fonts.get("body_family"):
        typography["body"] = {"family": fonts["body_family"]}
    if fonts.get("arabic_family"):
        typography["arabic"] = {"family": fonts["arabic_family"]}

    draft = {
        "colors": {
            role: answer.get(role)
            for role in ("primary", "secondary", "accent", "bg", "text")
            if answer.get(role)
        },
        "palette": [{"hex": s.hex, "share": s.share} for s in swatches[:12]],
        "typography": typography,
        "tone": {
            "voice": answer.get("voice"),
            "person": answer.get("person"),
            "formality": answer.get("formality"),
            **({"emoji": habits["emoji"]} if habits else {}),
        },
        "cta_styles": ctas,
        "hashtag_rules": {"max": habits["hashtag_max"]} if habits else {},
        "photography_style": answer.get("photography_style"),
        "sources": {"logo": logo is not None, "posts": len(posts), "captions": len(captions)},
        "warnings": warnings,
    }
    log.info(
        "brand_read",
        colours=len(candidates),
        ctas=len(ctas),
        captions=len(captions),
        cost_usd=round(result.cost_usd, 6),
    )
    return draft
