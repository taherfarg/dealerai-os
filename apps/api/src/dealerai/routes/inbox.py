"""The sales inbox: the queue, a conversation, and what you can do to it."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, Field, model_validator

from ..core.errors import (
    ChannelUnavailable,
    ConsentRequired,
    Forbidden,
    NotFound,
    Unusable,
    WindowClosed,
)
from ..db.queries.inbox import (
    COUNTS,
    MESSAGE,
    THREAD,
    VIEW_SQL,
    VIEWS_BY_SCOPE,
    View,
    list_sql,
    one_sql,
)
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..events.bus import emit
from ..media.links import url_for as media_url
from ..sales.messaging import (
    render_template,
    template_block_reason,
    variable_numbers,
    window_is_open,
)
from ..sales.timeline import event_line

router = APIRouter(prefix="/v1/conversations", tags=["inbox"])
#: Retrying a send names the message, not the conversation it sits in.
messages_router = APIRouter(prefix="/v1/messages", tags=["inbox"])

#: How close to the target counts as "about to be late" — the same two minutes
#: the due-soon notification uses, so the amber row and the ping agree.
DUE_SOON = timedelta(minutes=2)

#: What a row shows instead of text, when what arrived was not text.
_PREVIEWS = {
    "image": "Photo",
    "audio": "Voice note",
    "video": "Video",
    "document": "Document",
    "location": "Location",
    "sticker": "Sticker",
    "template": "Template",
    "unsupported": "Message",
}

_FOREVER = datetime.max.replace(tzinfo=UTC)
_NEVER = datetime.min.replace(tzinfo=UTC)


class UserRef(BaseModel):
    id: UUID
    name: str | None
    avatar_url: str | None = None


class ContactSummary(BaseModel):
    id: UUID
    name: str | None
    country: str | None
    language: str | None
    tags: list[str]
    owner: UserRef | None
    last_seen_at: datetime | None


class LastMessage(BaseModel):
    preview: str
    type: str
    direction: Literal["in", "out"]
    origin: str
    at: datetime


class ChannelRef(BaseModel):
    id: UUID
    platform: str
    name: str | None


class TeamRef(BaseModel):
    id: UUID
    name: str | None


class ConversationSummary(BaseModel):
    id: UUID
    channel: ChannelRef | None
    contact: ContactSummary
    status: str
    assignee: UserRef | None
    team: TeamRef | None
    last_message: LastMessage | None
    unread_count: int
    waiting_since: datetime | None
    sla_due_at: datetime | None
    sla_state: Literal["ok", "due_soon", "breached"] | None
    window_expires_at: datetime | None
    #: Always false in S2; the copilot arrives in S4 and this is what the row reads.
    has_ai_draft: bool = False


class ConversationPage(BaseModel):
    data: list[ConversationSummary]
    next_cursor: str | None


def _sla_state(
    waiting_since: datetime | None, due_at: datetime | None, now: datetime
) -> str | None:
    if waiting_since is None or due_at is None:
        return None
    if now >= due_at:
        return "breached"
    return "due_soon" if due_at - now <= DUE_SOON else "ok"


def _preview(row: Mapping[str, Any]) -> str:
    """What the row shows: the words, or what kind of thing arrived."""
    transcript = (row["transcript"] or {}).get("text") if row["transcript"] else None
    text = row["body"] or transcript
    if text:
        return str(text)[:160]
    return _PREVIEWS.get(str(row["last_type"]), "Message")


def summary(row: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """One database row as the inbox draws it.

    The list and the thread both go through here, so a conversation cannot look
    like two different things on two screens.
    """
    return {
        "id": row["id"],
        "channel": (
            {"id": row["channel_id"], "platform": row["platform"], "name": row["channel_name"]}
            if row["channel_id"]
            else None
        ),
        "contact": {
            "id": row["contact_id"],
            "name": row["full_name"],
            "country": row["country"],
            "language": row["locale"],
            "tags": list(row["tags"] or []),
            "owner": (
                {"id": row["contact_owner_id"], "name": row["contact_owner_name"]}
                if row["contact_owner_id"]
                else None
            ),
            "last_seen_at": row["last_seen_at"],
        },
        "status": row["status"],
        "assignee": (
            {
                "id": row["assigned_to"],
                "name": row["assignee_name"],
                "avatar_url": row["assignee_avatar"],
            }
            if row["assigned_to"]
            else None
        ),
        "team": {"id": row["team_id"], "name": row["team_name"]} if row["team_id"] else None,
        "last_message": (
            {
                "preview": _preview(row),
                "type": row["last_type"],
                "direction": row["direction"],
                "origin": row["origin"],
                "at": row["last_at"],
            }
            if row["last_at"]
            else None
        ),
        "unread_count": row["unread_count"],
        "waiting_since": row["waiting_since"],
        "sla_due_at": row["sla_due_at"],
        "sla_state": _sla_state(row["waiting_since"], row["sla_due_at"], now),
        "window_expires_at": row["wa_window_expires_at"],
        "has_ai_draft": False,
    }


def encode_cursor(row: Mapping[str, Any]) -> str:
    """Three sort keys, base64'd so nobody is tempted to build one by hand."""
    waiting = row["waiting_since"] or _FOREVER
    last = row["last_message_at"] or _NEVER
    raw = f"{waiting.isoformat()}|{last.isoformat()}|{row['id']}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, datetime, UUID]:
    try:
        waiting, last, conversation_id = base64.urlsafe_b64decode(cursor).decode().split("|")
        return datetime.fromisoformat(waiting), datetime.fromisoformat(last), UUID(conversation_id)
    except (ValueError, binascii.Error) as exc:
        raise Unusable("that cursor is not one of ours") from exc


