"""A task falling due: booked by the task itself, told to its assignee once."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import asyncpg

from conftest import SALES_1, TENANT_A, reseed_with_people
from dealerai.events.bus import Event
from dealerai.events.handlers import crm


async def _task(
    su: asyncpg.Connection,
    *,
    due_in: timedelta = timedelta(hours=1),
    status: str = "open",
    source: str = "human",
) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        """insert into tasks (tenant_id, title, due_at, status, source, assignee_id, created_by)
           values ($1, 'Call Omar', now() + $2::interval, $3, $4, $5, $5) returning id""",
        TENANT_A,
        due_in,
        status,
        source,
        SALES_1,
    )


async def _booked(su: asyncpg.Connection, task: uuid.UUID) -> list[Event]:
    """The checks a task booked for itself, as the worker would claim them."""
    rows = await su.fetch(
        """select id, tenant_id, event_type, payload, dedupe_key from events
            where event_type = 'task.due_check' and payload->>'task_id' = $1 order by id""",
        str(task),
    )
    return [
        Event(
            id=r["id"],
            tenant_id=r["tenant_id"],
            event_type=r["event_type"],
            payload=json.loads(r["payload"]),
            attempts=1,
            dedupe_key=r["dedupe_key"],
        )
        for r in rows
    ]


async def test_a_task_books_a_check_at_its_due_time(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    assert len(await _booked(su, task)) == 1
    assert await su.fetchval(
        """select e.run_after = t.due_at and e.status = 'pending' and e.tenant_id = t.tenant_id
             from events e join tasks t on t.id = $1
            where e.event_type = 'task.due_check'""",
        task,
    )


async def test_moving_a_task_books_the_new_time(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    await su.execute("update tasks set due_at = due_at + interval '1 day' where id = $1", task)
    assert len(await _booked(su, task)) == 2


async def test_renaming_a_task_books_nothing_new(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    await su.execute("update tasks set title = 'Call Omar today' where id = $1", task)
    assert len(await _booked(su, task)) == 1


async def test_a_task_that_is_done_or_the_ais_books_nothing(
    db: None, su: asyncpg.Connection
) -> None:
    await reseed_with_people()
    assert await _booked(su, await _task(su, status="done")) == []
    # An AI follow-up is due at once and already announces itself (followup_ready).
    assert await _booked(su, await _task(su, source="ai")) == []


async def test_a_task_falling_due_is_a_kind_of_notification(
    db: None, su: asyncpg.Connection
) -> None:
    await reseed_with_people()
    await su.execute(
        """insert into notifications (tenant_id, user_id, kind, title)
           values ($1, $2, 'task_due', 'Call Omar')""",
        TENANT_A,
        SALES_1,
    )


# --------------------------------------------------------------------------
# the check, when its time comes — each handed the event the trigger really
# booked, so the payload's shape is the database's and not the test's
# --------------------------------------------------------------------------


async def _told(su: asyncpg.Connection) -> list[asyncpg.Record]:
    return await su.fetch(  # type: ignore[no-any-return]
        "select user_id, kind, title, body, href from notifications where kind = 'task_due'"
    )


async def test_the_assignee_is_told_once(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    contact = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Omar Haddad') returning id",
        TENANT_A,
    )
    await su.execute("update tasks set contact_id = $2 where id = $1", task, contact)
    [event] = await _booked(su, task)

    await crm.on_task_due(event)
    await crm.on_task_due(event)  # the queue retries

    [told] = await _told(su)
    assert told["user_id"] == SALES_1
    assert (told["title"], told["body"], told["href"]) == (
        "Due now: Call Omar",
        "Omar Haddad",
        "/tasks",
    )


async def test_a_task_done_by_then_tells_nobody(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    [event] = await _booked(su, task)
    await su.execute("update tasks set status = 'done' where id = $1", task)

    await crm.on_task_due(event)

    assert await _told(su) == []


async def test_a_task_moved_by_then_waits_for_its_new_time(
    db: None, su: asyncpg.Connection
) -> None:
    await reseed_with_people()
    task = await _task(su)
    await su.execute("update tasks set due_at = due_at + interval '1 day' where id = $1", task)
    old, new = await _booked(su, task)

    await crm.on_task_due(old)
    assert await _told(su) == []

    await crm.on_task_due(new)
    assert len(await _told(su)) == 1


async def test_a_task_deleted_by_then_is_not_an_error(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    [event] = await _booked(su, task)
    await su.execute("delete from tasks where id = $1", task)

    await crm.on_task_due(event)

    assert await _told(su) == []
