"""What 0010_sales_copilot.sql must be true about: one live draft, and who hears about it."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B, USER_A
from dealerai.db.session import tenant_session


async def _conversation(su: asyncpg.Connection, tenant_id: uuid.UUID = TENANT_A) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        "select id from conversations where tenant_id = $1", tenant_id
    )


async def _suggest(
    su: asyncpg.Connection,
    conversation_id: uuid.UUID,
    status: str,
    tenant_id: uuid.UUID = TENANT_A,
) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        """insert into ai_suggestions (tenant_id, conversation_id, status, text)
           values ($1, $2, $3, 'Hello') returning id""",
        tenant_id,
        conversation_id,
        status,
    )


def _collector(queue: asyncio.Queue[str]) -> Callable[..., None]:
    """A named callback, so remove_listener can actually remove it."""

    def listener(*args: object) -> None:
        queue.put_nowait(str(args[-1]))

    return listener


async def test_a_conversation_has_at_most_one_live_draft(
    su: asyncpg.Connection, seeded: None
) -> None:
    """Two drafts on screen at once is a salesperson sending the older one."""
    conversation_id = await _conversation(su)
    await _suggest(su, conversation_id, "ready")
    with pytest.raises(asyncpg.UniqueViolationError):
        await _suggest(su, conversation_id, "generating")


async def test_a_superseded_draft_makes_room_for_the_next(
    su: asyncpg.Connection, seeded: None
) -> None:
    conversation_id = await _conversation(su)
    first = await _suggest(su, conversation_id, "ready")
    await su.execute("update ai_suggestions set status = 'superseded' where id = $1", first)
    await _suggest(su, conversation_id, "generating")  # no error


async def test_a_blocked_draft_is_not_live_either(su: asyncpg.Connection, seeded: None) -> None:
    """Blocked is a finished outcome: the composer shows one muted line, and the
    next customer message must still be able to start a new draft."""
    conversation_id = await _conversation(su)
    await _suggest(su, conversation_id, "blocked")
    await _suggest(su, conversation_id, "ready")  # no error


async def test_the_history_outlives_the_message_it_answered(
    su: asyncpg.Connection, seeded: None
) -> None:
    """Retention purges messages after 24 months and acceptance is kept for 12.
    A cascade here would delete the metric early, and silently."""
    conversation_id = await _conversation(su)
    message_id = await su.fetchval(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
           values ($1, $2, 'in', 'customer', 'customer', 'how much?') returning id""",
        TENANT_A,
        conversation_id,
    )
    suggestion_id = await su.fetchval(
        """insert into ai_suggestions (tenant_id, conversation_id, for_message_id, status, text)
           values ($1, $2, $3, 'ready', 'AED 235,000') returning id""",
        TENANT_A,
        conversation_id,
        message_id,
    )
    await su.execute("delete from messages where id = $1", message_id)
    row = await su.fetchrow(
        "select for_message_id, text from ai_suggestions where id = $1", suggestion_id
    )
    assert row is not None
    assert row["for_message_id"] is None
    assert row["text"] == "AED 235,000"


async def test_a_draft_is_invisible_across_tenants(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    conversation_id = await _conversation(su, TENANT_B)
    await _suggest(su, conversation_id, "ready", tenant_id=TENANT_B)
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select count(*) from ai_suggestions") == 0


async def test_a_draft_reaches_the_person_holding_the_conversation(
    su: asyncpg.Connection, seeded: None
) -> None:
    """A suggestion carries its conversation's visibility, exactly as a message
    does.

    Without it the payload has no owner_id, no assigned_to and no team_id, and
    realtime.py's filter reads that as "nobody with a scope may see this" — so
    the draft would stream to owners, admins and viewers and never to the
    salesperson it was written for.
    """
    conversation_id = await _conversation(su)
    await su.execute(
        "update conversations set owner_id = $2, assigned_to = $2 where id = $1",
        conversation_id,
        USER_A,
    )
    queue: asyncio.Queue[str] = asyncio.Queue()
    listener = _collector(queue)
    await su.add_listener("rt", listener)
    try:
        suggestion_id = await _suggest(su, conversation_id, "ready")
        payload = json.loads(await asyncio.wait_for(queue.get(), timeout=5))
    finally:
        await su.remove_listener("rt", listener)

    assert payload["type"] == "suggestion.ready"
    assert payload["id"] == str(suggestion_id)
    assert payload["conversation_id"] == str(conversation_id)
    assert payload["owner_id"] == str(USER_A)
    assert payload["assigned_to"] == str(USER_A)


async def test_a_chunk_holds_the_vector_the_embedder_produces(su: asyncpg.Connection) -> None:
    """The dimension is free to change while the table is empty and expensive
    afterwards, so it is asserted rather than assumed."""
    dimensions = await su.fetchval(
        """select atttypmod from pg_attribute
            where attrelid = 'doc_chunks'::regclass and attname = 'embedding'"""
    )
    from dealerai.ai.models import EMBEDDING_DIMENSIONS

    assert dimensions == EMBEDDING_DIMENSIONS
