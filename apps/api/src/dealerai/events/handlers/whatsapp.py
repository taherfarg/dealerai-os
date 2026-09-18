"""WhatsApp webhook event handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from ...db.session import tenant_session
from ...sales.identity import resolve_whatsapp_identity
from ...sales.messaging import is_opt_out
from ..bus import Event, emit, handler


def _at(message: dict[str, Any]) -> datetime:
    try:
        return datetime.fromtimestamp(int(message["timestamp"]), UTC)
    except (KeyError, TypeError, ValueError, OSError):
        return datetime.now(UTC)


def _body(message: dict[str, Any]) -> str | None:
    kind = str(message.get("type") or "")
    content = message.get(kind)
    if isinstance(content, dict):
        value = content.get("body") or content.get("text") or content.get("title")
        return str(value) if value else None
    return None


def _type(message: dict[str, Any]) -> str:
    kind = str(message.get("type") or "unsupported")
    allowed = {
        "text",
        "image",
        "audio",
        "video",
        "document",
        "location",
        "sticker",
        "template",
        "interactive_reply",
    }
    return kind if kind in allowed else "unsupported"


def _media(message: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(message.get("type") or "")
    if kind not in {"image", "audio", "video", "document", "sticker"}:
        return []
    content = message.get(kind)
    if not isinstance(content, dict) or not content.get("id"):
        return []
    return [
        {
            "external_id": str(content["id"]),
            "mime": str(content.get("mime_type") or "application/octet-stream"),
            "filename": content.get("filename"),
            "status": "pending",
        }
    ]


@handler("whatsapp.message_received")
async def on_message_received(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("whatsapp.message_received requires a tenant")
    tenant_id = event.tenant_id
    message = event.payload.get("message")
    if not isinstance(message, dict) or not message.get("id"):
        raise ValueError("whatsapp.message_received requires a message id")
    external_id = str(message["id"])
    channel_id = UUID(str(event.payload["channel_id"]))
    contacts = event.payload.get("contacts")
    contact_data = contacts[0] if isinstance(contacts, list) and contacts else {}
    contact_data = contact_data if isinstance(contact_data, dict) else {}
    profile = contact_data.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    bsuid = message.get("from_user_id") or contact_data.get("user_id")
    wa_id = message.get("from") or contact_data.get("wa_id")
    sent_at = _at(message)
    body = _body(message)
    media = _media(message)
    opted_out = is_opt_out(body)

    async with tenant_session(tenant_id) as conn:
        if await conn.fetchval(
            "select exists(select 1 from messages where tenant_id=$1 and external_id=$2)",
            tenant_id,
            external_id,
        ):
            return

        contact_id = await resolve_whatsapp_identity(
            conn,
            tenant_id=tenant_id,
            bsuid=str(bsuid) if bsuid else None,
            wa_id=str(wa_id) if wa_id else None,
            profile_name=str(profile.get("name")) if profile.get("name") else None,
            team_id=None,
        )
        conversation = await conn.fetchrow(
            """select id, status, assigned_to
               from conversations
               where contact_id=$1 and channel_id=$2
                 and status in ('open', 'waiting_customer', 'escalated')
               order by last_message_at desc nulls last, created_at desc limit 1""",
            contact_id,
            channel_id,
        )
        reopened = False
        if conversation is None:
            conversation = await conn.fetchrow(
                """select id, status, assigned_to from conversations
                   where contact_id=$1 and channel_id=$2
                   order by last_message_at desc nulls last, created_at desc limit 1""",
                contact_id,
                channel_id,
            )
            reopened = conversation is not None
        if conversation is None:
            conversation = await conn.fetchrow(
                """insert into conversations
                     (tenant_id, contact_id, channel_id, surface, owner_id, team_id)
                   select $1, c.id, $2, 'whatsapp', c.owner_id, c.team_id
                   from contacts c where c.id=$3
                   returning id, status, assigned_to""",
                tenant_id,
                channel_id,
                contact_id,
            )
        if conversation is None:  # pragma: no cover - contact exists in this transaction
            raise RuntimeError("could not create the WhatsApp conversation")
        conversation_id = conversation["id"]

        if reopened:
            await conn.execute(
                """insert into messages
                     (tenant_id, conversation_id, direction, sender, origin, kind, type, event,
                      created_at)
                   values ($1, $2, 'in', 'system', 'system', 'event', 'unsupported',
                           '{"type":"conversation.reopened"}'::jsonb, $3)""",
                tenant_id,
                conversation_id,
                sent_at,
            )

        message_id = await conn.fetchval(
            """insert into messages
                 (tenant_id, conversation_id, direction, sender, origin, type, body, media,
                  external_id, referral, created_at)
               values ($1, $2, 'in', 'customer', 'customer', $3, $4, $5, $6, $7, $8)
               on conflict do nothing returning id""",
            tenant_id,
            conversation_id,
            _type(message),
            body,
            media,
            external_id,
            message.get("referral"),
            sent_at,
        )
        if message_id is None:
            return

        settings = await conn.fetchval("select sales_settings from tenants where id=$1", tenant_id)
        target_minutes = int((settings or {}).get("first_response_target_min", 5))
        await conn.execute(
            """update conversations set
                 status='open',
                 last_message_at=greatest(last_message_at, $2),
                 last_inbound_at=greatest(last_inbound_at, $2),
                 wa_window_expires_at=greatest(wa_window_expires_at, $2 + interval '24 hours'),
                 waiting_since=coalesce(waiting_since, $2),
                 sla_due_at=coalesce(sla_due_at, $2 + make_interval(mins => $3))
               where id=$1""",
            conversation_id,
            sent_at,
            target_minutes,
        )
        if opted_out:
            await conn.execute(
                """update contacts
                   set consent = consent || jsonb_build_object('opted_out_at', $2::text)
                   where id=$1""",
                contact_id,
                sent_at.isoformat(),
            )

        if conversation["assigned_to"] is None:
            await emit(
                conn,
                "conversation.assign_requested",
                {"conversation_id": str(conversation_id)},
                tenant_id=tenant_id,
                dedupe_key=f"assign:{conversation_id}",
                priority=8,
            )
        await emit(
            conn,
            "notification.requested",
            {"conversation_id": str(conversation_id), "message_id": str(message_id)},
            tenant_id=tenant_id,
            dedupe_key=f"notify:{message_id}",
            priority=8,
        )
        for asset in media:
            await emit(
                conn,
                "message.media_requested",
                {
                    "message_id": str(message_id),
                    "channel_id": str(channel_id),
                    "media_id": asset["external_id"],
                    "mime": asset["mime"],
                    "filename": asset["filename"],
                },
                tenant_id=tenant_id,
                dedupe_key=f"media:{message_id}:{asset['external_id']}",
                priority=5,
            )
        now = datetime.now(UTC)
        if body and not opted_out:
            await emit(
                conn,
                "copilot.draft_requested",
                {"conversation_id": str(conversation_id), "message_id": str(message_id)},
                tenant_id=tenant_id,
                dedupe_key=f"draft:{message_id}",
                run_after=now + timedelta(seconds=20),
                priority=5,
            )
        await emit(
            conn,
            "conversation.idle",
            {"conversation_id": str(conversation_id), "message_id": str(message_id)},
            tenant_id=tenant_id,
            dedupe_key=f"idle:{conversation_id}",
            run_after=now + timedelta(minutes=15),
            priority=5,
        )
