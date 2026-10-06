"""Leads: the board's cards, and the stage moves this slice exists for."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..core.errors import Forbidden, NotFound, Unusable
from ..db.queries.crm import LEAD_TASKS, LEADS_LIST, ONE_LEAD, STAGE_HISTORY
from ..db.session import tenant_session
from ..deps import Ctx
from ..sales.scoring import from_stored, score
from ..sales.settings import SalesSettings
from ..sales.timeline import event_line
from .inbox import UserRef

router = APIRouter(prefix="/v1/leads", tags=["leads"])


class Money(BaseModel):
    amount_minor: int
    currency: str


class StageRef(BaseModel):
    id: UUID
    name: str
    category: Literal["open", "won", "lost"]


class VehicleRef(BaseModel):
    id: UUID
    label: str


class ContactRef(BaseModel):
    id: UUID
    name: str | None
    country: str | None


class LeadOut(BaseModel):
    id: UUID
    contact: ContactRef
    pipeline_id: UUID
    pipeline_name: str
    stage: StageRef
    vehicle: VehicleRef | None
    budget: Money | None
    score: int | None
    band: Literal["hot", "warm", "cold"] | None
    owner: UserRef | None
    conversation_id: UUID | None
    source: str | None
    lost_reason: str | None
    stage_entered_at: datetime
    created_at: datetime
    #: The earliest open task on this lead — the board's "next action".
    next_action_at: datetime | None


class ScoreReason(BaseModel):
    signal: str
    label: str
    points: int
    evidence_message_id: str | None


class StageMove(BaseModel):
    at: datetime
    text: str | None
    by: str | None


class LeadTask(BaseModel):
    id: UUID
    title: str
    kind: str
    due_at: datetime
    status: str
    assignee: UserRef | None


class LeadDetail(LeadOut):
    #: Recomputed from the stored signals, so the points shown are the points
    #: counted. A score the salesperson cannot check is a score they ignore.
    score_reasons: list[ScoreReason]
    history: list[StageMove]
    tasks: list[LeadTask]


class LeadCreate(BaseModel):
    contact_id: UUID
    pipeline_id: UUID | None = None
    vehicle_id: UUID | None = None
    budget: Money | None = None


class LeadPatch(BaseModel):
    stage_id: UUID | None = None
    owner_id: UUID | None = None
    vehicle_id: UUID | None = None
    budget: Money | None = None
    lost_reason: str | None = None


def lead_out(row: Mapping[str, Any]) -> dict[str, Any]:
    vehicle = None
    if row["vehicle_id"]:
        year = f" {row['model_year']}" if row["model_year"] else ""
        vehicle = {"id": row["vehicle_id"], "label": f"{row['make']} {row['model']}{year}".strip()}
    return {
        "id": row["id"],
        "contact": {
            "id": row["contact_id"],
            "name": row["contact_name"],
            "country": row["contact_country"],
        },
        "pipeline_id": row["pipeline_id"],
        "pipeline_name": row["pipeline_name"],
        "stage": {
            "id": row["stage_id"],
            "name": row["stage_name"],
            "category": row["stage_category"],
        },
        "vehicle": vehicle,
        "budget": (
            None
            if row["budget_minor"] is None
            else {"amount_minor": row["budget_minor"], "currency": row["currency"] or "AED"}
        ),
        "score": row["score"],
        "band": row["intent_band"],
        "owner": (
            None if row["owner_id"] is None else {"id": row["owner_id"], "name": row["owner_name"]}
        ),
        "conversation_id": row["conversation_id"],
        "source": row["source"],
        "lost_reason": row["lost_reason"],
        "stage_entered_at": row["stage_entered_at"],
        "created_at": row["created_at"],
        "next_action_at": row["next_action_at"],
    }


async def _row_or_404(conn: Any, lead_id: UUID) -> dict[str, Any]:
    row = await conn.fetchrow(ONE_LEAD, lead_id)
    if row is None:
        raise NotFound("no such lead")
    return dict(row)


async def _weights(conn: Any, tenant_id: UUID) -> dict[str, int]:
    raw = await conn.fetchval("select sales_settings from tenants where id = $1", tenant_id)
    return SalesSettings.model_validate(raw or {}).scoring_weights


async def _detail(conn: Any, tenant_id: UUID, lead_id: UUID) -> dict[str, Any]:
    row = await _row_or_404(conn, lead_id)
    _, _, reasons = score(from_stored(row["score_signals"]), await _weights(conn, tenant_id))
    history = await conn.fetch(STAGE_HISTORY, lead_id)
    tasks = await conn.fetch(LEAD_TASKS, lead_id)
    return {
        **lead_out(row),
        "score_reasons": reasons,
        "history": [
            {"at": move["occurs_at"], "text": move["body"], "by": move["actor_name"]}
            for move in history
        ],
        "tasks": [
            {
                "id": task["id"],
                "title": task["title"],
                "kind": task["kind"],
                "due_at": task["due_at"],
                "status": task["status"],
                "assignee": (
                    None
                    if task["assignee_id"] is None
                    else {"id": task["assignee_id"], "name": task["assignee_name"]}
                ),
            }
            for task in tasks
        ],
    }


@router.get("", response_model=list[LeadOut])
async def list_leads(
    ctx: Ctx,
    pipeline_id: UUID | None = None,
    owner_id: UUID | None = None,
    band: Annotated[Literal["hot", "warm", "cold"] | None, Query()] = None,
    q: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """The board, in board order. The whole board: a dealership's open leads fit
    in one page, and the columns count and total what they were given."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(LEADS_LIST, pipeline_id, owner_id, band, q or None, min(limit, 500))
    return [lead_out(row) for row in rows]


