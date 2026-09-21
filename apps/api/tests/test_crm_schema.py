"""The shape the CRM reads: pipelines, stages, tasks, and a lead that sits on one."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B, USER_A, USER_B
from dealerai import realtime
from dealerai.db.session import tenant_session
from dealerai.realtime import Subscriber


async def _a_pipeline(conn: asyncpg.Connection, tenant_id: uuid.UUID, name: str) -> uuid.UUID:
    pipeline = await conn.fetchval(
        "insert into pipelines (tenant_id, name) values ($1, $2) returning id", tenant_id, name
    )
    return uuid.UUID(str(pipeline))


async def _a_lead(
    conn: asyncpg.Connection, tenant_id: uuid.UUID, owner: uuid.UUID | None = None
) -> uuid.UUID:
    pipeline = await _a_pipeline(conn, tenant_id, f"Board {uuid.uuid4().hex[:6]}")
    stage = await conn.fetchval(
        """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
           values ($1, $2, 'New', 0, 'open') returning id""",
        tenant_id,
        pipeline,
    )
    contact = await conn.fetchval("select id from contacts where tenant_id = $1 limit 1", tenant_id)
    lead = await conn.fetchval(
        """insert into leads (tenant_id, contact_id, pipeline_id, stage_id, owner_id)
           values ($1, $2, $3, $4, $5) returning id""",
        tenant_id,
        contact,
        pipeline,
        stage,
        owner,
    )
    return uuid.UUID(str(lead))


async def test_a_pipeline_has_exactly_one_won_stage(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    pipeline = await _a_pipeline(su, TENANT_A, "Export")
    await su.execute(
        """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
           values ($1, $2, 'Won', 0, 'won')""",
        TENANT_A,
        pipeline,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(
            """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
               values ($1, $2, 'Also won', 1, 'won')""",
            TENANT_A,
            pipeline,
        )


async def test_a_task_is_always_somebody_s(db: None, su: asyncpg.Connection, seeded: None) -> None:
    with pytest.raises(asyncpg.NotNullViolationError):
        await su.execute(
            """insert into tasks (tenant_id, title, due_at, assignee_id)
               values ($1, 'Call Omar', now(), null)""",
            TENANT_A,
        )


async def test_a_salesperson_sees_their_own_tasks_and_not_a_colleague_s(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    for user in (USER_A, USER_B):
        await su.execute(
            """insert into tasks (tenant_id, title, due_at, assignee_id)
               values ($1, 'Call back', now(), $2)""",
            TENANT_A,
            user,
        )
    async with tenant_session(TENANT_A, user_id=USER_A, scope="own") as conn:
        assert await conn.fetchval("select count(*) from tasks") == 1
    # The worker has no user in its session and writes tasks for other people.
    async with tenant_session(TENANT_A, scope="all") as conn:
        assert await conn.fetchval("select count(*) from tasks") == 2


async def test_another_tenant_s_pipeline_is_not_there(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _a_pipeline(su, TENANT_B, "Theirs")
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select count(*) from pipelines where name = 'Theirs'") == 0


async def test_a_lead_move_reaches_the_stream(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """The trigger reads the lead's own owner, because a lead has no conversation.

    The unit tests in test_realtime.py know nothing about whether the trigger
    fires or what it names its event, which is exactly what a migration breaks.
    """
    lead = await _a_lead(su, TENANT_A, owner=USER_A)
    stop = asyncio.Event()
    listener = asyncio.create_task(realtime.listen(stop))
    subscriber = realtime.hub.subscribe(
        Subscriber(
            tenant_id=TENANT_A,
            user_id=USER_A,
            scope="own",
            visible_owner_ids={USER_A},
            team_ids=set(),
        )
    )
    try:
        await asyncio.sleep(0.2)  # let the listener attach before writing
        await su.execute("update leads set score = 80 where id = $1", lead)
        event = json.loads(await asyncio.wait_for(subscriber.queue.get(), timeout=5))
    finally:
        realtime.hub.unsubscribe(subscriber)
        stop.set()
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener

    assert event["type"] == "lead.updated"
    assert event["id"] == str(lead)
    assert event["owner_id"] == str(USER_A)
