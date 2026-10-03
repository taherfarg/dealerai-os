"""Tasks, in the buckets a working day is actually lived in."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, Field

from ..core.errors import (
    ChannelUnavailable,
    ConsentRequired,
    NotFound,
    Unusable,
    WindowClosed,
)
from ..db.queries.crm import ONE_TASK, TASKS_LIST
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..events.bus import emit
from ..sales.messaging import (
    OPTED_OUT,
    render_template,
    template_block_reason,
    window_is_open,
)
from .inbox import QueuedMessage, UserRef

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])

#: The columns a queued message comes back as, shared with the composer's
#: send so the two shapes cannot drift.
SEND_RETURNING = "id, conversation_id, type, body, status, idempotency_key, created_at"

Bucket = Literal["overdue", "today", "upcoming", "done"]


class ContactRef(BaseModel):
    id: UUID
    name: str | None


class SalesTask(BaseModel):
    id: UUID
    title: str
    kind: Literal["follow_up", "call", "meeting", "todo"]
    due_at: datetime
    status: Literal["open", "done", "cancelled"]
    completed_at: datetime | None
    #: `ai` means the copilot wrote it; the row shows a badge (S4 fills these in).
    source: Literal["human", "ai", "rule"]
    assignee: UserRef | None
    contact: ContactRef | None
    lead_id: UUID | None
    conversation_id: UUID | None
    #: {reason, text | template_id + variables} — what the AI wrote, for the
    #: follow-up card. Null on every task a person made.
    ai_draft: dict[str, Any] | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime
    kind: Literal["follow_up", "call", "meeting", "todo"] = "todo"
    assignee_id: UUID | None = None
    contact_id: UUID | None = None
    lead_id: UUID | None = None
    conversation_id: UUID | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_at: datetime | None = None
    status: Literal["open", "done", "cancelled"] | None = None
    cancel_reason: str | None = None


def task_out(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "due_at": row["due_at"],
        "status": row["status"],
        "completed_at": row["completed_at"],
        "source": row["source"],
        "assignee": (
            None
            if row["assignee_id"] is None
            else {"id": row["assignee_id"], "name": row["assignee_name"]}
        ),
        "contact": (
            None
            if row["contact_id"] is None
            else {"id": row["contact_id"], "name": row["contact_name"]}
        ),
        "lead_id": row["lead_id"],
        "conversation_id": row["conversation_id"],
        "ai_draft": row["ai_draft"],
    }


def day_start(timezone: str, now: datetime) -> datetime:
    """Midnight where the dealership is.

    Nine tonight in Dubai belongs to today for the person in Dubai, whatever the
    server's clock thinks — which is why the tenant's timezone is read rather
    than assumed. An unknown timezone falls back to UTC instead of breaking a
    screen over a settings typo.
    """
    try:
        here = now.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001 - a settings typo must not break the list
        here = now.astimezone(UTC)
    return here.replace(hour=0, minute=0, second=0, microsecond=0)


def window(bucket: Bucket, timezone: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    """The half-open range a bucket covers: overdue is everything before now,
    today is the rest of today, upcoming starts at tomorrow's midnight."""
    tomorrow = day_start(timezone, now) + timedelta(days=1)
    if bucket == "overdue":
        return None, now
    if bucket == "today":
        return now, tomorrow
    if bucket == "upcoming":
        return tomorrow, None
    return None, None  # done ignores the window


async def _row_or_404(conn: Any, task_id: UUID) -> dict[str, Any]:
    row = await conn.fetchrow(ONE_TASK, task_id)
    if row is None:
        raise NotFound("no such task")
    return dict(row)


