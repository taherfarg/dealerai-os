"""Routing a waiting customer to a person, and never to two people at once."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from conftest import MANAGER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.events.bus import Event
from dealerai.events.handlers import inbox
from dealerai.sales.assignment import Candidate, choose

NOW = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
CHANNEL = uuid.UUID("cccccccc-3333-4333-8333-000000000001")
LOCAL_TEAM = {MANAGER, SALES_1, SALES_2}


# --------------------------------------------------------------------------
# the rule, with no database
# --------------------------------------------------------------------------


def _candidate(user_id: uuid.UUID, **overrides: object) -> Candidate:
    base: dict[str, object] = {
        "user_id": user_id,
        "languages": ("ar", "en"),
        "accepting_chats": True,
        "open_conversations": 0,
        "max_open_conversations": None,
        "last_assigned_at": None,
    }
    base.update(overrides)
    return Candidate(**base)  # type: ignore[arg-type]


def test_the_least_recently_assigned_person_takes_it() -> None:
    busy = _candidate(SALES_1, last_assigned_at=NOW)
    free = _candidate(SALES_2, last_assigned_at=NOW - timedelta(hours=2))
    assert choose([busy, free], language=None) == SALES_2


def test_someone_who_has_never_been_assigned_goes_first() -> None:
    never = _candidate(SALES_2)
    assert choose([_candidate(SALES_1, last_assigned_at=NOW), never], language=None) == SALES_2


def test_a_shared_language_wins_over_the_rotation() -> None:
    """A French customer reaching an Arabic-only rep is a worse start than
    waiting one place longer in the queue."""
    arabic_only = _candidate(SALES_1, languages=("ar",))
    french = _candidate(SALES_2, languages=("fr", "en"), last_assigned_at=NOW)
    assert choose([arabic_only, french], language="fr") == SALES_2


def test_nobody_available_is_an_answer() -> None:
    away = _candidate(SALES_1, accepting_chats=False)
    full = _candidate(SALES_2, open_conversations=8, max_open_conversations=8)
    assert choose([away, full], language=None) is None


# --------------------------------------------------------------------------
# the handler, with one
# --------------------------------------------------------------------------


async def _waiting_conversation(
    su: asyncpg.Connection,
    *,
    owner: uuid.UUID | None = None,
    language: str = "ar",
    team: uuid.UUID | None = TEAM_LOCAL,
) -> uuid.UUID:
    contact_id = await su.fetchval(
        """insert into contacts (tenant_id, full_name, locale, country, owner_id, team_id)
           values ($1, 'Karim', $2, 'AE', $3, $4) returning id""",
        TENANT_A,
        language,
        owner,
        team,
    )
    return await su.fetchval(  # type: ignore[no-any-return]
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, team_id, owner_id, waiting_since)
           values ($1, $2, $3, 'whatsapp', $4, $5, now()) returning id""",
        TENANT_A,
        contact_id,
        CHANNEL,
        team,
        owner,
    )


def _event(conversation_id: uuid.UUID) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="conversation.assign_requested",
        payload={"conversation_id": str(conversation_id)},
        attempts=1,
        dedupe_key=f"assign:{conversation_id}",
    )


