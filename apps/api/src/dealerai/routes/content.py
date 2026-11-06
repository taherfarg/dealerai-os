"""Content: generate it, read it, change its words, approve or reject it.

Generating starts a run and returns immediately. Producing eight pieces is a
Pro planning call plus two dozen Flash calls plus thirty browser renders, and a
browser timeout must not be what decides whether a dealer's week of content
happens.

A piece the image agent finished waits at `pending_approval`. A person (marketer
and up) approves it or rejects it with a reason; scheduling it is the calendar's
(T3.8), publishing it M4's. A person may change its words in any language until
it goes out — the edit is marked as theirs (`edited_by_human`) and held to the
same price guard as the AI's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from ..core.errors import Conflict, NotFound, Unusable
from ..core.money import Money
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_role
from ..guards import price as price_guard
from ..media.links import url_for
from ..orchestrator import planner
from ..orchestrator.executor import PlannedTask

router = APIRouter(prefix="/v1/content", tags=["content"])

Marketer = Annotated[TenantContext, Depends(require_role("marketer"))]

MAX_PIECES = 12
#: A piece whose words a person may still change: nothing has gone out yet.
EDITABLE = ("draft", "pending_approval", "approved", "rejected")


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
    approved_at: datetime | None = None
    created_at: datetime
    locales: list[str] = Field(default_factory=list)
    assets: int = 0
    #: The first rendered image, as a signed link; none while it renders.
    thumbnail_url: str | None = None
    vehicle: str | None = None


class CopyOut(BaseModel):
    locale: str
    hook: str | None
    caption: str | None
    cta: str | None
    hashtags: list[str]
    alt_text: str | None
    edited_by_human: bool


class ImageOut(BaseModel):
    id: UUID
    aspect_ratio: str
    url: str
    locale: str | None
    width: int | None
    height: int | None


class ContentDetail(ContentItemOut):
    copies: list[CopyOut]
    images: list[ImageOut]


class CopyPatch(BaseModel):
    hook: str | None = Field(default=None, max_length=300)
    caption: str | None = Field(default=None, max_length=2_200)
    cta: str | None = Field(default=None, max_length=120)
    hashtags: list[str] | None = Field(default=None, max_length=30)


class RejectIn(BaseModel):
    #: Why — what the learning loop (M9) reads, so it is required.
    reason: str = Field(min_length=1, max_length=500)


@router.post("/generate", response_model=GenerateAccepted, status_code=status.HTTP_202_ACCEPTED)
async def generate(body: GenerateRequest, ctx: Marketer) -> dict[str, Any]:
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
       c.scheduled_at, c.published_at, c.approved_at, c.created_at,
       coalesce(array_agg(distinct p.locale) filter (where p.locale is not null), '{}') as locales,
       count(distinct a.id)::int as assets,
       (array_agg(a.storage_path order by a.sort_order) filter (where a.id is not null))[1]
         as thumbnail,
       nullif(concat_ws(' ', v.model_year, v.make, v.model), '') as vehicle
  from content_items c
  left join content_copy p on p.content_item_id = c.id
  left join content_assets a on a.content_item_id = c.id
  left join vehicles v on v.id = c.vehicle_id
 where c.tenant_id = $1
   and ($2::uuid is null or c.run_id = $2)
   and ($3::text is null or c.status = $3)
   and ($5::uuid is null or c.id = $5)
 group by c.id, v.id
 order by c.created_at desc
 limit $4
"""


def _item(row: Any) -> dict[str, Any]:
    item = dict(row)
    thumbnail = item.pop("thumbnail", None)
    item["thumbnail_url"] = url_for(thumbnail) if thumbnail else None
    return item


@router.get("", response_model=list[ContentItemOut])
async def list_content(
    ctx: Ctx,
    run_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = Query(default=50, le=200),
) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(_LIST, ctx.tenant_id, run_id, status_filter, limit, None)
    return [_item(r) for r in rows]


async def _detail(conn: asyncpg.Connection, tenant_id: UUID, content_id: UUID) -> dict[str, Any]:
    row = await conn.fetchrow(_LIST, tenant_id, None, None, 1, content_id)
    if row is None:
        raise NotFound("no such content", ar="لا يوجد محتوى بهذا الرقم.")
    item = _item(row)
    copies = await conn.fetch(
        """select locale, hook, caption, cta, hashtags, alt_text, edited_by_human
             from content_copy where content_item_id = $1 order by locale""",
        content_id,
    )
    images = await conn.fetch(
        """select id, aspect_ratio, storage_path, render_meta ->> 'locale' as locale,
                  width, height
             from content_assets where content_item_id = $1 order by sort_order""",
        content_id,
    )
    item["copies"] = [dict(c) for c in copies]
    item["images"] = [dict(i) | {"url": url_for(i["storage_path"])} for i in images]
    return item


