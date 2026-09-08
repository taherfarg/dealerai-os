"""Brand tools: what this dealership sounds like, and what it will not say.

Read-only. The brand profile is confirmed by a human during onboarding, and
nothing an agent does may edit it — a brand that drifts because an agent
adjusted it is a brand nobody can point at a decision for.
"""

from __future__ import annotations

from typing import Any

from ..db.session import tenant_session
from ..deps import TenantContext
from ..guards import brand as brand_guard
from .registry import tool

GROUP = "brand"

_PROFILE = """
select t.name, t.country, t.locales, t.currency,
       b.display_name, b.colors, b.typography, b.tone, b.cta_styles,
       b.hashtag_rules, b.forbidden_terms, b.required_disclaimers,
       b.photography_style, b.usps, b.target_markets, b.buyer_personas
  from tenants t left join brand_profiles b on b.tenant_id = t.id
 where t.id = $1
"""


def _ctas(cta_styles: Any) -> tuple[str, ...]:
    """cta_styles is a jsonb array the onboarding screen writes.

    Tolerates both shapes it can hold — bare strings, or objects with a `text`
    field — because the confirmation UI has changed once already and a guard
    that silently stops matching is worse than one that never ran.
    """
    if not isinstance(cta_styles, list):
        return ()
    out = []
    for entry in cta_styles:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("text"), str):
            out.append(entry["text"])
    return tuple(out)


@tool(name="get_brand_profile", group=GROUP)
async def get_brand_profile(ctx: TenantContext) -> dict[str, Any]:
    """This dealership's confirmed brand: voice, palette, CTAs, forbidden words.

    Everything you write must fit it. `confirmed: false` means onboarding is not
    finished — say so rather than inventing a voice.
    """
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(_PROFILE, ctx.tenant_id)
    if row is None:  # pragma: no cover - a tenant context implies a tenant
        return {"confirmed": False}

    data = dict(row)
    disclaimers = data.get("required_disclaimers") or {}
    return {
        "confirmed": data["display_name"] is not None,
        "name": data["display_name"] or data["name"],
        "country": data["country"],
        "locales": data["locales"],
        "currency": data["currency"],
        "colors": data["colors"] or {},
        "typography": data["typography"] or {},
        "tone": data["tone"] or {},
        "ctas": list(_ctas(data["cta_styles"])),
        "hashtag_rules": data["hashtag_rules"] or {},
        "forbidden_terms": list(data["forbidden_terms"] or ()),
        # Only this market's wording. Handing the model every country's
        # disclaimer invites it to pick the wrong one.
        "required_disclaimer": disclaimers.get(data["country"]),
        "photography_style": data["photography_style"],
        "usps": list(data["usps"] or ()),
        "target_markets": list(data["target_markets"] or ()),
    }


@tool(name="check_brand_rules", group=GROUP)
async def check_brand_rules(ctx: TenantContext, *, text: str) -> dict[str, Any]:
    """Check a draft against this dealership's brand rules before you finish.

    Returns the problems, each naming what to change. Calling this and fixing
    what it reports is cheaper than having the caption rejected after render.

    It does not check prices. That guard runs on its own and cannot be talked
    out of anything.
    """
    profile = await get_brand_profile(ctx)
    hashtag_rules = profile.get("hashtag_rules") or {}
    rules = brand_guard.BrandRules(
        forbidden_words=tuple(profile.get("forbidden_terms", ())),
        required_disclaimer=profile.get("required_disclaimer"),
        allowed_ctas=tuple(profile.get("ctas", ())),
        max_hashtags=int(hashtag_rules.get("max", brand_guard.MAX_HASHTAGS)),
    )
    findings = brand_guard.check(text, rules)
    return {
        "ok": not findings,
        "problems": [{"message": f.message, "detail": f.detail} for f in findings],
    }
