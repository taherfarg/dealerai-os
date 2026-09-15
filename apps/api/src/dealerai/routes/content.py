"""Content generation.

One endpoint that starts a run and returns immediately. Producing eight pieces
is a Pro planning call plus two dozen Flash calls plus thirty browser renders,
and a browser timeout must not be what decides whether a dealer's week of
content happens.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_role
from ..orchestrator import planner
from ..orchestrator.executor import PlannedTask

router = APIRouter(prefix="/v1/content", tags=["content"])

MAX_PIECES = 12


class GenerateRequest(BaseModel):
    vehicle_ids: list[UUID] = Field(default_factory=list, max_length=20)
    objective: str = Field(default="sell this stock", max_length=400)
    count: int = Field(default=8, ge=1, le=MAX_PIECES)
    locales: list[str] = Field(default_factory=lambda: ["en", "ar"], max_length=4)


class GenerateAccepted(BaseModel):
    run_id: UUID
    status: str


class ContentItemOut(BaseModel):
    id: UUID
    kind: str
    concept: str | None
    status: str
    vehicle_id: UUID | None
    run_id: UUID | None
    rejection_reason: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    locales: list[str] = Field(default_factory=list)
    assets: int = 0


@router.post("/generate", response_model=GenerateAccepted, status_code=status.HTTP_202_ACCEPTED)
async def generate(
    body: GenerateRequest,
    ctx: Annotated[TenantContext, Depends(require_role("marketer"))],
) -> dict[str, Any]:
    """Plan and queue a content run.

    The run starts as a single strategist task. How many pieces a vehicle
    deserves is not knowable until something has looked at it, so the rest of
    the DAG is spawned by the strategist rather than guessed here.
    """
    async with tenant_session(ctx.tenant_id) as conn:
        autonomy = await conn.fetchval(
            "select autonomy_mode from tenants where id = $1", ctx.tenant_id
        )

    run_id = await planner.create_run(
        tenant_id=ctx.tenant_id,
        goal=body.objective,
        tasks=[
            PlannedTask(
                task_key="plan",
                agent="content_strategist",
                input={
                    "vehicle_ids": [str(v) for v in body.vehicle_ids],
                    "objective": body.objective,
                    "count": body.count,
                    "locales": body.locales,
                },
            )
        ],
        autonomy=autonomy,
        trigger_type="user",
        triggered_by=ctx.user.id,
        goal_input=body.model_dump(mode="json"),
    )
    return {"run_id": run_id, "status": "running"}


_LIST = """
select c.id, c.kind, c.concept, c.status, c.vehicle_id, c.run_id, c.rejection_reason,
       c.scheduled_at, c.published_at, c.created_at,
       coalesce(array_agg(distinct p.locale) filter (where p.locale is not null), '{}') as locales,
       count(distinct a.id)::int as assets
  from content_items c
  left join content_copy p on p.content_item_id = c.id
  left join content_assets a on a.content_item_id = c.id
 where c.tenant_id = $1
   and ($2::uuid is null or c.run_id = $2)
   and ($3::text is null or c.status = $3)
 group by c.id
 order by c.created_at desc
 limit $4
"""


@router.get("", response_model=list[ContentItemOut])
async def list_content(
    ctx: Ctx,
    run_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = Query(default=50, le=200),
) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(_LIST, ctx.tenant_id, run_id, status_filter, limit)
    return [dict(r) for r in rows]
