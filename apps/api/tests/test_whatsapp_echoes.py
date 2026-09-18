"""Messages sent from the phone are visible without extending the service window."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from conftest import TENANT_A
from dealerai.events.bus import Event
from dealerai.events.handlers.whatsapp import on_echo_received, on_user_id_changed

CHANNEL = UUID("aaaaaaaa-1111-4111-8111-111111111111")
WINDOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


async def _conversation(su: asyncpg.Connection) -> tuple[UUID, UUID]:
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'phone-1', 'waba-1', 'coexistence')""",
        CHANNEL,
        TENANT_A,
    )
    contact_id = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Karim') returning id", TENANT_A
    )
    await su.execute(
        """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
           values ($1, $2, 'whatsapp_user_id', 'AE.old', true)""",
        TENANT_A,
        contact_id,
    )
    conversation_id = await su.fetchval(
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, waiting_since,
              sla_due_at, wa_window_expires_at)
           values ($1,$2,$3,'whatsapp',now(),now()+interval '5 minutes',$4) returning id""",
        TENANT_A,
        contact_id,
        CHANNEL,
        WINDOW,
    )
    return UUID(str(contact_id)), UUID(str(conversation_id))


async def test_phone_echo_stops_waiting_but_does_not_move_the_window(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    _, conversation_id = await _conversation(su)
    sent_at = WINDOW - timedelta(hours=1)
    await on_echo_received(
        Event(
            id=40,
            tenant_id=TENANT_A,
            event_type="whatsapp.echo_received",
            payload={
                "channel_id": str(CHANNEL),
                "message": {
                    "id": "wamid.phone-1",
                    "to_user_id": "AE.old",
                    "timestamp": str(int(sent_at.timestamp())),
                    "type": "text",
                    "text": {"body": "Yes, it is available."},
                },
            },
            attempts=1,
            dedupe_key="wamid.phone-1",
        )
    )
    message = await su.fetchrow(
        "select direction, sender, origin, body from messages where external_id='wamid.phone-1'"
    )
    assert message is not None and tuple(message.values()) == (
        "out",
        "human",
        "phone_app",
        "Yes, it is available.",
    )
    conversation = await su.fetchrow(
        """select waiting_since, sla_due_at, first_response_at, wa_window_expires_at
           from conversations where id=$1""",
        conversation_id,
    )
    assert conversation is not None
    assert conversation["waiting_since"] is None
    assert conversation["sla_due_at"] is None
    assert conversation["first_response_at"] == sent_at
    assert conversation["wa_window_expires_at"] == WINDOW


async def test_bsuid_change_keeps_the_same_contact(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact_id, _ = await _conversation(su)
    await on_user_id_changed(
        Event(
            id=41,
            tenant_id=TENANT_A,
            event_type="whatsapp.user_id_changed",
            payload={
                "channel_id": str(CHANNEL),
                "update": {"previous": "AE.old", "current": "AE.new"},
            },
            attempts=1,
            dedupe_key="AE.old:AE.new",
        )
    )
    identity = await su.fetchrow(
        """select contact_id, value from contact_identities
           where tenant_id=$1 and kind='whatsapp_user_id'""",
        TENANT_A,
    )
    assert identity is not None and (identity["contact_id"], identity["value"]) == (
        contact_id,
        "AE.new",
    )
