"""Follow-ups, where the hard part is deciding not to write.

Most of these are about producing nothing: six eligibility rules before any
model call, an agent allowed to say no, and guards on what it does write.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.agents.sales import followup as followup_agent
from dealerai.agents.sales.followup import Considered, Written
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.events.bus import Event
from dealerai.events.handlers import copilot
from dealerai.main import app
from dealerai.sales import followups
from dealerai.sales.settings import SalesSettings

NOW = datetime.now(UTC)
SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
PRICE = 12800000  # AED 128,000
REASON = "BYD Seal 05 dropped AED 4,000 since they asked"
DRAFT = "The Hilux you asked about is now AED 128,000. Shall I hold it for you?"


# ---------------------------------------------------------------------------
# The rules, as pure functions
# ---------------------------------------------------------------------------


def _lead(**over: Any) -> dict[str, Any]:
    return {
        "consent": {},
        "ai_followups": 0,
        "last_followup_at": None,
        "vehicle_status": "available",
        "open_ai_task": False,
        "lead_created_at": NOW - timedelta(days=30),
        **over,
    }


def _verdict(lead: dict[str, Any], *, trigger: str = "no_reply_48h", **over: Any) -> Any:
    settings = SalesSettings.model_validate(over.pop("settings", {}))
    return followups.may_follow_up(
        lead,
        trigger=trigger,
        now=over.pop("now", NOW),
        settings=settings,
        tz=ZoneInfo("Asia/Dubai"),
    )


def test_a_lead_with_nothing_against_it_may_be_followed_up() -> None:
    assert _verdict(_lead()).allowed


def test_a_customer_who_opted_out_is_never_written_to() -> None:
    verdict = _verdict(_lead(consent={"opted_out_at": "2026-09-01"}))
    assert not verdict.allowed and "not to be messaged" in verdict.because


def test_three_is_the_end_of_it() -> None:
    """After the last one the `silent` signal carries the lead to cold on its
    own, which is the ending — not a fourth message."""
    verdict = _verdict(_lead(ai_followups=3, last_followup_at=NOW - timedelta(days=60)))
    assert not verdict.allowed and "already been sent" in verdict.because


def test_the_cadence_list_is_the_cap() -> None:
    """A dealership that shortens the schedule gets fewer follow-ups, which is
    what shortening it means."""
    settings = {"follow_up_cadence_days": [2, 5]}
    assert followups.cap(SalesSettings.model_validate(settings)) == 2
    assert not _verdict(
        _lead(ai_followups=2, last_followup_at=NOW - timedelta(days=90)), settings=settings
    ).allowed


def test_a_car_that_has_sold_stops_its_own_alert() -> None:
    verdict = _verdict(_lead(vehicle_status="sold"), trigger="price_drop")
    assert not verdict.allowed and "no longer available" in verdict.because


def test_a_sold_car_does_not_stop_a_reply_chase() -> None:
    """`no_reply_48h` is about the conversation, not the car."""
    assert _verdict(_lead(vehicle_status="sold"), trigger="no_reply_48h").allowed


def test_one_follow_up_waiting_is_enough() -> None:
    verdict = _verdict(_lead(open_ai_task=True))
    assert not verdict.allowed and "already a follow-up waiting" in verdict.because


def test_the_first_waits_two_days_after_the_lead_appeared() -> None:
    """Every number in [2, 5, 14] is a wait: two days before the first
    follow-up, five before the second, a fortnight before the last."""
    assert _verdict(_lead(lead_created_at=NOW - timedelta(days=3))).allowed

    verdict = _verdict(_lead(lead_created_at=NOW - timedelta(hours=6)))
    assert not verdict.allowed and verdict.because == "too soon by the cadence"


def test_the_second_waits_five_days_and_says_when_to_look_again() -> None:
    sent = NOW - timedelta(hours=1)
    verdict = _verdict(_lead(ai_followups=1, last_followup_at=sent))
    assert not verdict.allowed and verdict.because == "too soon by the cadence"
    assert verdict.retry_at == sent + timedelta(days=5)


def test_the_third_waits_a_fortnight() -> None:
    sent = NOW - timedelta(days=3)
    verdict = _verdict(_lead(ai_followups=2, last_followup_at=sent))
    assert verdict.retry_at == sent + timedelta(days=14)


def test_a_closed_showroom_defers_rather_than_refuses() -> None:
    """A follow-up landing at 02:00 is a number that gets blocked."""
    settings = {"business_hours": {"mon": {"open": "09:00", "close": "18:00"}}}
    monday_dawn = datetime(2026, 9, 21, 1, 0, tzinfo=ZoneInfo("Asia/Dubai"))
    verdict = _verdict(_lead(), settings=settings, now=monday_dawn)
    assert not verdict.allowed and verdict.because == "the showroom is closed"
    assert verdict.retry_at is not None and verdict.retry_at.hour == 9


def test_a_dealership_with_no_hours_is_always_open() -> None:
    assert _verdict(_lead(), now=datetime(2026, 9, 21, 3, 0, tzinfo=UTC)).allowed


# ---------------------------------------------------------------------------
# The handler, with a stubbed agent
# ---------------------------------------------------------------------------


class Agent:
    def __init__(self) -> None:
        self.answer = Written(genuine_reason=True, reason=REASON, draft=DRAFT)
        self.calls = 0

    def says(self, **over: Any) -> None:
        self.answer = Written.model_validate(
            {"genuine_reason": True, "reason": REASON, "draft": DRAFT, **over}
        )


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> Agent:
    stub = Agent()

    async def fake(**kwargs: Any) -> Considered:
        stub.calls += 1
        return Considered(written=stub.answer, cost_usd=0.003)

    monkeypatch.setattr(copilot.followup_agent, "consider", fake)
    return stub


@pytest.fixture
async def lead(su: asyncpg.Connection, seeded: None) -> AsyncIterator[dict[str, Any]]:
    """One open lead on an available car, its conversation last spoken to by us."""
    await su.execute(
        "insert into auth.users (id, email) values ($1, 'ahmed@example.test')"
        " on conflict do nothing",
        SALES_1,
    )
    await su.execute(
        "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'sales')"
        " on conflict do nothing",
        TENANT_A,
        SALES_1,
    )
    await su.execute(
        "insert into teams (id, tenant_id, name) values ($1, $2, 'Local') on conflict do nothing",
        TEAM_LOCAL,
        TENANT_A,
    )
    channel_id = await su.fetchval(
        """insert into channels (tenant_id, platform, external_id, handle, status)
           values ($1, 'whatsapp', $2, '+971 4 123 4567', 'connected') returning id""",
        TENANT_A,
        f"wa-{uuid.uuid4()}",
    )
    contact_id = await su.fetchval(
        """insert into contacts (tenant_id, full_name, country, owner_id, team_id, profile)
           values ($1, 'Karim Benali', 'DZ', $2, $3, $4::jsonb) returning id""",
        TENANT_A,
        SALES_1,
        TEAM_LOCAL,
        json.dumps({"interest": {"value": "Hilux 2.8 Diesel", "source": "ai"}}),
    )
    conversation_id = await su.fetchval(
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, status, owner_id, assigned_to,
              wa_window_expires_at, last_message_at)
           values ($1,$2,$3,'whatsapp','open',$4,$4,$5,$6) returning id""",
        TENANT_A,
        contact_id,
        channel_id,
        SALES_1,
        NOW + timedelta(hours=10),
        NOW - timedelta(days=3),
    )
    for minutes, direction, body in (
        (4400, "in", "how much is the Hilux?"),
        (4300, "out", "AED 132,000."),
    ):
        await su.execute(
            """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                     type, body, created_at)
               values ($1,$2,'message',$3,$4,$5,'text',$6,$7)""",
            TENANT_A,
            conversation_id,
            direction,
            "customer" if direction == "in" else "human",
            "customer" if direction == "in" else "inbox",
            body,
            NOW - timedelta(minutes=minutes),
        )
    vehicle_id = await su.fetchval(
        """insert into vehicles (tenant_id, make, model, model_year, price_minor, status)
           values ($1, 'Toyota', 'Hilux', 2023, $2, 'available') returning id""",
        TENANT_A,
        PRICE,
    )
    pipeline_id, stage_id = await su.fetchrow(  # type: ignore[misc]
        """select p.id, s.id from pipelines p
             join pipeline_stages s on s.pipeline_id = p.id and s.category = 'open'
            where p.tenant_id = $1 order by p.position, s.position limit 1""",
        TENANT_A,
    )
    lead_id = await su.fetchval(
        """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                              owner_id, vehicle_id, created_at)
           values ($1,$2,$3,$4,$5,$6,$7,$8) returning id""",
        TENANT_A,
        contact_id,
        conversation_id,
        pipeline_id,
        stage_id,
        SALES_1,
        vehicle_id,
        # Three days old: a lead created this morning is not one to chase this
        # afternoon, which is what the first cadence gap says.
        NOW - timedelta(days=3),
    )
    await su.execute(
        """insert into message_templates
             (tenant_id, channel_id, external_id, name, language, category, status, body)
           values ($1,$2,'t1','price_update','en','utility','approved',
                   'Hello {{1}}, the {{2}} is now {{3}}.')""",
        TENANT_A,
        channel_id,
    )
    yield {
        "lead": uuid.UUID(str(lead_id)),
        "contact": uuid.UUID(str(contact_id)),
        "conversation": uuid.UUID(str(conversation_id)),
        "vehicle": uuid.UUID(str(vehicle_id)),
        "channel": uuid.UUID(str(channel_id)),
    }


