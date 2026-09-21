"""WhatsApp webhook event handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from ...ai.transcription import transcribe_audio
from ...connectors.base import (
    MessageRequest,
    NotSupported,
    OutsideMessagingWindow,
    RateLimited,
    RequestRejected,
    TokenExpired,
)
from ...connectors.channels import whatsapp_for_channel
from ...connectors.whatsapp import template_status
from ...db.session import tenant_session
from ...media import storage
from ...sales import hours
from ...sales.identity import resolve_whatsapp_identity
from ...sales.messaging import is_opt_out, variable_numbers
from ...sales.settings import SalesSettings
from ..bus import Event, emit, handler

log = structlog.get_logger()

_STATUS_ORDER = {"queued": 0, "sending": 1, "sent": 2, "delivered": 3, "read": 4}


def _media_asset(media: list[dict[str, Any]], external_id: str) -> dict[str, Any] | None:
    return next((asset for asset in media if str(asset.get("external_id")) == external_id), None)


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


def _timezone(name: str | None) -> ZoneInfo:
    """The tenant's timezone, or UTC if it names one this machine does not have."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("tenant_timezone_unknown", timezone=name)
        return ZoneInfo("UTC")


async def _start_the_timer(
    conn: Any,
    tenant_id: UUID,
    conversation_id: UUID,
    waiting_since: datetime,
    tenant: Any,
) -> None:
    """Set the response target in business hours, and book its two checks.

    A customer who writes at 23:30 is not late at 23:35, so the due time counts
    minutes the team is open (docs/sales/05-workflows.md § 5).
    """
    settings = SalesSettings.model_validate((tenant["sales_settings"] if tenant else None) or {})
    due = hours.due_at(
        waiting_since,
        settings=settings,
        tz=_timezone(tenant["timezone"] if tenant else None),
    )
    await conn.execute(
        "update conversations set sla_due_at=$2 where id=$1 and waiting_since=$3",
        conversation_id,
        due,
        waiting_since,
    )
    started = waiting_since.isoformat()
    await emit(
        conn,
        "conversation.sla_check",
        {"conversation_id": str(conversation_id), "level": "due_soon", "waiting_since": started},
        tenant_id=tenant_id,
        dedupe_key=f"sla:{conversation_id}:{started}:due_soon",
        run_after=due - timedelta(minutes=2),
        priority=8,
    )


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

        tenant = await conn.fetchrow(
            "select sales_settings, timezone from tenants where id=$1", tenant_id
        )
        # The customer may already have been waiting: the target counts from then,
        # not from this message.
        started_waiting = await conn.fetchval(
            """update conversations set
                 status='open',
                 last_message_at=greatest(last_message_at, $2),
                 last_inbound_at=greatest(last_inbound_at, $2),
                 wa_window_expires_at=greatest(wa_window_expires_at, $2 + interval '24 hours'),
                 waiting_since=coalesce(waiting_since, $2)
               where id=$1
               returning waiting_since""",
            conversation_id,
            sent_at,
        )
        await _start_the_timer(conn, tenant_id, conversation_id, started_waiting, tenant)
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


@handler("whatsapp.status_received")
async def on_status_received(event: Event) -> None:
    """Advance one outbound message; retry a status that raced ahead of its send write."""
    if event.tenant_id is None:
        raise ValueError("whatsapp.status_received requires a tenant")
    raw = event.payload.get("status")
    if not isinstance(raw, dict) or not raw.get("id"):
        raise ValueError("whatsapp.status_received requires a message id")
    external_id = str(raw["id"])
    incoming = str(raw.get("status") or "")
    if incoming not in {*_STATUS_ORDER, "failed"}:
        log.warning("whatsapp_status_unknown", status=incoming, external_id=external_id)
        return

    async with tenant_session(event.tenant_id) as conn:
        current = await conn.fetchrow(
            "select id, status from messages where tenant_id=$1 and external_id=$2",
            event.tenant_id,
            external_id,
        )
        if current is None:
            if event.attempts < event.max_attempts:
                raise LookupError(f"message {external_id} has not been stored yet")
            log.warning("whatsapp_status_orphaned", external_id=external_id)
            return
        if current["status"] == "failed":
            return
        if incoming != "failed" and _STATUS_ORDER.get(incoming, -1) <= _STATUS_ORDER.get(
            current["status"], -1
        ):
            return

        at = _at(raw)
        errors = raw.get("errors")
        first_error = errors[0] if isinstance(errors, list) and errors else {}
        first_error = first_error if isinstance(first_error, dict) else {}
        error = (
            {
                "code": str(first_error.get("code") or "unknown"),
                "message": str(
                    first_error.get("message") or first_error.get("title") or "Message failed"
                ),
            }
            if incoming == "failed"
            else None
        )
        await conn.execute(
            """update messages set
                 status=$2,
                 delivered_at=case when $2 in ('delivered','read')
                                   then coalesce(delivered_at, $3) else delivered_at end,
                 read_at=case when $2='read' then coalesce(read_at, $3) else read_at end,
                 pricing=coalesce($4, pricing),
                 error=case when $2='failed' then $5 else error end
               where id=$1""",
            current["id"],
            incoming,
            at,
            raw.get("pricing"),
            error,
        )


