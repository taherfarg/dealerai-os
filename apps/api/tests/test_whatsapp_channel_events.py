"""WhatsApp account and number health webhooks change channel sendability."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from conftest import TENANT_A
from dealerai.events.bus import Event
from dealerai.events.handlers.whatsapp import on_account_update, on_quality_update
from dealerai.routes.webhooks import _items

CHANNEL = UUID("aaaaaaaa-1111-4111-8111-111111111111")


async def _channel(su: asyncpg.Connection) -> None:
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'phone-1', 'waba-1', 'coexistence')""",
        CHANNEL,
        TENANT_A,
    )


def test_channel_updates_are_routed_with_stable_dedupe_keys() -> None:
    [account] = _items(
        "account_update",
        {"event": "PARTNER_REMOVED", "timestamp": "10"},
        CHANNEL,
    )
    assert (account.event_type, account.priority, account.dedupe_key) == (
        "whatsapp.account_update",
        10,
        "PARTNER_REMOVED:10",
    )
    [quality] = _items(
        "phone_number_quality_update",
        {
            "event": "FLAGGED",
            "current_limit": "TIER_1K",
            "quality_rating": "YELLOW",
            "timestamp": "11",
        },
        CHANNEL,
    )
    assert (quality.event_type, quality.priority) == ("whatsapp.quality_update", 2)


async def test_partner_removed_revokes_the_channel_and_notifies(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    await on_account_update(
        Event(
            id=50,
            tenant_id=TENANT_A,
            event_type="whatsapp.account_update",
            payload={
                "channel_id": str(CHANNEL),
                "update": {"event": "PARTNER_REMOVED", "timestamp": "10"},
            },
            attempts=1,
            dedupe_key="PARTNER_REMOVED:10",
        )
    )
    assert await su.fetchval("select status from channels where id=$1", CHANNEL) == "revoked"
    [event] = await su.fetch("select payload from events where event_type='notification.requested'")
    assert json.loads(event["payload"])["kind"] == "channel_disconnected"


async def test_quality_warning_is_stored_and_notifies(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _channel(su)
    await on_quality_update(
        Event(
            id=51,
            tenant_id=TENANT_A,
            event_type="whatsapp.quality_update",
            payload={
                "channel_id": str(CHANNEL),
                "update": {"quality_rating": "YELLOW", "timestamp": "11"},
            },
            attempts=1,
            dedupe_key="YELLOW:11",
        )
    )
    assert await su.fetchval("select quality_rating from channels where id=$1", CHANNEL) == "yellow"
    [event] = await su.fetch("select payload from events where event_type='notification.requested'")
    assert json.loads(event["payload"])["kind"] == "channel_quality"