@router.get("", response_model=list[SalesTask])
async def list_tasks(
    ctx: Ctx,
    assignee: Annotated[str, Query()] = "me",
    bucket: Bucket = "today",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """`assignee` is `me`, `team` or a person's id.

    A salesperson asking for `team` gets their own: RLS would answer with their
    own rows anyway, and a 403 on a list the switch does not even show them
    would be noise.
    """
    assignee_id: UUID | None = ctx.user.id
    if assignee == "team":
        assignee_id = None if ctx.scope != "own" else ctx.user.id
    elif assignee != "me":
        assignee_id = UUID(assignee)

    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        timezone = await conn.fetchval("select timezone from tenants where id = $1", ctx.tenant_id)
        start, end = window(bucket, timezone or "UTC", datetime.now(UTC))
        rows = await conn.fetch(
            TASKS_LIST, assignee_id, bucket == "done", start, end, min(limit, 200)
        )
    return [task_out(row) for row in rows]


@router.post("", response_model=SalesTask, status_code=201)
async def create_task(ctx: Ctx, body: TaskCreate) -> dict[str, Any]:
    """Mine unless it says otherwise. Everything it points at has to be
    something the caller can already see, or this is a way to probe for rows."""
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        for table, row_id in (
            ("contacts", body.contact_id),
            ("leads", body.lead_id),
            ("conversations", body.conversation_id),
        ):
            if row_id is not None and not await conn.fetchval(
                f"select exists (select 1 from {table} where id = $1)",  # noqa: S608
                row_id,
            ):
                raise NotFound(f"no such {table[:-1]}")
        if body.assignee_id is not None and not await conn.fetchval(
            "select app.member_role($1, $2) is not null", ctx.tenant_id, body.assignee_id
        ):
            raise NotFound("no such colleague in this workspace")

        task_id = await conn.fetchval(
            """insert into tasks (tenant_id, title, kind, due_at, assignee_id, created_by,
                                  contact_id, lead_id, conversation_id)
               values ($1, $2, $3, $4, $5, $6, $7, $8, $9) returning id""",
            ctx.tenant_id,
            body.title.strip(),
            body.kind,
            body.due_at,
            body.assignee_id or ctx.user.id,
            ctx.user.id,
            body.contact_id,
            body.lead_id,
            body.conversation_id,
        )
        return task_out(await _row_or_404(conn, task_id))


@router.patch("/{task_id}", response_model=SalesTask)
async def edit_task(ctx: Ctx, task_id: UUID, body: TaskPatch) -> dict[str, Any]:
    """Completing, snoozing and renaming are the same call.

    Completing twice changes nothing, and un-completing is an ordinary edit —
    which is what lets the Undo toast work without an endpoint of its own.
    """
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        await _row_or_404(conn, task_id)
        if body.title is not None:
            await conn.execute(
                "update tasks set title = $2 where id = $1", task_id, body.title.strip()
            )
        if body.due_at is not None:
            await conn.execute("update tasks set due_at = $2 where id = $1", task_id, body.due_at)
        if body.status is not None:
            await conn.execute(
                """update tasks set status = $2,
                          completed_at = case when $2 = 'done' then coalesce(completed_at, now())
                                              else null end,
                          cancel_reason = case when $2 = 'cancelled' then $3 else null end
                    where id = $1""",
                task_id,
                body.status,
                body.cancel_reason,
            )
        return task_out(await _row_or_404(conn, task_id))


@router.post(
    "/{task_id}/send-draft", response_model=QueuedMessage, status_code=status.HTTP_202_ACCEPTED
)
async def send_draft(
    ctx: Annotated[TenantContext, Depends(require_permission("inbox.send"))],
    task_id: UUID,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> dict[str, Any]:
    """Send the AI's follow-up and complete the task, in one tap.

    Two writes that must not half-happen: a message sent with the task left
    open gets sent a second time by a salesperson clearing their list.

    The state it was drafted against is not the state it is sent in. A
    follow-up written on Tuesday and sent on Thursday can have run out of
    window, or the customer can have opted out in between — so every rule the
    composer applies is applied again here, and the salesperson gets the same
    sentence they would have got typing it themselves.
    """
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        existing = await conn.fetchrow(
            f"select {SEND_RETURNING} from messages where tenant_id = $1 and idempotency_key = $2",  # noqa: S608
            ctx.tenant_id,
            idempotency_key,
        )
        if existing is not None:
            return dict(existing)

        task = await _row_or_404(conn, task_id)
        draft = task["ai_draft"] or {}
        if task["status"] != "open":
            raise Unusable(
                "That follow-up has already been dealt with.", ar="سبق التعامل مع هذه المتابعة."
            )
        if task["conversation_id"] is None:
            raise Unusable(
                "That follow-up has no conversation to send in.",
                ar="لا توجد محادثة تُرسل فيها هذه المتابعة.",
            )
        if not draft.get("text") and not draft.get("template_id"):
            raise Unusable(
                "That follow-up has no draft to send. Open the conversation instead.",
                ar="لا توجد مسودة تُرسل لهذه المتابعة. افتح المحادثة.",
            )

        conversation = await conn.fetchrow(
            """select c.id, c.wa_window_expires_at, ct.consent, ch.status as channel_status
                 from conversations c
                 join contacts ct on ct.id = c.contact_id
                 left join channels ch on ch.id = c.channel_id
                where c.id = $1""",
            task["conversation_id"],
        )
        if conversation is None:
            raise NotFound("no such conversation")
        if conversation["channel_status"] != "connected":
            raise ChannelUnavailable(
                "This WhatsApp number is not connected right now.",
                ar="رقم واتساب هذا غير متصل الآن.",
            )
        if (conversation["consent"] or {}).get("opted_out_at"):
            raise ConsentRequired(OPTED_OUT.en, ar=OPTED_OUT.ar)

        now = datetime.now(UTC)
        if draft.get("template_id"):
            template = await conn.fetchrow(
                "select id, name, language, category, body from message_templates where id = $1",
                UUID(str(draft["template_id"])),
            )
            if template is None:
                raise Unusable(
                    "The template this follow-up used is no longer approved.",
                    ar="القالب الذي استخدمته هذه المتابعة لم يعد معتمدًا.",
                )
            reason = template_block_reason(template["category"], conversation["consent"] or {})
            if reason:
                raise ConsentRequired(reason.en, ar=reason.ar)
            variables = [str(value) for value in (draft.get("variables") or [])]
            message_type = "template"
            text = render_template(template["body"], variables)
            template_data: dict[str, Any] | None = {
                "id": str(template["id"]),
                "name": template["name"],
                "language": template["language"],
                "category": template["category"],
                "params": {str(index + 1): value for index, value in enumerate(variables)},
            }
        else:
            if not window_is_open(conversation["wa_window_expires_at"], now):
                # Drafted Tuesday, sent Thursday.
                raise WindowClosed(
                    "More than 24 hours since the customer's last message. "
                    "Open the conversation and send an approved template.",
                    ar=(
                        "مرّ أكثر من 24 ساعة على آخر رسالة من العميل. "
                        "افتح المحادثة وأرسل قالبًا معتمدًا."
                    ),
                )
            message_type, text, template_data = "text", str(draft["text"]), None

        row = await conn.fetchrow(
            f"""insert into messages
                 (tenant_id, conversation_id, direction, sender, origin, author_user_id,
                  type, body, template, status, idempotency_key)
               values ($1, $2, 'out', 'human', 'inbox', $3, $4, $5, $6, 'queued', $7)
               returning {SEND_RETURNING}""",  # noqa: S608
            ctx.tenant_id,
            task["conversation_id"],
            ctx.user.id,
            message_type,
            text,
            template_data,
            idempotency_key,
        )
        await conn.execute(
            """update tasks set status = 'done', completed_at = now() where id = $1""", task_id
        )
        await emit(
            conn,
            "whatsapp.send_requested",
            {"message_id": str(row["id"])},
            tenant_id=ctx.tenant_id,
            dedupe_key=f"send:{row['id']}",
            priority=10,
        )
        return dict(row)
