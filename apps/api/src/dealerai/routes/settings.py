"""The dealership's sales settings, read by everyone, changed by the right person.

One jsonb column (tenants.sales_settings), validated whole by SalesSettings on
every write, so nothing can store a shape its readers cannot parse — and one of
those readers is an RLS policy. Which key needs which permission is the table
below (docs/sales/06-api-contract.md § 12).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.errors import Forbidden, Unusable
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..sales.settings import ArabicRegister, OpenHours, RoutingRule, SalesSettings, Weekday

router = APIRouter(prefix="/v1/settings", tags=["settings"])

AiAdmin = Annotated[TenantContext, Depends(require_permission("settings.ai"))]

#: key → the permission that may change it. A key missing here cannot be
#: written at all: scoring weights have no screen in Phase 1 and are set by
#: hand (docs/sales/04-ai-copilot.md § 5).
WRITERS: dict[str, str] = {
    "first_response_target_min": "settings.routing",
    "unassigned_visible_to_sales": "settings.routing",
    "default_team_id": "settings.routing",
    "business_hours": "settings.routing",
    "routing_rules": "settings.routing",
    "drafts_enabled": "settings.ai",
    "follow_up_cadence_days": "settings.ai",
    "arabic_register": "settings.ai",
    "retention_months": "settings.team",
}


class SalesSettingsPatch(BaseModel):
    """Absent means unchanged; null clears the default team."""

    model_config = ConfigDict(extra="forbid")

    first_response_target_min: int | None = Field(default=None, ge=1, le=24 * 60)
    unassigned_visible_to_sales: bool | None = None
    default_team_id: UUID | None = None
    business_hours: dict[Weekday, OpenHours] | None = None
    routing_rules: list[RoutingRule] | None = Field(default=None, max_length=50)
    drafts_enabled: bool | None = None
    #: At most five follow-ups, each within three months of the one before.
    follow_up_cadence_days: list[Annotated[int, Field(ge=1, le=90)]] | None = Field(
        default=None, max_length=5
    )
    arabic_register: ArabicRegister | None = None
    retention_months: int | None = Field(default=None, ge=1, le=120)


class IntentAcceptance(BaseModel):
    intent: str | None
    decided: int
    sent: int
    lightly_edited: int
    rewritten: int
    discarded: int
    #: (sent + lightly edited) / decided — docs/sales/04-ai-copilot.md § 3.
    #: Null before anything was decided.
    rate: float | None


class Acceptance(BaseModel):
    days: int
    overall: IntentAcceptance
    by_intent: list[IntentAcceptance]


ACCEPTANCE = """
select intent, sum(decided)::int as decided, sum(sent)::int as sent,
       sum(lightly_edited)::int as lightly_edited, sum(rewritten)::int as rewritten,
       sum(discarded)::int as discarded
  from v_suggestion_acceptance
 where day >= $1
 group by intent
 order by sum(decided) desc, intent nulls last
"""


def _with_rate(row: dict[str, Any]) -> dict[str, Any]:
    decided = row["decided"]
    rate = (row["sent"] + row["lightly_edited"]) / decided if decided else None
    return {**row, "rate": rate}


@router.get("/sales", response_model=SalesSettings)
async def read_sales_settings(ctx: Ctx) -> SalesSettings:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        raw = await conn.fetchval("select sales_settings from tenants where id = $1", ctx.tenant_id)
    return SalesSettings.model_validate(raw or {})


@router.patch("/sales", response_model=SalesSettings)
async def change_sales_settings(ctx: Ctx, patch: SalesSettingsPatch) -> SalesSettings:
    changes = patch.model_dump(exclude_unset=True, mode="json")
    refused = sorted({WRITERS[key] for key in changes if not ctx.may(WRITERS[key])})
    if refused:
        raise Forbidden(
            f"changing these settings requires {' and '.join(refused)}",
            ar=f"تغيير هذه الإعدادات يحتاج صلاحية {' و'.join(refused)}.",
        )
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        raw = dict(
            await conn.fetchval(
                "select sales_settings from tenants where id = $1 for update", ctx.tenant_id
            )
            or {}
        )
        current = SalesSettings.model_validate(raw).model_dump(mode="json")
        try:
            merged = SalesSettings.model_validate({**current, **changes})
        except ValidationError as exc:
            raise Unusable(
                str(exc.errors()[0]["msg"]),
                ar="هذه الإعدادات غير صالحة. راجع ساعات العمل وقواعد التوزيع.",
            ) from exc
        teams = {merged.default_team_id, *(rule.team_id for rule in merged.routing_rules)} - {None}
        if teams:
            known = await conn.fetchval(
                "select count(*) from teams where id = any($1::uuid[])", list(teams)
            )
            if known != len(teams):
                raise Unusable(
                    "routing names a team that does not exist",
                    ar="يشير التوزيع إلى فريق غير موجود.",
                )
        # Onto the raw column, so a key a newer deploy wrote survives an older one's save.
        await conn.execute(
            "update tenants set sales_settings = $2::jsonb where id = $1",
            ctx.tenant_id,
            {**raw, **merged.model_dump(mode="json")},
        )
    return merged


@router.get("/ai/acceptance", response_model=Acceptance)
async def acceptance(
    ctx: AiAdmin, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> dict[str, Any]:
    """How the drafts fared, by intent — the number the pilot's S5 criterion
    and the autopilot trigger are both read from."""
    since = (datetime.now(UTC) - timedelta(days=days)).date()
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = [dict(row) for row in await conn.fetch(ACCEPTANCE, since)]
    keys = ("decided", "sent", "lightly_edited", "rewritten", "discarded")
    overall = {"intent": None, **{key: sum(row[key] for row in rows) for key in keys}}
    return {
        "days": days,
        "overall": _with_rate(overall),
        "by_intent": [_with_rate(row) for row in rows],
    }