def _check(lead: dict[str, Any], trigger: str = "no_reply_48h") -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="followup.check",
        payload={"trigger": trigger, "lead_id": str(lead["lead"])},
        attempts=1,
        dedupe_key=None,
    )


async def _tasks(su: asyncpg.Connection, lead_id: uuid.UUID) -> list[asyncpg.Record]:
    return await su.fetch(  # type: ignore[no-any-return]
        """select title, kind, source, status, ai_draft, assignee_id
             from tasks where lead_id = $1""",
        lead_id,
    )


async def test_a_genuine_reason_becomes_a_task_for_the_owner(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await copilot.on_followup_check(_check(lead))

    tasks = await _tasks(su, lead["lead"])
    assert len(tasks) == 1
    assert tasks[0]["title"] == REASON
    assert (tasks[0]["kind"], tasks[0]["source"]) == ("follow_up", "ai")
    assert tasks[0]["assignee_id"] == SALES_1
    assert json.loads(tasks[0]["ai_draft"])["text"] == DRAFT

    told = await su.fetch(
        "select kind, title from notifications where tenant_id = $1 and user_id = $2",
        TENANT_A,
        SALES_1,
    )
    assert [row["kind"] for row in told] == ["followup_ready"]


async def test_nothing_new_to_say_produces_no_task(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    """The whole point. The model said no and nobody is interrupted."""
    agent.answer = Written(genuine_reason=False, reason="", draft="")
    await copilot.on_followup_check(_check(lead))

    assert await _tasks(su, lead["lead"]) == []
    assert await su.fetch("select 1 from notifications where user_id = $1", SALES_1) == []


async def test_yes_with_nothing_to_show_for_it_is_a_no(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise the salesperson gets a task whose title is empty.

    Asserted on the agent rather than the handler, because this is where the
    normalisation lives — the handler's tests stub the agent out."""
    from dealerai.orchestrator.toolloop import Conversation

    async def fake(task: Any, **kwargs: Any) -> Conversation:
        return Conversation(
            text="{}",
            parsed=Written(genuine_reason=True, reason="", draft=""),
            cost_usd=0.001,
        )

    monkeypatch.setattr(followup_agent, "converse", fake)
    considered = await followup_agent.consider(
        tenant_id=TENANT_A, run_id=uuid.uuid4(), trigger="price_drop", context=""
    )
    assert considered.written is not None
    assert considered.written.genuine_reason is False


@pytest.mark.parametrize(
    "arrange,trigger",
    [
        ("opt_out", "no_reply_48h"),
        ("three_already", "no_reply_48h"),
        ("sell_the_car", "price_drop"),
        ("one_waiting", "no_reply_48h"),
        ("closed_lead", "no_reply_48h"),
    ],
)
async def test_reasons_not_to_write_cost_nothing(
    arrange: str,
    trigger: str,
    db: None,
    su: asyncpg.Connection,
    lead: dict[str, Any],
    agent: Agent,
) -> None:
    """All of them checked before the model call, so most "no"s are free."""
    if arrange == "opt_out":
        await su.execute(
            """update contacts set consent = consent || '{"opted_out_at": "2026-09-01"}'::jsonb
                where id = $1""",
            lead["contact"],
        )
    elif arrange == "three_already":
        for _ in range(3):  # long enough ago that the cadence is not the reason
            await su.execute(
                """insert into tasks (tenant_id, title, kind, due_at, assignee_id, lead_id,
                                      source, status, completed_at)
                   values ($1, 'old', 'follow_up', now(), $2, $3, 'ai', 'done', now())""",
                TENANT_A,
                SALES_1,
                lead["lead"],
            )
    elif arrange == "sell_the_car":
        await su.execute("update vehicles set status = 'sold' where id = $1", lead["vehicle"])
    elif arrange == "one_waiting":
        await su.execute(
            """insert into tasks (tenant_id, title, kind, due_at, assignee_id, lead_id,
                                  source, status)
               values ($1, 'waiting', 'follow_up', now(), $2, $3, 'ai', 'open')""",
            TENANT_A,
            SALES_1,
            lead["lead"],
        )
    elif arrange == "closed_lead":
        await su.execute(
            """update leads set stage_id = (
                 select s.id from pipeline_stages s
                  where s.tenant_id = $1 and s.category = 'won' limit 1)
                where id = $2""",
            TENANT_A,
            lead["lead"],
        )

    await copilot.on_followup_check(_check(lead, trigger))
    assert agent.calls == 0
    new = [row for row in await _tasks(su, lead["lead"]) if row["title"] == REASON]
    assert new == []


async def test_too_soon_schedules_another_look_rather_than_forgetting(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await su.execute(
        """insert into tasks (tenant_id, title, kind, due_at, assignee_id, lead_id, source,
                              status, completed_at, created_at)
           values ($1, 'first', 'follow_up', now(), $2, $3, 'ai', 'done', now(), now())""",
        TENANT_A,
        SALES_1,
        lead["lead"],
    )
    await copilot.on_followup_check(_check(lead))

    assert agent.calls == 0
    queued = await su.fetch(
        "select run_after from events where event_type = 'followup.check' and status = 'pending'"
    )
    assert len(queued) == 1
    assert queued[0]["run_after"] > datetime.now(UTC) + timedelta(days=1)


async def test_just_checking_in_never_reaches_a_task(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    """The guard, not the prompt, is what makes this true."""
    agent.says(draft="Hi Karim! Just checking in on your enquiry.")
    await copilot.on_followup_check(_check(lead))
    assert await _tasks(su, lead["lead"]) == []


async def test_a_price_the_car_does_not_have_never_reaches_a_task(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    agent.says(draft="Good news — the Hilux is down to AED 99,000.")
    await copilot.on_followup_check(_check(lead))
    assert await _tasks(su, lead["lead"]) == []


async def test_a_closed_window_sends_a_template_instead(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await su.execute(
        "update conversations set wa_window_expires_at = $2 where id = $1",
        lead["conversation"],
        NOW - timedelta(hours=1),
    )
    await copilot.on_followup_check(_check(lead, "price_drop"))

    draft = json.loads((await _tasks(su, lead["lead"]))[0]["ai_draft"])
    assert draft["template_name"] == "price_update"
    assert draft["text"] is None
    assert draft["variables"] == ["Karim", "Toyota Hilux", "AED 128,000"]


async def test_no_suitable_template_still_leaves_a_task_to_call_them(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    """'Call the customer' is worth more than a message that cannot be sent."""
    await su.execute("delete from message_templates where tenant_id = $1", TENANT_A)
    await su.execute(
        "update conversations set wa_window_expires_at = $2 where id = $1",
        lead["conversation"],
        NOW - timedelta(hours=1),
    )
    await copilot.on_followup_check(_check(lead, "price_drop"))

    draft = json.loads((await _tasks(su, lead["lead"]))[0]["ai_draft"])
    assert draft["text"] is None and "template_id" not in draft
    assert draft["reason"] == REASON


# ---------------------------------------------------------------------------
# The three triggers
# ---------------------------------------------------------------------------


async def test_a_price_drop_reaches_the_customer_who_asked(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await copilot.on_price_changed(
        Event(
            id=1,
            tenant_id=TENANT_A,
            event_type="vehicle.price_changed",
            payload={
                "vehicle_id": str(lead["vehicle"]),
                "before_minor": 13200000,
                "after_minor": PRICE,
            },
            attempts=1,
            dedupe_key=None,
        )
    )
    queued = await su.fetch("select payload from events where event_type = 'followup.check'")
    assert [json.loads(row["payload"])["trigger"] for row in queued] == ["price_drop"]


async def test_a_price_rise_reaches_nobody(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await copilot.on_price_changed(
        Event(
            id=1,
            tenant_id=TENANT_A,
            event_type="vehicle.price_changed",
            payload={
                "vehicle_id": str(lead["vehicle"]),
                "before_minor": PRICE,
                "after_minor": 13200000,
            },
            attempts=1,
            dedupe_key=None,
        )
    )
    assert await su.fetch("select 1 from events where event_type = 'followup.check'") == []


async def test_a_new_arrival_reaches_the_customer_who_wanted_one(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    """A lead with no car, whose profile names what has just arrived."""
    await su.execute("update leads set vehicle_id = null where id = $1", lead["lead"])
    arrival = await su.fetchval(
        """insert into vehicles (tenant_id, make, model, model_year, price_minor, status)
           values ($1, 'Toyota', 'Hilux', 2024, 13500000, 'available') returning id""",
        TENANT_A,
    )
    from dealerai.db.session import tenant_session

    async with tenant_session(TENANT_A) as conn:
        await copilot.offer_a_new_arrival(conn, TENANT_A, uuid.UUID(str(arrival)))

    queued = await su.fetch("select payload from events where event_type = 'followup.check'")
    assert [json.loads(row["payload"])["trigger"] for row in queued] == ["similar_arrival"]


async def test_a_car_nobody_asked_for_reaches_nobody(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await su.execute("update leads set vehicle_id = null where id = $1", lead["lead"])
    arrival = await su.fetchval(
        """insert into vehicles (tenant_id, make, model, model_year, price_minor, status)
           values ($1, 'BYD', 'Seal 05', 2024, 8900000, 'available') returning id""",
        TENANT_A,
    )
    from dealerai.db.session import tenant_session

    async with tenant_session(TENANT_A) as conn:
        await copilot.offer_a_new_arrival(conn, TENANT_A, uuid.UUID(str(arrival)))
    assert await su.fetch("select 1 from events where event_type = 'followup.check'") == []


async def test_a_reply_schedules_its_own_follow_up_check(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    """No sweep and no scheduler: the message that starts the wait books the
    check, exactly as the response target is booked in S2."""
    from dealerai.db.session import tenant_session

    async with tenant_session(TENANT_A) as conn:
        await copilot.schedule_no_reply_check(conn, TENANT_A, lead["conversation"], NOW)

    queued = await su.fetch(
        """select payload, run_after from events where event_type = 'followup.check'"""
    )
    assert len(queued) == 1
    assert json.loads(queued[0]["payload"])["trigger"] == "no_reply_48h"
    assert queued[0]["run_after"] > datetime.now(UTC) + timedelta(days=1)


async def test_a_thread_with_six_replies_books_one_check(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    from dealerai.db.session import tenant_session

    async with tenant_session(TENANT_A) as conn:
        for minutes in range(6):
            await copilot.schedule_no_reply_check(
                conn, TENANT_A, lead["conversation"], NOW + timedelta(minutes=minutes)
            )
    assert len(await su.fetch("select 1 from events where event_type = 'followup.check'")) == 1


async def test_a_check_finds_the_open_lead_its_conversation_belongs_to(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await copilot.on_followup_check(
        Event(
            id=1,
            tenant_id=TENANT_A,
            event_type="followup.check",
            payload={
                "trigger": "no_reply_48h",
                "conversation_id": str(lead["conversation"]),
            },
            attempts=1,
            dedupe_key=None,
        )
    )
    assert len(await _tasks(su, lead["lead"])) == 1


async def test_a_conversation_with_no_open_lead_is_left_alone(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    await su.execute(
        """update leads set stage_id = (
             select s.id from pipeline_stages s where s.tenant_id = $1 and s.category = 'won'
             limit 1) where id = $2""",
        TENANT_A,
        lead["lead"],
    )
    await copilot.on_followup_check(
        Event(
            id=1,
            tenant_id=TENANT_A,
            event_type="followup.check",
            payload={
                "trigger": "no_reply_48h",
                "conversation_id": str(lead["conversation"]),
            },
            attempts=1,
            dedupe_key=None,
        )
    )
    assert agent.calls == 0


async def test_a_customer_who_wrote_back_is_the_inboxs_problem(
    db: None, su: asyncpg.Connection, lead: dict[str, Any], agent: Agent
) -> None:
    """They wrote last. Following that up is answering it, which is a person's
    job and the response target's."""
    await su.execute(
        """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                 type, body, created_at)
           values ($1,$2,'message','in','customer','customer','text','any news?',$3)""",
        TENANT_A,
        lead["conversation"],
        NOW - timedelta(hours=1),
    )
    await copilot.on_followup_check(_check(lead))
    assert agent.calls == 0
    assert await _tasks(su, lead["lead"]) == []


# ---------------------------------------------------------------------------
# Sending it
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
        "Idempotency-Key": str(uuid.uuid4()),
    }


async def _a_task_with_a_draft(**over: Any) -> dict[str, Any]:
    """The follow-up as the card sees it, built without the agent."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        channel_id = await conn.fetchval(
            """insert into channels (tenant_id, platform, external_id, handle, status)
               values ($1, 'whatsapp', $2, '+971 4 123 4567', 'connected') returning id""",
            TENANT_A,
            f"wa-{uuid.uuid4()}",
        )
        contact_id = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id, consent)
               values ($1, 'Karim Benali', $2, $3, $4::jsonb) returning id""",
            TENANT_A,
            over.get("owner", SALES_1),
            TEAM_LOCAL,
            json.dumps(over.get("consent", {})),
        )
        conversation_id = await conn.fetchval(
            """insert into conversations
                 (tenant_id, contact_id, channel_id, surface, status, owner_id, assigned_to,
                  wa_window_expires_at)
               values ($1,$2,$3,'whatsapp','open',$4,$4,$5) returning id""",
            TENANT_A,
            contact_id,
            channel_id,
            over.get("owner", SALES_1),
            over.get("window", NOW + timedelta(hours=10)),
        )
        task_id = await conn.fetchval(
            """insert into tasks (tenant_id, title, kind, due_at, assignee_id, contact_id,
                                  conversation_id, source, status, ai_draft)
               values ($1,$2,'follow_up',now(),$3,$4,$5,'ai',$6,$7::jsonb) returning id""",
            TENANT_A,
            REASON,
            over.get("owner", SALES_1),
            contact_id,
            conversation_id,
            over.get("status", "open"),
            json.dumps(over.get("draft", {"reason": REASON, "text": DRAFT})),
        )
        return {
            "task": uuid.UUID(str(task_id)),
            "conversation": uuid.UUID(str(conversation_id)),
        }
    finally:
        await conn.close()


async def _messages(conversation_id: uuid.UUID) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await conn.fetch(  # type: ignore[no-any-return]
            """select body, type, status from messages
                 where conversation_id = $1 and direction = 'out'""",
            conversation_id,
        )
    finally:
        await conn.close()


async def _task_status(task_id: uuid.UUID) -> str:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return str(await conn.fetchval("select status from tasks where id = $1", task_id))
    finally:
        await conn.close()


def test_sending_a_draft_completes_the_task_in_the_same_breath(client: TestClient) -> None:
    """A message sent with the task left open gets sent twice by a salesperson
    clearing their list."""
    built = asyncio.run(_a_task_with_a_draft())
    response = client.post(f"/v1/tasks/{built['task']}/send-draft", headers=_auth(SALES_1))

    assert response.status_code == 202
    assert asyncio.run(_task_status(built["task"])) == "done"
    sent = asyncio.run(_messages(built["conversation"]))
    assert [row["body"] for row in sent] == [DRAFT]


def test_a_window_that_closed_since_drafting_refuses_the_send(client: TestClient) -> None:
    """Drafted Tuesday, sent Thursday. The state it was written against is not
    the state it is sent in."""
    built = asyncio.run(_a_task_with_a_draft(window=NOW - timedelta(hours=1)))
    response = client.post(f"/v1/tasks/{built['task']}/send-draft", headers=_auth(SALES_1))

    assert response.status_code == 422
    assert response.json()["type"].endswith("window-closed")
    assert asyncio.run(_task_status(built["task"])) == "open"


def test_a_customer_who_opted_out_since_drafting_refuses_the_send(client: TestClient) -> None:
    built = asyncio.run(_a_task_with_a_draft(consent={"opted_out_at": "2026-09-20"}))
    response = client.post(f"/v1/tasks/{built['task']}/send-draft", headers=_auth(SALES_1))
    assert response.status_code == 422
    assert response.json()["type"].endswith("consent-required")


def test_a_task_already_done_cannot_be_sent_again(client: TestClient) -> None:
    built = asyncio.run(_a_task_with_a_draft(status="done"))
    assert (
        client.post(f"/v1/tasks/{built['task']}/send-draft", headers=_auth(SALES_1)).status_code
        == 422
    )


def test_a_task_with_no_draft_says_to_open_the_conversation(client: TestClient) -> None:
    built = asyncio.run(_a_task_with_a_draft(draft={"reason": REASON, "text": None}))
    response = client.post(f"/v1/tasks/{built['task']}/send-draft", headers=_auth(SALES_1))
    assert response.status_code == 422
    assert "Open the conversation" in response.json()["detail"]


def test_sending_the_same_draft_twice_sends_one_message(client: TestClient) -> None:
    built = asyncio.run(_a_task_with_a_draft())
    headers = _auth(SALES_1)
    first = client.post(f"/v1/tasks/{built['task']}/send-draft", headers=headers)
    second = client.post(f"/v1/tasks/{built['task']}/send-draft", headers=headers)

    assert first.json()["id"] == second.json()["id"]
    assert len(asyncio.run(_messages(built["conversation"]))) == 1


def test_a_salesperson_cannot_send_a_colleagues_follow_up(client: TestClient) -> None:
    built = asyncio.run(_a_task_with_a_draft(owner=SALES_2))
    assert (
        client.post(f"/v1/tasks/{built['task']}/send-draft", headers=_auth(SALES_1)).status_code
        == 404
    )