@handler("message.media_requested")
async def on_media_requested(event: Event) -> None:
    """Download one customer attachment and replace its external reference with storage."""
    if event.tenant_id is None:
        raise ValueError("message.media_requested requires a tenant")
    message_id = UUID(str(event.payload["message_id"]))
    channel_id = UUID(str(event.payload["channel_id"]))
    media_id = str(event.payload["media_id"])

    async with tenant_session(event.tenant_id) as conn:
        row = await conn.fetchrow(
            """select m.media, c.external_id, c.account_id, c.credentials
               from messages m
               join channels c on c.id=$2 and c.tenant_id=m.tenant_id
               where m.id=$1""",
            message_id,
            channel_id,
        )
    if row is None:
        if event.attempts < event.max_attempts:
            raise LookupError(f"message {message_id} has not been stored yet")
        return
    media = list(row["media"] or [])
    asset = _media_asset(media, media_id)
    if asset is None:
        raise ValueError(f"message {message_id} has no media {media_id}")
    if asset.get("status") == "ready":
        return

    try:
        connector = whatsapp_for_channel(dict(row))
        data, mime = await connector.download_media(media_id)
        filename = event.payload.get("filename")
        path = storage.object_path(
            event.tenant_id,
            "messages",
            storage.extension_for(mime, str(filename) if filename else None),
        )
        await storage.upload(path, data, content_type=mime)
    except Exception as exc:
        if event.attempts < event.max_attempts:
            raise
        asset |= {"status": "failed", "error": str(exc)}
        async with tenant_session(event.tenant_id) as conn:
            await conn.execute("update messages set media=$2 where id=$1", message_id, media)
        log.warning("whatsapp_media_failed", message_id=str(message_id), media_id=media_id)
        return

    asset |= {
        "status": "ready",
        "mime": mime,
        "size": len(data),
        "storage_path": path,
    }
    asset.pop("error", None)
    async with tenant_session(event.tenant_id) as conn:
        await conn.execute("update messages set media=$2 where id=$1", message_id, media)
        if mime.split(";", 1)[0].strip().lower().startswith("audio/"):
            await emit(
                conn,
                "message.transcription_requested",
                {"message_id": str(message_id), "media_id": media_id},
                tenant_id=event.tenant_id,
                dedupe_key=f"transcribe:{message_id}:{media_id}",
                priority=5,
            )


@handler("message.transcription_requested")
async def on_transcription_requested(event: Event) -> None:
    """Transcribe one stored audio asset and make it available to the reply copilot."""
    if event.tenant_id is None:
        raise ValueError("message.transcription_requested requires a tenant")
    message_id = UUID(str(event.payload["message_id"]))
    media_id = str(event.payload["media_id"])
    async with tenant_session(event.tenant_id) as conn:
        row = await conn.fetchrow(
            "select media, transcript, conversation_id from messages where id=$1", message_id
        )
    if row is None:
        if event.attempts < event.max_attempts:
            raise LookupError(f"message {message_id} has not been stored yet")
        return
    if row["transcript"]:
        return
    asset = _media_asset(list(row["media"] or []), media_id)
    if asset is None or asset.get("status") != "ready" or not asset.get("storage_path"):
        if event.attempts < event.max_attempts:
            raise LookupError(f"media {media_id} is not ready")
        return

    data = await storage.download(str(asset["storage_path"]))
    result = await transcribe_audio(
        tenant_id=event.tenant_id,
        data=data,
        mime=str(asset.get("mime") or "application/octet-stream"),
    )
    transcript = {"text": result.text, "language": result.language}
    async with tenant_session(event.tenant_id) as conn:
        await conn.execute("update messages set transcript=$2 where id=$1", message_id, transcript)
        if result.text:
            await emit(
                conn,
                "copilot.draft_requested",
                {"conversation_id": str(row["conversation_id"]), "message_id": str(message_id)},
                tenant_id=event.tenant_id,
                dedupe_key=f"draft:{message_id}",
                priority=5,
            )


