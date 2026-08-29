from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.db.session import system_session, tenant_session
from dealerai.events import bus
from dealerai.events.bus import Event, emit
from dealerai.events.worker import Worker


@pytest.fixture(autouse=True)
def clean_handlers() -> Iterator[None]:
    """Handlers are a module-level registry; keep tests from leaking into each other."""
    saved = dict(bus._HANDLERS)
    bus._HANDLERS.clear()
    yield
    bus._HANDLERS.clear()
    bus._HANDLERS.update(saved)


@pytest.fixture
async def clean_events(su: asyncpg.Connection) -> AsyncIterator[None]:
    await su.execute("delete from events")
    yield
    await su.execute("delete from events")


async def _row(event_id: int) -> Any:
    async with system_session() as conn:
        return await conn.fetchrow("select * from events where id = $1", event_id)


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------


async def test_emit_is_transactional_with_its_cause(
    db: None, seeded: None, clean_events: None, su: asyncpg.Connection
) -> None:
    """An event emitted inside a transaction that rolls back must not survive.

    This is why emit() takes the caller's connection instead of opening its own:
    otherwise the queue ends up with a job for a vehicle that was never created.
    """
    with pytest.raises(RuntimeError):
        async with tenant_session(TENANT_A) as conn:
            await emit(conn, "test.rollback", {"a": 1}, tenant_id=TENANT_A)
            raise RuntimeError("boom")

    assert await su.fetchval("select count(*) from events where event_type='test.rollback'") == 0


async def test_emit_dedupes_pending_events(db: None, seeded: None, clean_events: None) -> None:
    async with tenant_session(TENANT_A) as conn:
        first = await emit(conn, "test.dedupe", tenant_id=TENANT_A, dedupe_key="msg-1")
        second = await emit(conn, "test.dedupe", tenant_id=TENANT_A, dedupe_key="msg-1")
    assert first is not None
    assert second is None, "duplicate webhook delivery created a second event"


async def test_emit_payload_round_trips_as_a_dict(
    db: None, seeded: None, clean_events: None
) -> None:
    async with tenant_session(TENANT_A) as conn:
        event_id = await emit(conn, "test.payload", {"nested": {"n": 1}}, tenant_id=TENANT_A)
    assert event_id is not None
    row = await _row(event_id)
    assert row["payload"] == {"nested": {"n": 1}}


# --------------------------------------------------------------------------
# claim + dispatch
# --------------------------------------------------------------------------


async def test_concurrent_workers_handle_each_event_exactly_once(
    db: None, seeded: None, clean_events: None
) -> None:
    handled: list[int] = []

    @bus.handler("test.once")
    async def _h(event: Event) -> None:
        # Yield control so the workers genuinely interleave.
        await asyncio.sleep(0)
        handled.append(event.id)

    async with tenant_session(TENANT_A) as conn:
        for i in range(100):
            await emit(conn, "test.once", {"i": i}, tenant_id=TENANT_A)

    workers = [Worker(f"w{i}", batch_size=7) for i in range(3)]

    async def drain(w: Worker) -> None:
        while await w.run_once():
            pass

    await asyncio.gather(*(drain(w) for w in workers))

    assert len(handled) == 100
    assert len(set(handled)) == 100, "an event was handled twice"

    async with system_session() as conn:
        pending = await conn.fetchval(
            "select count(*) from events where event_type='test.once' and status <> 'done'"
        )
    assert pending == 0


async def test_handler_receives_tenant_and_payload(
    db: None, seeded: None, clean_events: None
) -> None:
    seen: list[Event] = []

    @bus.handler("test.ctx")
    async def _h(event: Event) -> None:
        seen.append(event)

    async with tenant_session(TENANT_A) as conn:
        await emit(conn, "test.ctx", {"vehicle": "abc"}, tenant_id=TENANT_A)

    await Worker("w").run_once()

    assert len(seen) == 1
    assert seen[0].tenant_id == TENANT_A
    assert seen[0].payload == {"vehicle": "abc"}
    assert seen[0].attempts == 1


async def test_priority_is_respected(db: None, seeded: None, clean_events: None) -> None:
    order: list[str] = []

    @bus.handler("test.prio")
    async def _h(event: Event) -> None:
        order.append(event.payload["label"])

    async with tenant_session(TENANT_A) as conn:
        await emit(conn, "test.prio", {"label": "low"}, tenant_id=TENANT_A, priority=0)
        await emit(conn, "test.prio", {"label": "high"}, tenant_id=TENANT_A, priority=10)

    await Worker("w").run_once()
    assert order == ["high", "low"]


async def test_future_events_are_not_claimed(db: None, seeded: None, clean_events: None) -> None:
    @bus.handler("test.later")
    async def _h(event: Event) -> None:  # pragma: no cover - must not run
        raise AssertionError("a scheduled event ran early")

    async with tenant_session(TENANT_A) as conn:
        await emit(
            conn,
            "test.later",
            tenant_id=TENANT_A,
            run_after=datetime.now(UTC) + timedelta(hours=1),
        )

    assert await Worker("w").run_once() == 0


