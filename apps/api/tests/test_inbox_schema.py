"""What 0008_sales_inbox.sql must be true about: reads, notifications, live updates."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable

import asyncpg
import pytest

from conftest import TENANT_A, USER_A
from dealerai.db.session import tenant_session


async def _conversation(su: asyncpg.Connection) -> uuid.UUID:
    return await su.fetchval("select id from conversations where tenant_id = $1", TENANT_A)


def _collector(queue: asyncio.Queue[str]) -> Callable[..., None]:
    """A named callback, so remove_listener can actually remove it."""

    def listener(*args: object) -> None:
        queue.put_nowait(str(args[-1]))

    return listener


async def test_a_read_cursor_is_one_row_per_person(su: asyncpg.Connection, seeded: None) -> None:
    conversation_id = await _conversation(su)
    insert = """insert into conversation_reads (tenant_id, conversation_id, user_id, last_read_at)
                values ($1, $2, $3, now())
                on conflict (conversation_id, user_id)
                  do update set last_read_at = excluded.last_read_at"""
    await su.execute(insert, TENANT_A, conversation_id, USER_A)
    await su.execute(insert, TENANT_A, conversation_id, USER_A)
    assert (
        await su.fetchval(
            "select count(*) from conversation_reads where conversation_id = $1", conversation_id
        )
        == 1
    )


async def test_a_notification_is_delivered_once(su: asyncpg.Connection, seeded: None) -> None:
    """ "This customer is late" must not fire twice for one waiting period.

    The event queue only dedupes events that are still pending, so the row needs
    its own key to survive the first event finishing.
    """
    insert = """insert into notifications (tenant_id, user_id, kind, title, dedupe_key)
                values ($1, $2, 'waiting_missed', 'Karim has been waiting', 'sla:1:missed')
                on conflict do nothing"""
    await su.execute(insert, TENANT_A, USER_A)
    await su.execute(insert, TENANT_A, USER_A)
    assert await su.fetchval("select count(*) from notifications") == 1


async def test_a_notification_belongs_to_one_person(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await su.execute(
        """insert into notifications (tenant_id, user_id, kind, title)
           values ($1, $2, 'assigned', 'For you')""",
        TENANT_A,
        USER_A,
    )
    other = uuid.UUID("eeeeeeee-1111-4000-8000-000000000001")
    await su.execute("delete from auth.users where id = $1", other)
    await su.execute("insert into auth.users (id, email) values ($1, 'other@example.test')", other)
    await su.execute(
        "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'sales')",
        TENANT_A,
        other,
    )
    try:
        async with tenant_session(TENANT_A, user_id=other, scope="own") as conn:
            assert await conn.fetchval("select count(*) from notifications") == 0
        async with tenant_session(TENANT_A, user_id=USER_A, scope="own") as conn:
            assert await conn.fetchval("select count(*) from notifications") == 1
    finally:
        await su.execute("delete from auth.users where id = $1", other)


async def test_a_new_message_announces_itself(su: asyncpg.Connection, seeded: None) -> None:
    """The trigger is what makes a live update impossible to forget."""
    conversation_id = await _conversation(su)
    queue: asyncio.Queue[str] = asyncio.Queue()
    listener = _collector(queue)
    await su.add_listener("rt", listener)
    try:
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
               values ($1, $2, 'in', 'customer', 'customer', 'live update please')""",
            TENANT_A,
            conversation_id,
        )
        payload = json.loads(await asyncio.wait_for(queue.get(), timeout=5))
    finally:
        await su.remove_listener("rt", listener)

    assert payload["type"] == "message.created"
    assert payload["tenant_id"] == str(TENANT_A)
    assert payload["conversation_id"] == str(conversation_id)
    # The message carries its conversation's visibility, so the stream can filter
    # without a query per event.
    assert {"owner_id", "assigned_to", "team_id"} <= set(payload)


async def test_a_bulk_import_can_stay_quiet(su: asyncpg.Connection, seeded: None) -> None:
    """The history import writes thousands of rows; one notification each would
    flood the queue and the browser."""
    conversation_id = await _conversation(su)
    queue: asyncio.Queue[str] = asyncio.Queue()
    listener = _collector(queue)
    await su.add_listener("rt", listener)
    try:
        async with su.transaction():
            await su.execute("select set_config('app.suppress_rt', 'on', true)")
            await su.execute(
                """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                         body)
                   values ($1, $2, 'in', 'customer', 'history', 'imported')""",
                TENANT_A,
                conversation_id,
            )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=1)
    finally:
        await su.remove_listener("rt", listener)


async def test_search_reads_the_transcript_too(su: asyncpg.Connection, seeded: None) -> None:
    """A customer's voice note is searchable by what was said in it."""
    conversation_id = await _conversation(su)
    await su.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, type,
                                 transcript)
           values ($1, $2, 'in', 'customer', 'customer', 'audio',
                   '{"text": "is the land cruiser still available", "language": "en"}'::jsonb)""",
        TENANT_A,
        conversation_id,
    )
    found = await su.fetchval(
        """select count(*) from messages
           where tenant_id = $1
             and to_tsvector('simple', coalesce(body, '') || ' ' ||
                             coalesce(transcript->>'text', '')) @@ plainto_tsquery('simple', $2)""",
        TENANT_A,
        "land cruiser",
    )
    assert found == 1
