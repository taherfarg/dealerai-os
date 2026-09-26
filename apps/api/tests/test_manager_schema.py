"""What 0011_sales_manager.sql must be true about."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, TENANT_B, USER_A, jwt_session
from dealerai.db.session import system_session, tenant_session

NOW = datetime.now(UTC)


async def _conversation_of(su: asyncpg.Connection, name: str) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        """select cv.id from conversations cv join contacts ct on ct.id = cv.contact_id
            where ct.full_name = $1""",
        name,
    )


async def _miss(su: asyncpg.Connection, conversation_id: uuid.UUID, rep: uuid.UUID | None) -> None:
    await su.execute(
        """insert into sla_misses (tenant_id, conversation_id, assigned_to, waiting_since, due_at)
           values ($1, $2, $3, $4, $5)""",
        TENANT_A,
        conversation_id,
        rep,
        NOW - timedelta(minutes=9),
        NOW - timedelta(minutes=4),
    )


async def test_a_miss_is_seen_exactly_when_its_conversation_is(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    mine = await _conversation_of(su, "s1 customer")
    await _miss(su, mine, SALES_1)
    await _miss(su, await _conversation_of(su, "s2 customer"), None)
    async with tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        seen = [row["conversation_id"] for row in await conn.fetch("select * from sla_misses")]
    assert seen == [mine]


async def test_one_wait_is_missed_once(su: asyncpg.Connection, seeded: None) -> None:
    """The check that writes a miss can run twice; the miss cannot exist twice."""
    conversation_id = await su.fetchval(
        "select id from conversations where tenant_id = $1", TENANT_A
    )
    await _miss(su, conversation_id, None)
    with pytest.raises(asyncpg.UniqueViolationError):
        await _miss(su, conversation_id, None)


async def test_a_brief_is_its_readers_alone(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    for reader in (OWNER, MANAGER):
        await su.execute(
            """insert into sales_briefs (tenant_id, user_id, brief_date, facts)
               values ($1, $2, current_date, '{}')""",
            TENANT_A,
            reader,
        )
    async with tenant_session(TENANT_A, user_id=MANAGER, scope="team") as conn:
        assert await conn.fetchval("select array_agg(user_id) from sales_briefs") == [MANAGER]
    async with tenant_session(TENANT_A) as conn:  # the worker writes everybody's
        assert await conn.fetchval("select count(*) from sales_briefs") == 2


@pytest.mark.parametrize("shortcut", ["price", "/Price", "/two words", "/" + "x" * 31, "/"])
async def test_a_shortcut_is_a_slash_and_a_word(
    su: asyncpg.Connection, seeded: None, shortcut: str
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await su.execute(
            """insert into quick_replies (tenant_id, shortcut, title, body)
               values ($1, $2, 'Price', '{"en": "It is"}')""",
            TENANT_A,
            shortcut,
        )


async def test_two_quick_replies_cannot_share_a_shortcut(
    su: asyncpg.Connection, seeded: None
) -> None:
    insert = """insert into quick_replies (tenant_id, shortcut, title, body)
                values ($1, '/price', 'Price', '{"en": "It is"}')"""
    await su.execute(insert, TENANT_A)
    await su.execute(insert, TENANT_B)  # another dealership's /price is theirs
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(insert, TENANT_A)


async def test_a_quick_reply_says_something_in_some_language(
    su: asyncpg.Connection, seeded: None
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await su.execute(
            """insert into quick_replies (tenant_id, shortcut, title, body)
               values ($1, '/empty', 'Empty', '{"de": "Hallo"}')""",
            TENANT_A,
        )


async def _suggestion(
    su: asyncpg.Connection,
    conversation_id: uuid.UUID,
    outcome: str | None,
    ratio: float | None = None,
) -> None:
    await su.execute(
        """insert into ai_suggestions (tenant_id, conversation_id, status, text, intent,
                                       outcome, edit_ratio)
           values ($1, $2, 'superseded', 'Hello', 'price', $3, $4)""",
        TENANT_A,
        conversation_id,
        outcome,
        ratio,
    )


async def test_acceptance_counts_a_light_edit_as_accepted(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    conversation_id = await su.fetchval(
        "select id from conversations where tenant_id = $1", TENANT_A
    )
    for outcome, ratio in (("sent", 0.0), ("edited", 0.1), ("edited", 0.5), ("discarded", None)):
        await _suggestion(su, conversation_id, outcome, ratio)
    await _suggestion(su, conversation_id, None)  # never decided: not in the metric
    async with tenant_session(TENANT_A) as conn:
        row = await conn.fetchrow(
            """select sum(decided) as decided, sum(sent) as sent,
                      sum(lightly_edited) as lightly, sum(rewritten) as rewritten,
                      sum(discarded) as discarded
                 from v_suggestion_acceptance where intent = 'price'"""
        )
    assert dict(row) == {"decided": 4, "sent": 1, "lightly": 1, "rewritten": 1, "discarded": 1}


async def test_acceptance_reads_through_the_callers_visibility(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    await _suggestion(su, await _conversation_of(su, "s1 customer"), "sent")
    await _suggestion(su, await _conversation_of(su, "s2 customer"), "sent")
    async with tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        assert await conn.fetchval("select sum(decided) from v_suggestion_acceptance") == 1


async def test_the_clock_lists_every_active_tenant_and_nothing_more(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await su.execute("update tenants set status = 'paused' where id = $1", TENANT_B)
    async with system_session() as conn:  # no tenant: RLS would otherwise show none
        rows = await conn.fetch("select * from app.tenant_clocks()")
    assert [(row["id"], row["timezone"]) for row in rows] == [(TENANT_A, "Asia/Dubai")]
    assert list(rows[0].keys()) == ["id", "timezone"]


async def test_a_browser_cannot_ask_for_the_clocks(su: asyncpg.Connection, seeded: None) -> None:
    async with jwt_session(su, USER_A) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("select * from app.tenant_clocks()")


async def test_a_brief_is_a_kind_of_notification(su: asyncpg.Connection, seeded: None) -> None:
    await su.execute(
        """insert into notifications (tenant_id, user_id, kind, title, entity)
           values ($1, $2, 'brief_ready', 'Your morning brief', $3::jsonb)""",
        TENANT_A,
        USER_A,
        json.dumps({"type": "brief", "id": str(uuid.uuid4())}),
    )
