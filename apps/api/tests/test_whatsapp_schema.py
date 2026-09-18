"""What 0007_sales_whatsapp.sql must be true about, before any handler relies on it."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B
from dealerai.db.session import system_session


async def _channel(
    su: asyncpg.Connection, tenant_id: uuid.UUID, phone_number_id: str, waba_id: str = "waba-1"
) -> uuid.UUID:
    return await su.fetchval(
        """insert into channels (tenant_id, platform, external_id, account_id, mode)
           values ($1, 'whatsapp', $2, $3, 'cloud_api') returning id""",
        tenant_id,
        phone_number_id,
        waba_id,
    )


async def _conversation(su: asyncpg.Connection, tenant_id: uuid.UUID) -> uuid.UUID:
    return await su.fetchval("select id from conversations where tenant_id = $1", tenant_id)


async def test_a_phone_number_belongs_to_one_tenant(su: asyncpg.Connection, seeded: None) -> None:
    """Webhooks route by phone_number_id before any tenant is known."""
    await _channel(su, TENANT_A, "15550001")
    with pytest.raises(asyncpg.UniqueViolationError):
        await _channel(su, TENANT_B, "15550001")


async def test_routing_works_before_any_tenant_is_known(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    channel_id = await _channel(su, TENANT_A, "15550001", "waba-a")
    async with system_session() as conn:
        by_number = await conn.fetch(
            "select tenant_id, channel_id from app.route_whatsapp($1, $2)", "15550001", "other"
        )
        by_account = await conn.fetch(
            "select tenant_id, channel_id from app.route_whatsapp($1, $2)", None, "waba-a"
        )
        unknown = await conn.fetch(
            "select tenant_id, channel_id from app.route_whatsapp($1, $2)", "nope", "nope"
        )
    assert [(r["tenant_id"], r["channel_id"]) for r in by_number] == [(TENANT_A, channel_id)]
    assert [(r["tenant_id"], r["channel_id"]) for r in by_account] == [(TENANT_A, channel_id)]
    assert unknown == []


async def test_only_the_api_role_may_route(su: asyncpg.Connection) -> None:
    fn = "app.route_whatsapp(text, text)"
    assert await su.fetchval("select has_function_privilege('dealerai_app', $1, 'execute')", fn)
    for role in ("anon", "authenticated"):
        assert not await su.fetchval(
            "select has_function_privilege($1, $2, 'execute')", role, fn
        ), f"{role} can map phone numbers to tenants"


async def test_a_whatsapp_message_id_is_unique_per_tenant(
    su: asyncpg.Connection, seeded: None
) -> None:
    """History import and a live webhook can deliver the same id through two paths."""
    conversation = await _conversation(su, TENANT_A)
    contact = await su.fetchval("select contact_id from conversations where id = $1", conversation)
    other = await su.fetchval(
        """insert into conversations (tenant_id, contact_id, surface)
           values ($1, $2, 'whatsapp') returning id""",
        TENANT_A,
        contact,
    )
    insert = """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                      external_id)
                values ($1, $2, 'in', 'customer', 'customer', 'wamid.same')"""
    await su.execute(insert, TENANT_A, conversation)
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(insert, TENANT_A, other)
    await su.execute(insert, TENANT_B, await _conversation(su, TENANT_B))


async def test_an_idempotency_key_creates_one_message(su: asyncpg.Connection, seeded: None) -> None:
    conversation = await _conversation(su, TENANT_A)
    insert = """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                      status, idempotency_key)
                values ($1, $2, 'out', 'human', 'inbox', 'queued', 'key-1')"""
    await su.execute(insert, TENANT_A, conversation)
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(insert, TENANT_A, conversation)


async def test_sending_is_a_status(su: asyncpg.Connection, seeded: None) -> None:
    await su.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, status)
           values ($1, $2, 'out', 'human', 'inbox', 'sending')""",
        TENANT_A,
        await _conversation(su, TENANT_A),
    )


async def test_every_message_says_where_it_came_from(su: asyncpg.Connection, seeded: None) -> None:
    with pytest.raises(asyncpg.NotNullViolationError):
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender)
               values ($1, $2, 'in', 'customer')""",
            TENANT_A,
            await _conversation(su, TENANT_A),
        )


async def test_errors_are_structured(su: asyncpg.Connection, seeded: None) -> None:
    error = {"code": "131047", "message": "Re-engagement message"}
    message_id = await su.fetchval(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, status,
                                 error)
           values ($1, $2, 'out', 'human', 'inbox', 'failed', $3::jsonb) returning id""",
        TENANT_A,
        await _conversation(su, TENANT_A),
        '{"code": "131047", "message": "Re-engagement message"}',
    )
    stored = await su.fetchval("select error::text from messages where id = $1", message_id)
    assert stored is not None and "131047" in stored and error["message"] in stored