@handler("whatsapp.send_requested")
async def on_send_requested(event: Event) -> None:
    """Claim one queued message exactly once, then call Meta outside the transaction."""
    if event.tenant_id is None:
        raise ValueError("whatsapp.send_requested requires a tenant")
    message_id = UUID(str(event.payload["message_id"]))
    async with tenant_session(event.tenant_id) as conn:
        row = await conn.fetchrow(
            """with claimed as (
                 update messages set status='sending', locked_at=now()
                 where id=$1 and status='queued'
                 returning *
               )
               select claimed.id, claimed.body, claimed.template, claimed.idempotency_key,
                      claimed.reply_to_id, c.contact_id, c.channel_id,
                      ch.external_id, ch.account_id, ch.credentials
               from claimed
               join conversations c on c.id=claimed.conversation_id
               join channels ch on ch.id=c.channel_id""",
            message_id,
        )
        if row is None:
            return
        await emit(
            conn,
            "whatsapp.send_watchdog",
            {"message_id": str(message_id)},
            tenant_id=event.tenant_id,
            dedupe_key=f"send-watchdog:{message_id}",
            run_after=datetime.now(UTC) + timedelta(minutes=2),
            priority=10,
        )
        recipient = await conn.fetchval(
            """select value from contact_identities
               where contact_id=$1 and kind in ('whatsapp_user_id','phone')
               order by case kind when 'whatsapp_user_id' then 0 else 1 end, is_primary desc
               limit 1""",
            row["contact_id"],
        )
    if not recipient:
        async with tenant_session(event.tenant_id) as conn:
            await conn.execute(
                """update messages set status='failed', locked_at=null,
                          error=$2
                   where id=$1""",
                message_id,
                {
                    "code": "recipient_missing",
                    "message": "Customer has no WhatsApp identity",
                },
            )
        return

    template = dict(row["template"] or {})
    request = MessageRequest(
        recipient_external_id=str(recipient),
        idempotency_key=str(row["idempotency_key"]),
        text=None if template else row["body"],
        template=str(template["name"]) if template else None,
        template_params=dict(template.get("params") or {}),
        template_language=str(template["language"]) if template else None,
    )
    try:
        result = await whatsapp_for_channel(dict(row)).send_message(request)
    except RateLimited:
        # Meta declined to accept it, so nothing reached the customer. Put it
        # back in the queue instead of failing a reply Meta never saw.
        async with tenant_session(event.tenant_id) as conn:
            await conn.execute(
                """update messages set status='queued', locked_at=null
                   where id=$1 and status='sending'""",
                message_id,
            )
        raise
    except (OutsideMessagingWindow, RequestRejected, NotSupported, TokenExpired) as exc:
        # Meta read the request and refused it: nothing was delivered, and the
        # reason is worth showing to the salesperson.
        code = str(getattr(exc, "code", getattr(exc, "slug", "connector_error")))
        async with tenant_session(event.tenant_id) as conn:
            await conn.execute(
                "update messages set status='failed', locked_at=null, error=$2 where id=$1",
                message_id,
                {"code": code, "message": str(exc)},
            )
            if isinstance(exc, TokenExpired):
                await conn.execute(
                    "update channels set status='expired' where id=$1", row["channel_id"]
                )
        return
    # Anything else — a timeout, a 5xx, a dropped connection — leaves the send
    # ambiguous: Meta may already have delivered it. The row stays 'sending' and
    # the watchdog calls it "delivery unknown" two minutes later, because a
    # customer-visible double send is the worse of the two mistakes
    # (docs/sales/03-whatsapp.md § 7). Nothing here auto-resends: the claim
    # above only ever moves a message out of 'queued'.

    async with tenant_session(event.tenant_id) as conn:
        conversation_id = await conn.fetchval(
            """update messages set status='sent', external_id=$2, locked_at=null
               where id=$1 and status='sending'
               returning conversation_id""",
            message_id,
            result.external_id,
        )
        if conversation_id is not None:
            # The customer has their answer, so the queue stops counting. Here
            # rather than where Send was pressed: until Meta has accepted it
            # nobody has replied to anything, and a queue that stops showing a
            # customer who is still waiting is worse than one that is a second
            # late (docs/sales/05-workflows.md § 3).
            await conn.execute(
                """update conversations set
                     waiting_since=null, sla_due_at=null,
                     first_response_at=coalesce(first_response_at, now())
                   where id=$1""",
                conversation_id,
            )


