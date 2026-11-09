"""Content: generate it, read it, change its words, approve or reject it.

Generating starts a run and returns immediately. Producing eight pieces is a
Pro planning call plus two dozen Flash calls plus thirty browser renders, and a
browser timeout must not be what decides whether a dealer's week of content
happens.

A piece the image agent finished waits at `pending_approval`. A person (marketer
and up) approves it or rejects it with a reason; scheduling it is the calendar's
(T3.8), and publishing it the worker's when the slot comes (T4.3). A person may
change its words in any language until it goes out — the edit is marked as
theirs (`edited_by_human`) and held to the same price guard as the AI's.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator

from .. import schedule
from ..core.errors import Conflict, NotFound, Unusable
from ..core.money import Money
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_role
from ..guards import price as price_guard
from ..media import compositor
from ..media.links import url_for
from ..orchestrator import planner
from ..orchestrator.executor import PlannedTask
from ..sales.clock import zone

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


class PublicationOut(BaseModel):
    """Where a piece went, one account at a time (T4.3)."""

    platform: str
    handle: str | None
    status: str
    permalink: str | None
    #: Why it did not go out here, as the platform said it.
    error: str | None
    attempts: int
    published_at: datetime | None


class ContentDetail(ContentItemOut):
    copies: list[CopyOut]
    images: list[ImageOut]
    publications: list[PublicationOut] = Field(default_factory=list)
    #: Copy fields this piece's template prints on its images. Changing one
    #: would leave the images saying the old words, so they are not editable.
    in_image: list[str]


class CopyPatch(BaseModel):
    hook: str | None = Field(default=None, max_length=300)
    caption: str | None = Field(default=None, max_length=2_200)
    cta: str | None = Field(default=None, max_length=120)
    hashtags: list[str] | None = Field(default=None, max_length=30)


class ScheduleIn(BaseModel):
    """A day and a time on the dealer's own clock: the API owns the timezone,
    so a browser in another one cannot shift a post by hours."""

    day: date
    at: time = schedule.DEFAULT_TIME

    @field_validator("at")
    @classmethod
    def _no_offset(cls, at: time) -> time:
        # "10:00+04:00" names a zone the dealer's clock already has; taking it
        # would compare an aware time with a naive one and fail as a 500.
        if at.tzinfo is not None:
            raise ValueError("a time on the dealer's clock, without an offset: 10:00")
        return at


class CalendarItem(ContentItemOut):
    local_date: date
    local_time: str


class CalendarDay(BaseModel):
    date: date
    #: Pieces going out that day, published ones included.
    count: int
    #: At the daily limit: nothing more fits.
    full: bool


class CalendarOut(BaseModel):
    timezone: str
    max_posts_per_day: int | None
    #: ["23:00", "07:00"], or none.
    quiet_hours: list[str] | None
    days: list[CalendarDay]
    items: list[CalendarItem]
    #: Days from today with nothing going out.
    gaps: list[date]
    #: Approved and waiting for a slot.
    unscheduled: list[ContentItemOut]


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


_SELECT = """
select c.id, c.kind, c.concept, c.status, c.vehicle_id, c.run_id, c.rejection_reason,
       c.scheduled_at, c.published_at, c.approved_at, c.created_at,
       coalesce(array_agg(distinct p.locale) filter (where p.locale is not null), '{}') as locales,
       count(distinct a.id)::int as assets,
       (array_agg(a.storage_path order by a.sort_order) filter (where a.id is not null))[1]
         as thumbnail,
       nullif(concat_ws(' ', v.model_year, v.make, v.model), '') as vehicle,
       c.brief ->> 'template_key' as template_key
  from content_items c
  left join content_copy p on p.content_item_id = c.id
  left join content_assets a on a.content_item_id = c.id
  left join vehicles v on v.id = c.vehicle_id
"""

_LIST = (
    _SELECT
    + """
 where c.tenant_id = $1
   and ($2::uuid is null or c.run_id = $2)
   and ($3::text is null or c.status = $3)
   and ($5::uuid is null or c.id = $5)
 group by c.id, v.id
 order by c.created_at desc
 limit $4
"""
)

#: What goes out — or went out — in a window, by when.
_GOING_OUT = (
    _SELECT
    + """
 where c.tenant_id = $1 and c.status in ('scheduled', 'publishing', 'published')
   and coalesce(c.published_at, c.scheduled_at) >= $2
   and coalesce(c.published_at, c.scheduled_at) < $3
 group by c.id, v.id
 order by coalesce(c.published_at, c.scheduled_at)