@router.get("/{content_id}", response_model=ContentDetail)
async def get_content(content_id: UUID, ctx: Ctx) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id) as conn:
        return await _detail(conn, ctx.tenant_id, content_id)


#: Columns a person may write on a piece's copy, in the order they are bound.
_COPY_FIELDS = ("hook", "caption", "cta", "hashtags")


@router.patch("/{content_id}/copy/{locale}", response_model=ContentDetail)
async def edit_copy(
    content_id: UUID, locale: str, body: CopyPatch, ctx: Marketer
) -> dict[str, Any]:
    """A person's words for one language, marked as theirs. The price guard
    holds them to what holds the AI: a price that is not the car's is the one
    mistake a caption cannot make, whoever typed it.
    ponytail: the price guard only — the brand guard's rules are the AI's
    voice, and the person editing is the brand."""
    changes = body.model_dump(exclude_unset=True)
    if "hashtags" in changes:
        changes["hashtags"] = [
            tag.strip().lstrip("#") for tag in changes["hashtags"] or [] if tag.strip()
        ]
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        item = await conn.fetchrow(
            """select c.status, v.price_minor, v.currency
                 from content_items c left join vehicles v on v.id = c.vehicle_id
                where c.id = $1 for update of c""",
            content_id,
        )
        if item is None:
            raise NotFound("no such content", ar="لا يوجد محتوى بهذا الرقم.")
        if item["status"] not in EDITABLE:
            raise Conflict(
                f"a piece that is {item['status']} cannot be edited",
                ar="لا يمكن تعديل محتوى نُشر أو قيد النشر.",
            )
        copy = await conn.fetchrow(
            """select hook, caption, cta, hashtags from content_copy
                where content_item_id = $1 and locale = $2""",
            content_id,
            locale,
        )
        if copy is None:
            raise NotFound(f"this piece has no {locale} copy", ar="لا يوجد نص بهذه اللغة.")
        after = {field: changes.get(field, copy[field]) for field in _COPY_FIELDS}
        text = " ".join(str(after[field] or "") for field in ("hook", "caption", "cta"))
        allowed = (
            {Money(item["price_minor"], item["currency"]).major}
            if item["price_minor"] is not None
            else set()
        )
        findings = price_guard.check(text, allowed=allowed)
        if findings:
            raise Unusable(
                "; ".join(finding.message for finding in findings),
                ar="النص يذكر سعرًا غير سعر السيارة المسجّل.",
            )
        await conn.execute(
            """update content_copy
                  set hook = $3, caption = $4, cta = $5, hashtags = $6,
                      edited_by_human = true, updated_at = now()
                where content_item_id = $1 and locale = $2""",
            content_id,
            locale,
            *(after[field] for field in _COPY_FIELDS),
        )
        return await _detail(conn, ctx.tenant_id, content_id)


@router.post("/{content_id}/approve", response_model=ContentDetail)
async def approve(content_id: UUID, ctx: Marketer) -> dict[str, Any]:
    """Waiting for approval → approved, by this person, now."""
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        done = await conn.fetchval(
            """update content_items
                  set status = 'approved', approved_by = $2, approved_at = now(),
                      rejection_reason = null
                where id = $1 and status = 'pending_approval'
            returning id""",
            content_id,
            ctx.user.id,
        )
        if done is None:
            await _refuse(conn, content_id, "approved")
        return await _detail(conn, ctx.tenant_id, content_id)


@router.post("/{content_id}/reject", response_model=ContentDetail)
async def reject(content_id: UUID, body: RejectIn, ctx: Marketer) -> dict[str, Any]:
    """Not this one, and why. An approved piece can be taken back until it is
    scheduled."""
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        done = await conn.fetchval(
            """update content_items
                  set status = 'rejected', rejection_reason = $2,
                      approved_by = null, approved_at = null
                where id = $1 and status in ('pending_approval', 'approved')
            returning id""",
            content_id,
            body.reason.strip(),
        )
        if done is None:
            await _refuse(conn, content_id, "rejected")
        return await _detail(conn, ctx.tenant_id, content_id)


async def _refuse(conn: asyncpg.Connection, content_id: UUID, wanted: str) -> None:
    current = await conn.fetchval("select status from content_items where id = $1", content_id)
    if current is None:
        raise NotFound("no such content", ar="لا يوجد محتوى بهذا الرقم.")
    raise Conflict(
        f"a piece that is {current} cannot be {wanted}",
        ar="لا يمكن تغيير حالة هذا المحتوى الآن.",
    )
