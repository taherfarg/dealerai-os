"""A WhatsApp message becomes a visible, idempotent inbox message before side effects."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from conftest import TENANT_A
from dealerai.events.bus import Event
from dealerai.events.handlers.whatsapp import on_message_received

CHANNEL = UUID("aaaaaaaa-1111-4111-8111-111111111111")
MESSAGE_AT = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


async def _channel(su: asyncpg.Connection) -> None:
    await su.execute(
        """insert into channels
             (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'phone-1', 'waba-1', 'cloud_api')""",
        CHANNEL,
        TENANT_A,
    )
    await su.execute(
        """update tenants
           set sales_settings = '{"first_response_target_min": 5}'::jsonb
           where id = $1""",
        TENANT_A,
    )


def _event(
    *,
    message_id: str = "wamid.in-1",
    text: str | None = "Is the Hilux available?",
    message_type: str = "text",
) -> Event:
    message: dict[str, object] = {
        "id": message_id,
        "from": "971500000101",
        "from_user_id": "AE.13491208655302741918",
        "timestamp": str(int(MESSAGE_AT.timestamp())),
        "type": message_type,
    }
    if text is not None:
        message["text"] = {"body": text}
    if message_type == "audio":
        message["audio"] = {"id": "media-1", "mime_type": "audio/ogg; codecs=opus"}
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="whatsapp.message_received",
        payload={
            "channel_id": str(CHANNEL),
            "contacts": [
                {
                    "profile": {"name": "Karim"},
                    "wa_id": "971500000101",
                    "user_id": "AE.13491208655302741918",
                }
            ],
            "metadata": {"phone_number_id": "phone-1"},
            "message": message,
        },
        attempts=1,
        dedupe_key=message_id,
    )


async def test_a_customer_message_creates_the_thread_message_and_followups(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    await on_message_received(_event())

    [message] = await su.fetch(
        """select m.external_id, m.body, m.type, m.origin, m.created_at,
                  c.contact_id, c.channel_id, c.status, c.last_message_at,
                  c.last_inbound_at, c.wa_window_expires_at, c.waiting_since, c.sla_due_at
           from messages m join conversations c on c.id = m.conversation_id
           where m.tenant_id = $1 and m.external_id = 'wamid.in-1'""",
        TENANT_A,
    )
    assert (message["body"], message["type"], message["origin"]) == (
        "Is the Hilux available?",
        "text",
        "customer",
    )
    assert message["channel_id"] == CHANNEL
    assert message["status"] == "open"
    assert message["created_at"] == MESSAGE_AT
    assert message["last_message_at"] == MESSAGE_AT
    assert message["last_inbound_at"] == MESSAGE_AT
    assert message["wa_window_expires_at"] == MESSAGE_AT + timedelta(hours=24)
    assert message["waiting_since"] == MESSAGE_AT
    assert message["sla_due_at"] == MESSAGE_AT + timedelta(minutes=5)

    events = await su.fetch(
        "select event_type, priority, run_after, payload from events order by id"
    )
    assert [(e["event_type"], e["priority"]) for e in events] == [
        ("conversation.assign_requested", 8),
        ("notification.requested", 8),
        ("copilot.draft_requested", 5),
        ("conversation.idle", 5),
    ]
    draft = next(e for e in events if e["event_type"] == "copilot.draft_requested")
    assert draft["run_after"] >= MESSAGE_AT + timedelta(seconds=20)


async def test_an_audio_message_is_visible_before_media_work(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    await on_message_received(_event(message_id="wamid.audio", text=None, message_type="audio"))
    row = await su.fetchrow(
        "select id, type, media from messages where tenant_id = $1 and external_id='wamid.audio'",
        TENANT_A,
    )
    assert row is not None and row["type"] == "audio"
    assert json.loads(row["media"])[0]["external_id"] == "media-1"
    [media_event] = await su.fetch(
        "select event_type, payload from events where event_type='message.media_requested'"
    )
    payload = json.loads(media_event["payload"])
    assert payload["message_id"] == str(row["id"])
    assert payload["media_id"] == "media-1"


async def test_replaying_the_handler_creates_no_second_message_or_side_effect(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    event = _event()
    await on_message_received(event)
    await on_message_received(event)
    assert (
        await su.fetchval(
            "select count(*) from messages where tenant_id=$1 and external_id='wamid.in-1'",
            TENANT_A,
        )
        == 1
    )
    assert await su.fetchval("select count(*) from events") == 4


async def test_an_opt_out_is_recorded_before_followups(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    await on_message_received(_event(text="لا تراسلني"))
    consent = await su.fetchval(
        """select c.consent from contacts c
           join contact_identities i on i.contact_id = c.id
           where i.tenant_id=$1 and i.kind='whatsapp_user_id'
             and i.value='AE.13491208655302741918'""",
        TENANT_A,
    )
    assert json.loads(consent)["opted_out_at"] == MESSAGE_AT.isoformat()
    assert not await su.fetchval(
        "select exists(select 1 from events where event_type='copilot.draft_requested')"
    )


async def test_a_closed_conversation_is_reopened_with_an_event_line(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    contact_id = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Karim') returning id", TENANT_A
    )
    await su.execute(
        """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
           values ($1, $2, 'whatsapp_user_id', 'AE.13491208655302741918', true)""",
        TENANT_A,
        contact_id,
    )
    conversation_id = await su.fetchval(
        """insert into conversations (tenant_id, contact_id, channel_id, surface, status)
           values ($1, $2, $3, 'whatsapp', 'closed') returning id""",
        TENANT_A,
        contact_id,
        CHANNEL,
    )
    await on_message_received(_event())
    assert (
        await su.fetchval("select status from conversations where id=$1", conversation_id) == "open"
    )
    [line] = await su.fetch(
        """select kind, type, origin, event from messages
           where conversation_id=$1 and kind='event'""",
        conversation_id,
    )
    assert (line["kind"], line["type"], line["origin"]) == ("event", "unsupported", "system")
    assert json.loads(line["event"])["type"] == "conversation.reopened"