"""
)


#: A copy field → the image slot that prints it (agents/content/image.py `_slots`).
#: The hook is not here: an image's headline is the copywriter's own `headline`.
_PRINTED = {"caption": "body", "cta": "cta"}


def in_image(template_key: str | None) -> list[str]:
    """The copy fields this template prints. No template, no images to
    contradict; a template that cannot be read is assumed to print them all."""
    if not template_key:
        return []
    try:
        slots = compositor.manifest(template_key).slots
    except Exception:  # noqa: BLE001 - a missing manifest must not unlock the words
        return sorted(_PRINTED)
    return sorted(field for field, slot in _PRINTED.items() if slot in slots)


def _item(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["in_image"] = in_image(item.pop("template_key", None))
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
    publications = await conn.fetch(
        """select ch.platform, ch.handle, p.status, p.permalink, p.error, p.attempts,
                  p.published_at
             from publications p join channels ch on ch.id = p.channel_id
            where p.content_item_id = $1 order by ch.platform""",
        content_id,
    )
    item["copies"] = [dict(c) for c in copies]
    item["publications"] = [dict(p) for p in publications]
    item["images"] = [dict(i) | {"url": url_for(i["storage_path"])} for i in images]
    return item


async def _clock(conn: asyncpg.Connection, tenant_id: UUID) -> tuple[Any, schedule.Rules]:
    row = await conn.fetchrow(
        "select timezone, autonomy_rules from tenants where id = $1", tenant_id
    )
    return zone(row["timezone"]), schedule.rules_of(row["autonomy_rules"])


@router.get("/calendar", response_model=CalendarOut)
async def calendar(
    ctx: Ctx,
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
) -> dict[str, Any]:
    """The days from `from` to `to` on the dealer's clock: what goes out each
    day against the daily limit, the days from today with nothing, and the
    approved pieces still waiting for a slot. Reading it changes nothing."""
    if end < start or (end - start).days >= schedule.MAX_DAYS:
        raise Unusable(
            f"a calendar is up to {schedule.MAX_DAYS} days, from on or before to",
            ar="التقويم حتى 62 يومًا، والبداية قبل النهاية.",
        )
    async with tenant_session(ctx.tenant_id) as conn:
        tz, rules = await _clock(conn, ctx.tenant_id)
        opens = datetime.combine(start, time.min, tzinfo=tz)
        closes = datetime.combine(end, time.max, tzinfo=tz)
        rows = await conn.fetch(_GOING_OUT, ctx.tenant_id, opens, closes)
        waiting = await conn.fetch(_LIST, ctx.tenant_id, None, "approved", 200, None)
    items = []
    counts: dict[date, int] = {}
    for row in rows:
        item = _item(row)
        local = (row["published_at"] or row["scheduled_at"]).astimezone(tz)
        item |= {"local_date": local.date(), "local_time": f"{local:%H:%M}"}
        counts[local.date()] = counts.get(local.date(), 0) + 1
        items.append(item)
    span = schedule.days(start, end)
    limit = rules.max_per_day
    return {
        "timezone": str(tz),
        "max_posts_per_day": limit,
        "quiet_hours": [f"{t:%H:%M}" for t in rules.quiet] if rules.quiet else None,
        "days": [
            {
                "date": day,
                "count": counts.get(day, 0),
                "full": limit is not None and counts.get(day, 0) >= limit,
            }
            for day in span
        ],
        "items": items,
        "gaps": schedule.gaps(span, counts, today=datetime.now(tz).date()),
        "unscheduled": [_item(r) for r in waiting if r["scheduled_at"] is None],
    }


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
            """select c.status, v.price_minor, v.currency,
                      c.brief ->> 'template_key' as template_key
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
        printed = [
            field
            for field in in_image(item["template_key"])
            if field in changes and changes[field] != copy[field]
        ]
        if printed:
            raise Conflict(
                f"this piece's images print its {' and '.join(printed)}; "
                "reject it to have it made again with other words",
                ar="هذا النص مطبوع على صور المنشور؛ ارفضه ليُعاد إنشاؤه بكلمات أخرى.",
            )
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


_SAME_DAY = """
select count(*) from content_items
 where tenant_id = $1 and id <> $2 and status in ('scheduled', 'publishing', 'published')
   and (coalesce(published_at, scheduled_at) at time zone $3)::date = $4
"""


@router.post("/{content_id}/schedule", response_model=ContentDetail)
async def schedule_piece(content_id: UUID, body: ScheduleIn, ctx: Marketer) -> dict[str, Any]:
    """An approved piece into a slot — or a scheduled one into another, which is
    what dragging it on the calendar does. Held to the dealer's posting rules on
    its own clock, and refused with the rule it breaks. Nothing is sent: the
    piece goes out when the slot is due (M4)."""
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        # One scheduler per dealer at a time, or two people could each take
        # the last slot of a day.
        await conn.execute(
            "select pg_advisory_xact_lock(hashtext($1))",
            f"content-schedule:{ctx.tenant_id}",
        )
        current = await conn.fetchval(
            "select status from content_items where id = $1 for update", content_id
        )
        if current is None:
            raise NotFound("no such content", ar="لا يوجد محتوى بهذا الرقم.")
        if current not in ("approved", "scheduled"):
            raise Conflict(
                f"a piece that is {current} cannot be scheduled; approve it first",
                ar="لا يُجدول إلا المحتوى الموافق عليه.",
            )
        tz, rules = await _clock(conn, ctx.tenant_id)
        already = await conn.fetchval(_SAME_DAY, ctx.tenant_id, content_id, str(tz), body.day)
        refused = schedule.refusal(
            rules,
            day=body.day,
            at=body.at,
            already=int(already),
            now=datetime.now(tz).replace(tzinfo=None),
        )
        if refused:
            raise Conflict(refused, ar="لا يمكن الجدولة في هذا الموعد حسب قواعد النشر.")
        await conn.execute(
            "update content_items set status = 'scheduled', scheduled_at = $2 where id = $1",
            content_id,
            datetime.combine(body.day, body.at, tzinfo=tz),
        )
        return await _detail(conn, ctx.tenant_id, content_id)


@router.post("/{content_id}/unschedule", response_model=ContentDetail)
async def unschedule(content_id: UUID, ctx: Marketer) -> dict[str, Any]:
    """Off the calendar, still approved."""
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        done = await conn.fetchval(
            """update content_items set status = 'approved', scheduled_at = null
                where id = $1 and status = 'scheduled' returning id""",
            content_id,
        )
        if done is None:
            await _refuse(conn, content_id, "unscheduled")
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
