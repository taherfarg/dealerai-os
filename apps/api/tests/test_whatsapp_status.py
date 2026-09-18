"""WhatsApp delivery statuses only move a sent message forward."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.events.bus import Event
from dealerai.events.handlers.whatsapp import on_status_received

MESSAGE = UUID("aaaaaaaa-2222-4222-8222-222222222222")


async def _message(su: asyncpg.Connection, *, status: str = "sent") -> None:
    conversation = await su.fetchval(
        "select id from conversations where tenant_id=$1 limit 1", TENANT_A
    )
    await su.execute(
        """insert into messages
             (id, tenant_id, conversation_id, direction, sender, origin, status, external_id)
           values ($1, $2, $3, 'out', 'human', 'inbox', $4, 'wamid.out')""",
        MESSAGE,
        TENANT_A,
        conversation,
        status,
    )


def _event(status: str, *, attempts: int = 1, max_attempts: int = 5) -> Event:
    return Event(
        id=9,
        tenant_id=TENANT_A,
        event_type="whatsapp.status_received",
        payload={
            "channel_id": "aaaaaaaa-1111-4111-8111-111111111111",
            "status": {
                "id": "wamid.out",
                "status": status,
                "timestamp": "1789646402",
                "pricing": {"billable": True, "category": "marketing"},
            },
        },
        attempts=attempts,
        dedupe_key=f"wamid.out:{status}",
        max_attempts=max_attempts,
    )


async def test_status_moves_forward_and_keeps_pricing(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _message(su)
    await on_status_received(_event("delivered"))
    await on_status_received(_event("read"))
    await on_status_received(_event("sent"))
    row = await su.fetchrow(
        "select status, delivered_at, read_at, pricing from messages where id=$1", MESSAGE
    )
    assert row["status"] == "read"
    assert row["delivered_at"] == datetime.fromtimestamp(1789646402, UTC)
    assert row["read_at"] == datetime.fromtimestamp(1789646402, UTC)
    assert json.loads(row["pricing"])["category"] == "marketing"


async def test_failed_is_terminal_and_keeps_meta_s_error(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _message(su)
    event = _event("failed")
    event.payload["status"]["errors"] = [
        {"code": 131047, "title": "Re-engagement message", "message": "Window closed"}
    ]
    await on_status_received(event)
    await on_status_received(_event("read"))
    row = await su.fetchrow("select status, error from messages where id=$1", MESSAGE)
    assert row["status"] == "failed"
    error = json.loads(row["error"])
    assert error == {"code": "131047", "message": "Window closed"}


async def test_an_unknown_message_retries_before_the_last_attempt(db: None, seeded: None) -> None:
    with pytest.raises(LookupError, match="wamid.out"):
        await on_status_received(_event("delivered", attempts=2, max_attempts=3))


async def test_an_unknown_message_is_dropped_on_the_last_attempt(db: None, seeded: None) -> None:
    await on_status_received(_event("delivered", attempts=3, max_attempts=3))
