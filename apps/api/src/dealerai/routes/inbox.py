"""The sales inbox: the queue, a conversation, and what you can do to it."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, Field, model_validator

from ..core.errors import (
    ChannelUnavailable,
    ConsentRequired,
    Forbidden,
    NotFound,
    Unusable,
    WindowClosed,
)
from ..db.queries.inbox import COUNTS, VIEW_SQL, VIEWS_BY_SCOPE, View, list_sql
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..events.bus import emit
from ..sales.messaging import (
    render_template,
    template_block_reason,
    variable_numbers,
    window_is_open,
)

router = APIRouter(prefix="/v1/conversations", tags=["inbox"])

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