# --------------------------------------------------------------------------
# failure handling
# --------------------------------------------------------------------------


async def test_failures_back_off_then_dead_letter(
    db: None, seeded: None, clean_events: None
) -> None:
    @bus.handler("test.boom")
    async def _h(event: Event) -> None:
        raise ValueError("handler exploded")

    async with tenant_session(TENANT_A) as conn:
        event_id = await emit(conn, "test.boom", tenant_id=TENANT_A)
    assert event_id is not None

    worker = Worker("w")
    delays: list[float] = []

    # max_attempts defaults to 5, so the 5th failure is terminal.
    for attempt in range(1, 6):
        async with system_session() as conn:
            await conn.execute("update events set run_after = now() where id = $1", event_id)

        assert await worker.run_once() == 1
        row = await _row(event_id)
        assert row["attempts"] == attempt
        assert "handler exploded" in row["error"]

        if attempt < 5:
            assert row["status"] == "pending"
            assert row["dead_letter"] is False
            delays.append((row["run_after"] - datetime.now(UTC)).total_seconds())
        else:
            assert row["status"] == "failed"
            assert row["dead_letter"] is True

    assert delays == sorted(delays), f"backoff did not grow: {delays}"
    assert delays[-1] > delays[0] * 2


async def test_unknown_event_type_retries_rather_than_vanishing(
    db: None, seeded: None, clean_events: None
) -> None:
    """A rolling deploy can briefly leave an old worker without a new handler.
    Dropping the event would lose customer messages; retrying rides it out."""
    async with tenant_session(TENANT_A) as conn:
        event_id = await emit(conn, "test.nobody_handles_this", tenant_id=TENANT_A)
    assert event_id is not None

    assert await Worker("w").run_once() == 1
    row = await _row(event_id)
    assert row["status"] == "pending"
    assert "UnknownEventType" in row["error"]


async def test_one_bad_event_does_not_stop_the_batch(
    db: None, seeded: None, clean_events: None
) -> None:
    done: list[int] = []

    @bus.handler("test.mixed")
    async def _h(event: Event) -> None:
        if event.payload["i"] == 1:
            raise ValueError("only this one")
        done.append(event.payload["i"])

    async with tenant_session(TENANT_A) as conn:
        for i in range(3):
            await emit(conn, "test.mixed", {"i": i}, tenant_id=TENANT_A)

    await Worker("w").run_once()
    assert sorted(done) == [0, 2]


# --------------------------------------------------------------------------
# reaper
# --------------------------------------------------------------------------


async def test_reaper_releases_events_from_a_dead_worker(
    db: None, seeded: None, clean_events: None
) -> None:
    handled: list[int] = []

    @bus.handler("test.stuck")
    async def _h(event: Event) -> None:
        handled.append(event.id)

    async with tenant_session(TENANT_A) as conn:
        event_id = await emit(conn, "test.stuck", tenant_id=TENANT_A)
    assert event_id is not None

    # Simulate a worker that claimed the event and then died.
    async with system_session() as conn:
        await conn.execute(
            """update events set status='processing', locked_at = now() - interval '30 minutes',
                                 locked_by='ghost', attempts = 1
               where id = $1""",
            event_id,
        )

    worker = Worker("w", lock_timeout_minutes=15)
    assert await worker.run_once() == 0, "a locked event should not be claimable"

    assert await worker.reap() == [event_id]
    assert await worker.run_once() == 1
    assert handled == [event_id]


async def test_reaper_leaves_fresh_locks_alone(db: None, seeded: None, clean_events: None) -> None:
    async with tenant_session(TENANT_A) as conn:
        event_id = await emit(conn, "test.fresh", tenant_id=TENANT_A)

    async with system_session() as conn:
        await conn.execute(
            "update events set status='processing', locked_at=now(), locked_by='alive' "
            "where id = $1",
            event_id,
        )

    assert await Worker("w", lock_timeout_minutes=15).reap() == []


async def test_priority_decides_what_gets_claimed_under_backlog(
    db: None, seeded: None, clean_events: None
) -> None:
    """The case that actually matters: more work queued than one batch can hold."""

    @bus.handler("test.backlog")
    async def _h(event: Event) -> None:
        pass

    async with tenant_session(TENANT_A) as conn:
        for i in range(5):
            await emit(conn, "test.backlog", {"i": i}, tenant_id=TENANT_A, priority=0)
        await emit(conn, "test.backlog", {"i": 99}, tenant_id=TENANT_A, priority=10)

    claimed = await Worker("w", batch_size=1).claim()
    assert [e.payload["i"] for e in claimed] == [99]