@pytest.fixture
async def workspace(su: asyncpg.Connection) -> asyncpg.Connection:
    """Two salespeople and a manager in the Local team, all taking chats."""
    await reseed_with_people()
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode, status)
           values ($1, $2, 'whatsapp', 'assign-phone', 'assign-waba', 'cloud_api', 'connected')""",
        CHANNEL,
        TENANT_A,
    )
    return su


async def test_the_handler_assigns_and_says_so(db: None, workspace: asyncpg.Connection) -> None:
    su = workspace
    conversation_id = await _waiting_conversation(su)

    await inbox.on_assign_requested(_event(conversation_id))

    row = await su.fetchrow(
        "select assigned_to, owner_id from conversations where id = $1", conversation_id
    )
    assert row is not None and row["assigned_to"] in LOCAL_TEAM
    assert row["owner_id"] == row["assigned_to"], "the customer's owner follows the assignment"
    event_line = await su.fetchval(
        "select event from messages where conversation_id = $1 and kind = 'event'", conversation_id
    )
    assert event_line is not None
    assert (
        await su.fetchval(
            "select count(*) from notifications where kind = 'assigned' and user_id = $1",
            row["assigned_to"],
        )
        == 1
    )


async def test_the_routed_team_is_kept_when_somebody_takes_it(
    db: None, workspace: asyncpg.Connection
) -> None:
    """A new customer arrives with no team. Routed and assigned in one go, the
    conversation kept only its assignee: it was missing from the manager's Team
    inbox and the dashboard's waiting list while the dashboard's tile counted it."""
    su = workspace
    await su.execute(
        """update tenants set sales_settings = coalesce(sales_settings, '{}'::jsonb)
             || jsonb_build_object('default_team_id', $2::uuid) where id = $1""",
        TENANT_A,
        TEAM_LOCAL,
    )
    conversation_id = await _waiting_conversation(su, team=None)

    await inbox.on_assign_requested(_event(conversation_id))

    row = await su.fetchrow(
        """select cv.assigned_to, cv.team_id, ct.team_id as customer_team
             from conversations cv join contacts ct on ct.id = cv.contact_id
            where cv.id = $1""",
        conversation_id,
    )
    assert row is not None and row["assigned_to"] in LOCAL_TEAM
    assert (row["team_id"], row["customer_team"]) == (TEAM_LOCAL, TEAM_LOCAL)


async def test_two_conversations_do_not_land_on_one_person(
    db: None, workspace: asyncpg.Connection
) -> None:
    """Both reps are free; the rotation must hand out one each."""
    su = workspace
    first = await _waiting_conversation(su)
    second = await _waiting_conversation(su)

    await asyncio.gather(
        inbox.on_assign_requested(_event(first)),
        inbox.on_assign_requested(_event(second)),
    )

    assigned = [
        row["assigned_to"]
        for row in await su.fetch(
            "select assigned_to from conversations where id = any($1::uuid[])", [first, second]
        )
    ]
    assert None not in assigned, f"a conversation was left unassigned: {assigned}"
    assert len(set(assigned)) == 2, f"both went to the same person: {assigned}"


async def test_a_customer_who_already_has_a_rep_stays_with_them(
    db: None, workspace: asyncpg.Connection
) -> None:
    conversation_id = await _waiting_conversation(workspace, owner=SALES_2)
    await inbox.on_assign_requested(_event(conversation_id))
    assert (
        await workspace.fetchval(
            "select assigned_to from conversations where id = $1", conversation_id
        )
        == SALES_2
    )


async def test_a_rep_who_is_away_does_not_get_their_own_customer(
    db: None, workspace: asyncpg.Connection
) -> None:
    """Their customer still gets an answer from someone else."""
    su = workspace
    await su.execute("update memberships set accepting_chats = false where user_id = $1", SALES_2)
    conversation_id = await _waiting_conversation(su, owner=SALES_2)

    await inbox.on_assign_requested(_event(conversation_id))

    assigned = await su.fetchval(
        "select assigned_to from conversations where id = $1", conversation_id
    )
    assert assigned is not None and assigned != SALES_2


async def test_nobody_available_leaves_it_in_the_queue_and_tries_again(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    await su.execute(
        "update memberships set accepting_chats = false where tenant_id = $1", TENANT_A
    )
    conversation_id = await _waiting_conversation(su)

    await inbox.on_assign_requested(_event(conversation_id))

    assert (
        await su.fetchval("select assigned_to from conversations where id = $1", conversation_id)
        is None
    )
    retry = await su.fetchrow(
        """select run_after from events
           where event_type = 'conversation.assign_requested' and status = 'pending'"""
    )
    assert retry is not None and retry["run_after"] > datetime.now(UTC)
    assert await su.fetchval("select count(*) from notifications") == 0
