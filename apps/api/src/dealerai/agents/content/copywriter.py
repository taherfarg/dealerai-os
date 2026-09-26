"""The Copywriter: one brief, one language, one caption.

One task per locale rather than one call producing both, because a caption
written in English and then rendered into Arabic reads like a caption written
in English and then rendered into Arabic. A Gulf buyer can tell in one line.

Everything it writes about the car comes from the record it is handed. It has
no inventory tools on purpose — the Creative Director already looked the
vehicle up, and a second lookup is a second chance to describe a different car.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from ...ai.gateway import SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...core.money import Money, exponent
from ...db.session import tenant_session
from ...guards import brand as brand_guard
from ...orchestrator.gate import Action
from .. import base

log = structlog.get_logger()

MAX_HASHTAGS = 8


class Copy(BaseModel):
    hook: str = Field(max_length=90, description="The first line. It has to earn the second.")
    caption: str = Field(max_length=1400)
    cta: str = Field(max_length=90)
    hashtags: list[str] = Field(default_factory=list, max_length=MAX_HASHTAGS)
    alt_text: str = Field(
        max_length=300, description="What is in the picture, for a screen reader."
    )
    headline: str = Field(max_length=70, description="The words that go on the image itself.")
    subhead: str = Field(default="", max_length=90)


class Input(BaseModel):
    locale: str = "en"
    concept: str = "hero"
    angle: str = ""
    content_item_id: str | None = None
    template_key: str | None = None
    vehicle: dict[str, Any] = Field(default_factory=dict)


class Output(Copy):
    locale: str
    content_item_id: str | None = None


class Copywriter:
    name: ClassVar[str] = "copywriter"
    input_schema: ClassVar[type[BaseModel]] = Input
    output_schema: ClassVar[type[BaseModel]] = Output
    task_kind: ClassVar[TaskKind | None] = TaskKind.COPYWRITE
    action: ClassVar[Action | None] = None

    async def run(self, inp: Input, ctx: base.AgentContext) -> base.AgentResult:
        if not inp.vehicle:
            return base.AgentResult(
                status="failed", reason="no vehicle record reached the copywriter"
            )

        profile = await _brand(ctx.tenant_id)
        result = await complete(
            TaskKind.COPYWRITE,
            tenant_id=ctx.tenant_id,
            system=SystemLayers(
                role=load("_rules") + "\n\n" + load("copywriter"),
                tenant=_brand_layer(profile),
            ),
            messages=(
                f"## Brief\nconcept: {inp.concept}\ntemplate: {inp.template_key}\n"
                f"angle: <untrusted>{inp.angle}</untrusted>\n\n"
                f"## Language\nWrite in {inp.locale}.\n\n"
                f"## The vehicle — every fact you may state\n{_facts(inp.vehicle)}"
            ),
            output_schema=Copy,
            run_id=ctx.run_id,
            task_id=ctx.task_id,
            trace_name=f"copywriter:{inp.locale}",
        )
        if not isinstance(result.parsed, Copy):  # pragma: no cover - schema-constrained
            return base.AgentResult(status="failed", reason="the copywriter returned no copy")

        copy = result.parsed
        # The brand guard again, here, where it can still be fixed cheaply. It
        # runs once more over the finished piece in the image agent — this is
        # the early catch, not the enforcement.
        findings = brand_guard.check(
            f"{copy.hook} {copy.caption} {copy.cta}", _rules(profile, inp.locale)
        )
        if findings:
            log.info(
                "copy_has_brand_problems",
                locale=inp.locale,
                problems=[f.message for f in findings],
            )

        if inp.content_item_id:
            await _save(ctx, inp, copy)

        return base.AgentResult(
            status="ok",
            output={
                **copy.model_dump(),
                "locale": inp.locale,
                "content_item_id": inp.content_item_id,
            },
            cost_usd=result.cost_usd,
        )


def _facts(vehicle: dict[str, Any]) -> str:
    """The record, formatted, with the price spelled out once.

    Minor units are how the database stores a price and not how anyone writes
    one. Handing the model 31000000 and hoping is how a caption ends up saying
    AED 31,000,000 for a Patrol.
    """
    lines = []
    currency = vehicle.get("currency") or "AED"
    for key, value in sorted(vehicle.items()):
        if value in (None, "", [], {}) or key in ("id", "min_price_minor", "specs"):
            continue
        if key == "price_minor":
            money = Money(int(value), currency)
            major = money.amount_minor / (10 ** exponent(currency))
            lines.append(f"price: {currency} {major:,.0f} — write it exactly this way")
            continue
        lines.append(f"{key}: {value}")
    usps = (
        (vehicle.get("specs") or {}).get("usps") if isinstance(vehicle.get("specs"), dict) else None
    )
    if usps:
        points = ", ".join(u.get("text", "") for u in usps if isinstance(u, dict))
        lines.append(f"selling points already verified: {points}")
    return "\n".join(lines)


async def _brand(tenant_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(
            """select t.name, t.country, b.display_name, b.tone, b.cta_styles,
                      b.hashtag_rules, b.forbidden_terms, b.required_disclaimers, b.usps
                 from tenants t left join brand_profiles b on b.tenant_id = t.id
                where t.id = $1""",
            tenant_id,
        )
    return dict(row) if row else {}


def _rules(profile: dict[str, Any], locale: str = "en") -> brand_guard.BrandRules:
    disclaimers = profile.get("required_disclaimers") or {}
    return brand_guard.BrandRules(
        forbidden_words=tuple(profile.get("forbidden_terms") or ()),
        required_disclaimer=disclaimers.get(profile.get("country")),
        allowed_ctas=brand_guard.ctas_for(profile, locale),
        max_hashtags=int((profile.get("hashtag_rules") or {}).get("max", MAX_HASHTAGS)),
    )


def _brand_layer(profile: dict[str, Any]) -> str:
    """The tenant layer of the prompt — brand facts that change weekly.

    Sorted and free of timestamps: it sits above the request-specific context in
    the cached prefix, and anything that varies per call destroys the cache for
    every tenant.
    """
    tone = profile.get("tone") or {}
    parts = [f"You write for {profile.get('display_name') or profile.get('name')}."]
    if tone:
        parts.append("Voice: " + ", ".join(f"{k} {v}" for k, v in sorted(tone.items())))
    if profile.get("usps"):
        parts.append("What this dealership is known for: " + ", ".join(profile["usps"]))
    forbidden = profile.get("forbidden_terms") or []
    if forbidden:
        parts.append("Never use these words: " + ", ".join(sorted(forbidden)))

    # Every language's approved CTAs, not only the one being written. The guard
    # blocks a caption whose call to action is not on this list, and a model
    # that was never shown the list writes its own — which is how an entire run
    # gets rejected over a phrasing nobody told it about. Listing all of them
    # keeps this layer byte-identical across locales, so the cached prefix
    # survives.
    grouped = _ctas_by_language(profile)
    if grouped:
        parts.append(
            "Approved calls to action. Your `cta` must be one of these for the "
            "language you are writing in, copied exactly:\n"
            + "\n".join(f"  {language}: {' | '.join(texts)}" for language, texts in grouped)
        )
    return "\n".join(parts)


def _ctas_by_language(profile: dict[str, Any]) -> list[tuple[str, list[str]]]:
    grouped: dict[str, list[str]] = {}
    for entry in profile.get("cta_styles") or []:
        if isinstance(entry, str):
            grouped.setdefault("any language", []).append(entry)
        elif isinstance(entry, dict) and entry.get("text"):
            language = str(entry.get("locale") or "any language").split("-")[0]
            grouped.setdefault(language, []).append(str(entry["text"]))
    return sorted(grouped.items())


async def _save(ctx: base.AgentContext, inp: Input, copy: Copy) -> None:
    async with tenant_session(ctx.tenant_id) as conn:
        await conn.execute(
            """insert into content_copy
                 (tenant_id, content_item_id, locale, hook, caption, cta, hashtags, alt_text)
               values ($1,$2,$3,$4,$5,$6,$7,$8)
               on conflict (content_item_id, locale) do update set
                 hook = excluded.hook, caption = excluded.caption, cta = excluded.cta,
                 hashtags = excluded.hashtags, alt_text = excluded.alt_text""",
            ctx.tenant_id,
            UUID(str(inp.content_item_id)),
            inp.locale,
            copy.hook,
            copy.caption,
            copy.cta,
            copy.hashtags[:MAX_HASHTAGS],
            copy.alt_text,
        )


base.register(Copywriter())
