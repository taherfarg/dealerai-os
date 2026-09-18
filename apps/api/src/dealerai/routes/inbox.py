"""Conversation actions for the sales inbox."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field, model_validator

from ..connectors.base import OutsideMessagingWindow, RequestRejected
from ..core.errors import NotFound, Unusable
from ..db.session import tenant_session
from ..deps import TenantContext, require_permission
from ..events.bus import emit
from ..sales.messaging import (
    render_template,
    template_block_reason,
    variable_numbers,
    window_is_open,
)

router = APIRouter(prefix="/v1/conversations", tags=["inbox"])


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
            raise RequestRejected("the WhatsApp channel is not connected", code="channel_inactive")

        consent = dict(conversation["consent"] or {})
        message_type = "text"
        text = body.text
        template_data: dict[str, Any] | None = None
        if body.template_id is None:
            if consent.get("opted_out_at"):
                raise RequestRejected("the customer asked not to be messaged", code="opted_out")
            if not window_is_open(conversation["wa_window_expires_at"], datetime.now(UTC)):
                raise OutsideMessagingWindow("choose an approved template to continue")
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
                raise RequestRejected("the template is not approved", code="template_not_approved")
            reason = template_block_reason(template["category"], consent)
            if reason:
                raise RequestRejected(reason, code="consent_required")
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