@handler("whatsapp.send_watchdog")
async def on_send_watchdog(event: Event) -> None:
    """Fail an ambiguous send instead of risking a customer-visible duplicate."""
    if event.tenant_id is None:
        raise ValueError("whatsapp.send_watchdog requires a tenant")
    message_id = UUID(str(event.payload["message_id"]))
    async with tenant_session(event.tenant_id) as conn:
        await conn.execute(
            """update messages set
                 status='failed', locked_at=null,
                 error=$2
               where id=$1 and status='sending' and external_id is null
                 and locked_at <= now() - interval '2 minutes'""",
            message_id,
            {
                "code": "delivery_unknown",
                "message": "Delivery unknown — check the conversation before resending",
            },
        )


def _template_body(components: list[dict[str, Any]]) -> str:
    for component in components:
        if str(component.get("type") or "").upper() == "BODY":
            return str(component.get("text") or "")
    return ""


@handler("whatsapp.templates_sync_requested")
async def on_templates_sync_requested(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("whatsapp.templates_sync_requested requires a tenant")
    channel_id = UUID(str(event.payload["channel_id"]))
    async with tenant_session(event.tenant_id) as conn:
        channel = await conn.fetchrow(
            "select id, external_id, account_id, credentials from channels where id=$1",
            channel_id,
        )
    if channel is None:
        raise LookupError(f"channel {channel_id} does not exist")
    templates = await whatsapp_for_channel(dict(channel)).list_templates()

    async with tenant_session(event.tenant_id) as conn:
        await conn.execute(
            "update message_templates set status='disabled', synced_at=now() where channel_id=$1",
            channel_id,
        )
        for template in templates:
            body = _template_body(template.components)
            await conn.execute(
                """insert into message_templates
                     (tenant_id, channel_id, external_id, name, language, category, status,
                      components, body, variables, rejected_reason, synced_at)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,now())
                   on conflict (channel_id, name, language) do update set
                     external_id=excluded.external_id,
                     category=excluded.category,
                     status=excluded.status,
                     components=excluded.components,
                     body=excluded.body,
                     variables=excluded.variables,
                     rejected_reason=excluded.rejected_reason,
                     synced_at=now()""",
                event.tenant_id,
                channel_id,
                template.external_id,
                template.name,
                template.language,
                template.category,
                template.status,
                template.components,
                body,
                [str(number) for number in variable_numbers(body)],
                template.rejected_reason,
            )


@handler("whatsapp.template_status")
async def on_template_status(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("whatsapp.template_status requires a tenant")
    channel_id = UUID(str(event.payload["channel_id"]))
    update = event.payload.get("update")
    if not isinstance(update, dict):
        raise ValueError("whatsapp.template_status requires an update")
    external_id = str(update.get("message_template_id") or update.get("id") or "")
    status = template_status(str(update.get("event") or update.get("status") or ""))
    reason = update.get("reason") or update.get("rejected_reason")
    async with tenant_session(event.tenant_id) as conn:
        template_id = await conn.fetchval(
            """update message_templates set status=$3, rejected_reason=$4, synced_at=now()
               where channel_id=$1 and external_id=$2 returning id""",
            channel_id,
            external_id,
            status,
            str(reason) if reason else None,
        )
        if template_id is None:
            if event.attempts < event.max_attempts:
                raise LookupError(f"template {external_id} has not been synchronized yet")
            return
        if status == "rejected":
            await emit(
                conn,
                "notification.requested",
                {
                    "kind": "template_rejected",
                    "channel_id": str(channel_id),
                    "template_id": str(template_id),
                },
                tenant_id=event.tenant_id,
                dedupe_key=f"template-rejected:{template_id}",
                priority=2,
            )


@handler("whatsapp.echo_received")
async def on_echo_received(event: Event) -> None:
    """Mirror a reply sent from the WhatsApp Business app into the inbox."""
    if event.tenant_id is None:
        raise ValueError("whatsapp.echo_received requires a tenant")
    message = event.payload.get("message")
    if not isinstance(message, dict) or not message.get("id"):
        raise ValueError("whatsapp.echo_received requires a message id")
    channel_id = UUID(str(event.payload["channel_id"]))
    external_id = str(message["id"])
    bsuid = message.get("to_user_id") or message.get("recipient_user_id")
    wa_id = message.get("to") or message.get("recipient_id")
    sent_at = _at(message)
    media = _media(message)

    async with tenant_session(event.tenant_id) as conn:
        if await conn.fetchval(
            "select exists(select 1 from messages where external_id=$1)", external_id
        ):
            return
        contact_id = await resolve_whatsapp_identity(
            conn,
            tenant_id=event.tenant_id,
            bsuid=str(bsuid) if bsuid else None,
            wa_id=str(wa_id) if wa_id else None,
            profile_name=None,
            team_id=None,
        )
        conversation = await conn.fetchrow(
            """select id from conversations
               where contact_id=$1 and channel_id=$2
               order by last_message_at desc nulls last, created_at desc limit 1""",
            contact_id,
            channel_id,
        )
        if conversation is None:
            conversation_id = await conn.fetchval(
                """insert into conversations
                     (tenant_id, contact_id, channel_id, surface, owner_id, team_id)
                   select $1, c.id, $2, 'whatsapp', c.owner_id, c.team_id
                   from contacts c where c.id=$3 returning id""",
                event.tenant_id,
                channel_id,
                contact_id,
            )
        else:
            conversation_id = conversation["id"]
        message_id = await conn.fetchval(
            """insert into messages
                 (tenant_id, conversation_id, direction, sender, origin, type, body,
                  media, external_id, status, created_at)
               values ($1,$2,'out','human','phone_app',$3,$4,$5,$6,'sent',$7)
               on conflict do nothing returning id""",
            event.tenant_id,
            conversation_id,
            _type(message),
            _body(message),
            media,
            external_id,
            sent_at,
        )
        if message_id is None:
            return
        await conn.execute(
            """update conversations set
                 status='open',
                 last_message_at=greatest(last_message_at, $2),
                 waiting_since=null,
                 sla_due_at=null,
                 first_response_at=coalesce(first_response_at, $2)
               where id=$1""",
            conversation_id,
            sent_at,
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
                tenant_id=event.tenant_id,
                dedupe_key=f"media:{message_id}:{asset['external_id']}",
                priority=5,
            )


@handler("whatsapp.user_id_changed")
async def on_user_id_changed(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("whatsapp.user_id_changed requires a tenant")
    update = event.payload.get("update")
    if not isinstance(update, dict):
        raise ValueError("whatsapp.user_id_changed requires an update")
    previous = str(update.get("previous") or "")
    current = str(update.get("current") or "")
    if not previous or not current:
        raise ValueError("user id update needs previous and current values")
    async with tenant_session(event.tenant_id) as conn:
        changed = await conn.fetchval(
            """update contact_identities set value=$3
               where tenant_id=$1 and kind='whatsapp_user_id' and value=$2
               returning id""",
            event.tenant_id,
            previous,
            current,
        )
        if changed is None and event.attempts < event.max_attempts:
            raise LookupError(f"WhatsApp user id {previous} is not known")


@handler("whatsapp.account_update")
async def on_account_update(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("whatsapp.account_update requires a tenant")
    channel_id = UUID(str(event.payload["channel_id"]))
    update = event.payload.get("update")
    if not isinstance(update, dict):
        raise ValueError("whatsapp.account_update requires an update")
    change = str(update.get("event") or update.get("status") or "").upper()
    if change != "PARTNER_REMOVED":
        return
    async with tenant_session(event.tenant_id) as conn:
        await conn.execute("update channels set status='revoked' where id=$1", channel_id)
        await emit(
            conn,
            "notification.requested",
            {"kind": "channel_disconnected", "channel_id": str(channel_id)},
            tenant_id=event.tenant_id,
            dedupe_key=f"whatsapp-disconnected:{channel_id}",
            priority=10,
        )


@handler("whatsapp.quality_update")
async def on_quality_update(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("whatsapp.quality_update requires a tenant")
    channel_id = UUID(str(event.payload["channel_id"]))
    update = event.payload.get("update")
    if not isinstance(update, dict):
        raise ValueError("whatsapp.quality_update requires an update")
    rating = str(update.get("quality_rating") or update.get("current_quality_rating") or "").lower()
    if rating not in {"green", "yellow", "red"}:
        log.warning("whatsapp_quality_unknown", rating=rating, channel_id=str(channel_id))
        return
    async with tenant_session(event.tenant_id) as conn:
        await conn.execute("update channels set quality_rating=$2 where id=$1", channel_id, rating)
        if rating in {"yellow", "red"}:
            await emit(
                conn,
                "notification.requested",
                {
                    "kind": "channel_quality",
                    "channel_id": str(channel_id),
                    "rating": rating,
                },
                tenant_id=event.tenant_id,
                dedupe_key=f"whatsapp-quality:{channel_id}:{rating}",
                priority=2,
            )