@router.get("", response_model=ConversationPage)
async def list_conversations(
    ctx: Ctx,
    view: View = "mine",
    status_filter: Annotated[str, Query(alias="status")] = "open",
    q: str = "",
    channel_id: str = "",
    cursor: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    if view not in VIEWS_BY_SCOPE[ctx.scope]:
        raise Forbidden(f"the {view} view needs a manager")
    keys = decode_cursor(cursor) if cursor else None
    size = min(limit, 100)

    arguments: list[Any] = [ctx.user.id, status_filter, q, channel_id]
    if keys is not None:
        arguments.extend(keys)
    # One more than asked, to know whether there is another page.
    arguments.append(size + 1)

    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(list_sql(view, with_cursor=keys is not None), *arguments)

    page, has_more = rows[:size], len(rows) > size
    now = datetime.now(UTC)
    return {
        "data": [summary(row, now) for row in page],
        "next_cursor": encode_cursor(page[-1]) if has_more and page else None,
    }


class Attachment(BaseModel):
    url: str
    mime: str
    filename: str | None = None
    size_bytes: int | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    kind: Literal["message", "note", "event"]
    type: str
    direction: Literal["in", "out"]
    origin: str
    author: UserRef | None
    text: str | None
    attachment: Attachment | None
    transcript: dict[str, Any] | None
    location: dict[str, Any] | None
    template: dict[str, Any] | None
    reply_to: dict[str, Any] | None
    reactions: list[dict[str, Any]]
    #: Outbound only: the ticks belong to messages we sent.
    status: str | None
    error: dict[str, Any] | None
    event: dict[str, Any] | None
    referral: dict[str, Any] | None
    created_at: datetime


class MessagePage(BaseModel):
    data: list[MessageOut]
    next_cursor: str | None


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class AssignIn(BaseModel):
    user_id: UUID | None


class StatusIn(BaseModel):
    status: Literal["open", "closed", "spam"]


def _attachment(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The first stored asset, as a link the browser can load.

    Media that is still downloading, or that failed, has no link: the thread
    shows a placeholder rather than a broken image.
    """
    assets = list(row["media"] or [])
    asset = assets[0] if assets else None
    if not asset or asset.get("status") != "ready" or not asset.get("storage_path"):
        return None
    return {
        "url": media_url(str(asset["storage_path"])),
        "mime": str(asset.get("mime") or "application/octet-stream"),
        "filename": asset.get("filename"),
        "size_bytes": asset.get("size"),
        "duration_s": asset.get("duration_s"),
        "width": asset.get("width"),
        "height": asset.get("height"),
    }


def message_out(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "kind": row["kind"],
        "type": row["type"],
        "direction": row["direction"],
        "origin": row["origin"],
        "author": (
            {
                "id": row["author_user_id"],
                "name": row["author_name"],
                "avatar_url": row["author_avatar"],
            }
            if row["author_user_id"]
            else None
        ),
        "text": row["body"],
        "attachment": _attachment(row),
        "transcript": row["transcript"],
        "location": row["location"],
        "template": row["template"],
        "reply_to": (
            {
                "id": row["reply_to_id"],
                "preview": row["reply_body"]
                or (
                    (row["reply_transcript"] or {}).get("text") if row["reply_transcript"] else None
                )
                or _PREVIEWS.get(str(row["reply_type"]), "Message"),
            }
            if row["reply_to_id"]
            else None
        ),
        "reactions": list(row["reactions"] or []),
        # Inbound messages and notes have no delivery state to show.
        "status": row["status"] if row["direction"] == "out" and row["kind"] == "message" else None,
        "error": row["error"],
        "event": row["event"],
        "referral": row["referral"],
        "created_at": row["created_at"],
    }


def _encode_message_cursor(row: Mapping[str, Any]) -> str:
    raw = f"{row['created_at'].isoformat()}|{row['id']}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_message_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        created_at, message_id = base64.urlsafe_b64decode(cursor).decode().split("|")
        return datetime.fromisoformat(created_at), UUID(message_id)
    except (ValueError, binascii.Error) as exc:
        raise Unusable("that cursor is not one of ours") from exc


async def _summary_of(conn: Any, user_id: UUID, conversation_id: UUID) -> dict[str, Any]:
    """The conversation as the list draws it, or 404 — which is also the answer
    for another tenant's id and for a colleague's conversation."""
    row = await conn.fetchrow(one_sql(), user_id, conversation_id)
    if row is None:
        raise NotFound("no such conversation")
    return summary(row, datetime.now(UTC))


@router.get("/counts")
async def conversation_counts(ctx: Ctx) -> dict[str, dict[str, int]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        counts: dict[str, dict[str, int]] = {}
        for view in VIEWS_BY_SCOPE[ctx.scope]:
            row = await conn.fetchrow(COUNTS.format(view=VIEW_SQL[view]), ctx.user.id)
            counts[view] = {"waiting": row["waiting"], "unread": int(row["unread"])}
    return counts


class SendMessageIn(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=4096)
    template_id: UUID | None = None
    variables: list[str] = Field(default_factory=list, max_length=20)
    reply_to_id: UUID | None = None

    @model_validator(mode="after")
    def exactly_one_kind(self) -> SendMessageIn:
        if (self.text is None) == (self.template_id is None):
            raise ValueError("provide exactly one of text or template_id")
        return self


class QueuedMessage(BaseModel):
    id: UUID
    conversation_id: UUID
    type: str
    body: str | None
    status: str
    idempotency_key: str
    created_at: datetime


_RETURNING = "id, conversation_id, type, body, status, idempotency_key, created_at"


@router.post(
    "/{conversation_id}/messages",
    response_model=QueuedMessage,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    conversation_id: UUID,
    body: SendMessageIn,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    ctx: Annotated[TenantContext, Depends(require_permission("inbox.send"))],
) -> QueuedMessage:
    """Persist the send intent before the worker calls Meta."""
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        existing = await conn.fetchrow(
            f"select {_RETURNING} from messages where tenant_id=$1 and idempotency_key=$2",  # noqa: S608
            ctx.tenant_id,
            idempotency_key,
        )
        if existing is not None:
            return QueuedMessage.model_validate(dict(existing))

        conversation = await conn.fetchrow(
            """select c.id, c.contact_id, c.wa_window_expires_at, c.channel_id,
                      ct.consent, ch.status as channel_status
               from conversations c
               join contacts ct on ct.id=c.contact_id
               join channels ch on ch.id=c.channel_id and ch.platform='whatsapp'
               where c.id=$1""",
            conversation_id,
        )
        if conversation is None:
            raise NotFound("no such WhatsApp conversation")
        if conversation["channel_status"] != "connected":
            raise ChannelUnavailable("This WhatsApp number is not connected right now.")

        consent = dict(conversation["consent"] or {})
        message_type = "text"
        text = body.text
        template_data: dict[str, Any] | None = None
        if body.template_id is None:
            if consent.get("opted_out_at"):
                raise ConsentRequired("The customer asked not to be messaged.")
            if not window_is_open(conversation["wa_window_expires_at"], datetime.now(UTC)):
                raise WindowClosed(
                    "More than 24 hours since the customer's last message. "
                    "Send an approved template."
                )
        else:
            template = await conn.fetchrow(
                """select id, name, language, category, status, body
                   from message_templates where id=$1 and channel_id=$2""",
                body.template_id,
                conversation["channel_id"],
            )
            if template is None:
                raise NotFound("no such message template")
            if template["status"] != "approved":
                raise Unusable("This template is not approved by WhatsApp.")
            reason = template_block_reason(template["category"], consent)
            if reason:
                raise ConsentRequired(reason)
            required = variable_numbers(template["body"])
            if required and (required != list(range(1, len(body.variables) + 1))):
                raise Unusable(f"this template needs {max(required)} variables")
            if not required and body.variables:
                raise Unusable("this template has no variables")
            message_type = "template"
            text = render_template(template["body"], body.variables)
            template_data = {
                "id": str(template["id"]),
                "name": template["name"],
                "language": template["language"],
                "category": template["category"],
                "params": {str(i + 1): value for i, value in enumerate(body.variables)},
            }

        row = await conn.fetchrow(
            f"""insert into messages
                 (tenant_id, conversation_id, direction, sender, origin, author_user_id,
                  type, body, template, reply_to_id, status, idempotency_key)
               values ($1, $2, 'out', 'human', 'inbox', $3, $4, $5, $6, $7, 'queued', $8)
               returning {_RETURNING}""",  # noqa: S608
            ctx.tenant_id,
            conversation_id,
            ctx.user.id,
            message_type,
            text,
            template_data,
            body.reply_to_id,
            idempotency_key,
        )
        await emit(
            conn,
            "whatsapp.send_requested",
            {"message_id": str(row["id"])},
            tenant_id=ctx.tenant_id,
            dedupe_key=f"send:{row['id']}",
            priority=10,
        )
        return QueuedMessage.model_validate(dict(row))


@router.get("/{conversation_id}", response_model=ConversationSummary)
async def get_conversation(ctx: Ctx, conversation_id: UUID) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        return await _summary_of(conn, ctx.user.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    ctx: Ctx, conversation_id: UUID, cursor: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """Oldest first within a page; the cursor walks further into the past."""
    keys = _decode_message_cursor(cursor) if cursor else (None, None)
    size = min(limit, 200)
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await _summary_of(conn, ctx.user.id, conversation_id)  # 404 before reading the thread
        rows = await conn.fetch(THREAD, conversation_id, keys[0], keys[1], size + 1)
    page, has_more = rows[:size], len(rows) > size
    return {
        "data": [message_out(row) for row in reversed(page)],
        "next_cursor": _encode_message_cursor(page[-1]) if has_more and page else None,
    }


@router.post(
    "/{conversation_id}/notes", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
async def add_note(ctx: Ctx, conversation_id: UUID, body: NoteIn) -> dict[str, Any]:
    """An internal note. It reaches no connector because nothing queues it."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await _summary_of(conn, ctx.user.id, conversation_id)
        message_id = await conn.fetchval(
            """insert into messages (tenant_id, conversation_id, kind, type, direction, sender,
                                     origin, author_user_id, body)
               values ($1, $2, 'note', 'text', 'out', 'human', 'inbox', $3, $4)
               returning id""",
            ctx.tenant_id,
            conversation_id,
            ctx.user.id,
            body.text,
        )
        row = await conn.fetchrow(MESSAGE, message_id)
        assert row is not None  # noqa: S101 - written a statement ago, in this session
        return message_out(row)


@router.post("/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_conversation_read(ctx: Ctx, conversation_id: UUID) -> Response:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await _summary_of(conn, ctx.user.id, conversation_id)
        await conn.execute(
            """insert into conversation_reads (tenant_id, conversation_id, user_id, last_read_at)
               values ($1, $2, $3, now())
               on conflict (conversation_id, user_id)
                 do update set last_read_at = excluded.last_read_at""",
            ctx.tenant_id,
            conversation_id,
            ctx.user.id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/assign", response_model=ConversationSummary)
async def assign_conversation(
    conversation_id: UUID,
    body: AssignIn,
    ctx: Annotated[TenantContext, Depends(require_permission("inbox.send"))],
) -> dict[str, Any]:
    """Claiming yourself needs nothing more; anyone else needs inbox.assign."""
    if body.user_id != ctx.user.id and not ctx.may("inbox.assign"):
        raise Forbidden("assigning to someone else needs the inbox.assign permission")

    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await _summary_of(conn, ctx.user.id, conversation_id)
        await conn.execute(
            """update conversations set assigned_to = $2, owner_id = coalesce(owner_id, $2)
               where id = $1""",
            conversation_id,
            body.user_id,
        )
        name = (
            await conn.fetchval("select full_name from profiles where id = $1", body.user_id)
            if body.user_id
            else None
        )
        await event_line(
            conn,
            ctx.tenant_id,
            conversation_id,
            "assigned" if body.user_id else "unassigned",
            f"Assigned to {name or 'a colleague'}" if body.user_id else "Returned to the queue",
        )
        if body.user_id and body.user_id != ctx.user.id:
            await emit(
                conn,
                "notification.requested",
                {"kind": "assigned", "conversation_id": str(conversation_id)},
                tenant_id=ctx.tenant_id,
                dedupe_key=f"assigned:{conversation_id}:{body.user_id}",
                priority=8,
            )
        # Reassigned to a colleague, a salesperson can no longer see it — so the
        # answer is read back with the caller's own scope and may be a 404.
        return await _summary_of(conn, ctx.user.id, conversation_id)


@router.post("/{conversation_id}/status", response_model=ConversationSummary)
async def set_conversation_status(
    ctx: Ctx, conversation_id: UUID, body: StatusIn
) -> dict[str, Any]:
    """open, closed or spam. Closing stops the timer: the customer has an answer."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await _summary_of(conn, ctx.user.id, conversation_id)
        await conn.execute(
            """update conversations set
                 status = $2,
                 waiting_since = case when $2 = 'open' then waiting_since else null end,
                 sla_due_at = case when $2 = 'open' then sla_due_at else null end
               where id = $1""",
            conversation_id,
            body.status,
        )
        said = {"open": "Reopened", "closed": "Closed", "spam": "Marked as spam"}[body.status]
        await event_line(
            conn,
            ctx.tenant_id,
            conversation_id,
            {"open": "reopened", "closed": "closed", "spam": "spam"}[body.status],
            said,
        )
        return await _summary_of(conn, ctx.user.id, conversation_id)


@messages_router.post(
    "/{message_id}/retry", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED
)
async def retry_message(
    message_id: UUID,
    ctx: Annotated[TenantContext, Depends(require_permission("inbox.send"))],
) -> dict[str, Any]:
    """Send a failed message again, as itself.

    Only from `failed`. A message still `sending` is the ambiguous case the
    watchdog owns, and re-queueing that is exactly the double send S1 removed.
    The row keeps its id and its idempotency key, so the thread does not grow a
    second bubble.
    """
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        row = await conn.fetchrow(
            """update messages set status = 'queued', error = null, locked_at = null
               where id = $1 and status = 'failed' and direction = 'out' and kind = 'message'
               returning conversation_id""",
            message_id,
        )
        if row is None:
            raise NotFound("no failed message to retry")
        await emit(
            conn,
            "whatsapp.send_requested",
            {"message_id": str(message_id)},
            tenant_id=ctx.tenant_id,
            dedupe_key=f"send:{message_id}:{int(datetime.now(UTC).timestamp())}",
            priority=10,
        )
        message = await conn.fetchrow(MESSAGE, message_id)
        assert message is not None  # noqa: S101 - the row we just updated
        return message_out(message)