@router.get("/{lead_id}", response_model=LeadDetail)
async def get_lead(ctx: Ctx, lead_id: UUID) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        return await _detail(conn, ctx.tenant_id, lead_id)


@router.post("", response_model=LeadDetail, status_code=201)
async def create_lead(ctx: Ctx, body: LeadCreate) -> dict[str, Any]:
    """A lead starts where the customer already is: their owner, their team, the
    default board's first open stage."""
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        customer = await conn.fetchrow(
            """select c.id, c.owner_id, c.team_id,
                      exists (select 1 from contact_identities i
                               where i.contact_id = c.id and i.kind = 'whatsapp_user_id')
                        as on_whatsapp,
                      (select id from conversations v
                        where v.contact_id = c.id order by v.last_message_at desc nulls last
                        limit 1) as conversation_id
                 from contacts c where c.id = $1""",
            body.contact_id,
        )
        if customer is None:
            raise NotFound("no such customer")

        stage = await conn.fetchrow(
            """select s.id, s.pipeline_id from pipeline_stages s
                 join pipelines p on p.id = s.pipeline_id
                where s.category = 'open' and ($1::uuid is null or p.id = $1)
                order by p.is_default desc, p.position, s.position
                limit 1""",
            body.pipeline_id,
        )
        if stage is None:
            raise NotFound("no such pipeline")

        lead_id = await conn.fetchval(
            """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                                  owner_id, team_id, vehicle_id, budget_minor, currency, source)
               values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) returning id""",
            ctx.tenant_id,
            body.contact_id,
            customer["conversation_id"],
            stage["pipeline_id"],
            stage["id"],
            customer["owner_id"] or ctx.user.id,
            customer["team_id"],
            body.vehicle_id,
            body.budget.amount_minor if body.budget else None,
            body.budget.currency if body.budget else "AED",
            "whatsapp" if customer["on_whatsapp"] else "manual",
        )
        return await _detail(conn, ctx.tenant_id, lead_id)


@router.patch("/{lead_id}", response_model=LeadDetail)
async def edit_lead(ctx: Ctx, lead_id: UUID, body: LeadPatch) -> dict[str, Any]:
    """A stage move is three writes: the lead, its history, and a line in the
    conversation the customer is having."""
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        lead = await _row_or_404(conn, lead_id)

        if body.owner_id is not None:
            member = await conn.fetchval(
                "select app.member_role($1, $2)", ctx.tenant_id, body.owner_id
            )
            if member is None:
                raise NotFound("no such colleague in this workspace")
            await conn.execute(
                "update leads set owner_id = $2 where id = $1", lead_id, body.owner_id
            )
        if body.vehicle_id is not None:
            await conn.execute(
                "update leads set vehicle_id = $2 where id = $1", lead_id, body.vehicle_id
            )
        if body.budget is not None:
            await conn.execute(
                "update leads set budget_minor = $2, currency = $3 where id = $1",
                lead_id,
                body.budget.amount_minor,
                body.budget.currency,
            )

        if body.stage_id is not None and body.stage_id != lead["stage_id"]:
            stage = await conn.fetchrow(
                """select id, name, category from pipeline_stages
                    where id = $1 and pipeline_id = $2""",
                body.stage_id,
                lead["pipeline_id"],
            )
            if stage is None:
                raise Unusable("that stage belongs to a different pipeline")
            if stage["category"] in ("won", "lost") and not ctx.may("leads.mark_won_lost"):
                raise Forbidden(
                    "marking a lead won or lost needs leads.mark_won_lost",
                    ar="تسجيل الفرصة مكسوبة أو خاسرة يحتاج صلاحية leads.mark_won_lost.",
                )
            if stage["category"] == "lost" and not (body.lost_reason or "").strip():
                raise Unusable(
                    "a lost lead needs a reason — it is the only way to learn anything",
                    ar="الفرصة الخاسرة تحتاج سببًا — به وحده نتعلم شيئًا.",
                )

            await conn.execute(
                """update leads set stage_id = $2, stage_entered_at = now(),
                          lost_reason = case when $3 then $4 else null end
                    where id = $1""",
                lead_id,
                stage["id"],
                stage["category"] == "lost",
                (body.lost_reason or "").strip() or None,
            )
            # History lives in activities, which is already visible to whoever
            # can see the lead — one fewer table with its own policy.
            await conn.execute(
                """insert into activities (tenant_id, lead_id, contact_id, kind, body, meta,
                                           actor_type, actor_id)
                   values ($1, $2, $3, 'stage_change', $4, $5, 'user', $6)""",
                ctx.tenant_id,
                lead_id,
                lead["contact_id"],
                f"{lead['stage_name']} → {stage['name']}",
                {"from": str(lead["stage_id"]), "to": str(stage["id"])},
                str(ctx.user.id),
            )
            if lead["conversation_id"]:
                await event_line(
                    conn,
                    ctx.tenant_id,
                    lead["conversation_id"],
                    "stage_change",
                    f"Lead moved to {stage['name']}",
                    name=stage["name"],
                )

        return await _detail(conn, ctx.tenant_id, lead_id)
