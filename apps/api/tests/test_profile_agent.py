"""What a quiet conversation teaches us — and what is thrown away.

The model is stubbed and everything else is real. Everything the model returns
here is a proposal; these tests are almost all about what code refuses to keep.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from conftest import SALES_1, TEAM_LOCAL, TENANT_A
from dealerai.agents.sales import profile as profile_agent
from dealerai.agents.sales.profile import Learned, Studied, Summary
from dealerai.core.errors import Unusable
from dealerai.events.bus import Event
from dealerai.events.handlers import copilot
from dealerai.sales import scoring

NOW = datetime.now(UTC)


class Model:
    def __init__(self) -> None:
        self.learned = Learned(
            summary=Summary(text="They want a Land Cruiser.", next_action="call")
        )
        self.calls = 0
        self.prompts: list[str] = []

    def learns(
        self,
        *,
        updates: list[tuple[str, str, str]] | None = None,
        signals: list[tuple[str, str]] | None = None,
        summary: tuple[str, str] | None = None,
    ) -> None:
        self.learned = Learned(
            updates=[
                {"field": field, "value": value, "evidence_message_id": evidence}  # type: ignore[list-item]
                for field, value, evidence in (updates or [])
            ],
            signals=[
                {"signal": name, "evidence_message_id": evidence}  # type: ignore[list-item]
                for name, evidence in (signals or [])
            ],
            summary=Summary(text=summary[0], next_action=summary[1])
            if summary
            else Summary(text="Nothing new.", next_action="wait"),
        )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Model:
    stub = Model()

    async def fake(**kwargs: Any) -> Studied:
        stub.calls += 1
        stub.prompts.append(str(kwargs["transcript"]))
        return Studied(learned=stub.learned, cost_usd=0.003)

    monkeypatch.setattr(copilot, "study", fake)
    return stub


@pytest.fixture
async def thread(su: asyncpg.Connection, seeded: None) -> AsyncIterator[dict[str, Any]]:
    """One conversation with three customer messages and an open lead."""
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
    contact_id = await su.fetchval(
        """insert into contacts (tenant_id, full_name, owner_id, team_id)
           values ($1, 'Omar Al Mazrouei', $2, $3) returning id""",
        TENANT_A,
        SALES_1,
        TEAM_LOCAL,
    )
    conversation_id = await su.fetchval(
        """insert into conversations (tenant_id, contact_id, surface, status, owner_id, assigned_to)
           values ($1, $2, 'whatsapp', 'open', $3, $3) returning id""",
        TENANT_A,
        contact_id,
        SALES_1,
    )
    messages = []
    for minutes, direction, body in (
        (60, "in", "how much for the Land Cruiser?"),
        (55, "out", "AED 235,000."),
        (50, "in", "my budget is 228,000, and I need it shipped to Algeria"),
    ):
        messages.append(
            await su.fetchval(
                """insert into messages (tenant_id, conversation_id, kind, direction, sender,
                                         origin, type, body, created_at)
                   values ($1,$2,'message',$3,$4,$5,'text',$6,$7) returning id""",
                TENANT_A,
                conversation_id,
                direction,
                "customer" if direction == "in" else "human",
                "customer" if direction == "in" else "inbox",
                body,
                NOW - timedelta(minutes=minutes),
            )
        )
    pipeline_id, stage_id = await su.fetchrow(  # type: ignore[misc]
        """select p.id, s.id from pipelines p
             join pipeline_stages s on s.pipeline_id = p.id and s.category = 'open'
            where p.tenant_id = $1 order by p.position, s.position limit 1""",
        TENANT_A,
    )
    lead_id = await su.fetchval(
        """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                              owner_id, intent_band, score)
           values ($1,$2,$3,$4,$5,$6,'cold',0) returning id""",
        TENANT_A,
        contact_id,
        conversation_id,
        pipeline_id,
        stage_id,
        SALES_1,
    )
    yield {
        "conversation": uuid.UUID(str(conversation_id)),
        "contact": uuid.UUID(str(contact_id)),
        "lead": uuid.UUID(str(lead_id)),
        "messages": [uuid.UUID(str(m)) for m in messages],
        "last": uuid.UUID(str(messages[-1])),
    }


def _event(thread: dict[str, Any], message: uuid.UUID | None = None) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="conversation.idle",
        payload={
            "conversation_id": str(thread["conversation"]),
            "message_id": str(message or thread["last"]),
        },
        attempts=1,
        dedupe_key=None,
    )


async def _profile(su: asyncpg.Connection, contact_id: uuid.UUID) -> dict[str, Any]:
    raw = await su.fetchval("select profile from contacts where id = $1", contact_id)
    return dict(json.loads(raw)) if raw else {}


async def _lead(su: asyncpg.Connection, lead_id: uuid.UUID) -> asyncpg.Record:
    row = await su.fetchrow(
        "select score, intent_band, score_signals from leads where id = $1", lead_id
    )
    assert row is not None
    return row


async def _summary(su: asyncpg.Connection, conversation_id: uuid.UUID) -> dict[str, Any]:
    raw = await su.fetchval("select summary from conversations where id = $1", conversation_id)
    return dict(json.loads(raw)) if raw else {}


# ---------------------------------------------------------------------------
# What is kept
# ---------------------------------------------------------------------------


async def test_what_the_customer_said_lands_on_their_record(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(updates=[("budget", "228000", str(thread["messages"][2]))])
    await copilot.on_conversation_idle(_event(thread))

    field = (await _profile(su, thread["contact"]))["budget"]
    assert field["value"] == {"amount_minor": 22800000, "currency": "AED"}
    assert field["source"] == "ai"
    assert field["evidence_message_id"] == str(thread["messages"][2])


async def test_the_summary_is_written_for_whoever_picks_it_up_cold(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(summary=("Wants a Land Cruiser shipped to Algeria.", "send the export quote"))
    await copilot.on_conversation_idle(_event(thread))

    summary = await _summary(su, thread["conversation"])
    assert summary["text"] == "Wants a Land Cruiser shipped to Algeria."
    assert summary["next_action"] == "send the export quote"
    assert summary["cursor_message_id"] == str(thread["messages"][2])


async def test_every_field_shape_survives_the_round_trip(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The model writes strings; the store holds money, booleans and lists."""
    evidence = str(thread["messages"][2])
    model.learns(
        updates=[
            ("interest", "Land Cruiser 4.0, white", evidence),
            ("budget", "AED 228,000", evidence),
            ("purchase_type", "export", evidence),
            ("destination", "dz", evidence),
            ("trade_in", "yes", evidence),
            ("objections", "shipping cost, colour", evidence),
        ]
    )
    await copilot.on_conversation_idle(_event(thread))

    stored = {key: value["value"] for key, value in (await _profile(su, thread["contact"])).items()}
    assert stored == {
        "interest": "Land Cruiser 4.0, white",
        "budget": {"amount_minor": 22800000, "currency": "AED"},
        "purchase_type": "export",
        "destination": "DZ",
        "trade_in": True,
        "objections": ["shipping cost", "colour"],
    }


# ---------------------------------------------------------------------------
# What is thrown away
# ---------------------------------------------------------------------------


async def test_a_value_a_person_set_is_never_overwritten(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The rule the whole panel rests on. Being corrected and then ignored is
    how people stop correcting anything."""
    await su.execute(
        """update contacts set profile = $2::jsonb where id = $1""",
        thread["contact"],
        json.dumps(
            {
                "budget": {
                    "value": {"amount_minor": 22800000, "currency": "AED"},
                    "source": "human",
                    "evidence_message_id": None,
                }
            }
        ),
    )
    model.learns(updates=[("budget", "300000", str(thread["messages"][2]))])
    await copilot.on_conversation_idle(_event(thread))

    field = (await _profile(su, thread["contact"]))["budget"]
    assert field["value"]["amount_minor"] == 22800000
    assert field["source"] == "human"


async def test_the_ai_may_correct_its_own_earlier_guess(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(updates=[("interest", "Hilux", str(thread["messages"][0]))])
    await copilot.on_conversation_idle(_event(thread))
    await su.execute(
        "update conversations set summary = null where id = $1", thread["conversation"]
    )

    model.learns(updates=[("interest", "Land Cruiser", str(thread["messages"][2]))])
    await copilot.on_conversation_idle(_event(thread))
    assert (await _profile(su, thread["contact"]))["interest"]["value"] == "Land Cruiser"


async def test_evidence_from_another_conversation_is_dropped(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The prompt-injection case with a real consequence: a message id from
    somebody else's thread would put their words on this customer's record."""
    model.learns(updates=[("interest", "Hilux", str(uuid.uuid4()))])
    await copilot.on_conversation_idle(_event(thread))
    assert "interest" not in await _profile(su, thread["contact"])


async def test_one_invalid_field_does_not_cost_the_summary(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(
        updates=[("destination", "Algeria", str(thread["messages"][2]))],  # not ISO-2
        summary=("They want it shipped to Oran.", "send the export quote"),
    )
    await copilot.on_conversation_idle(_event(thread))

    assert "destination" not in await _profile(su, thread["contact"])
    assert (await _summary(su, thread["conversation"]))["next_action"] == "send the export quote"


async def test_a_budget_with_no_number_in_it_is_dropped(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(updates=[("budget", "not sure yet", str(thread["messages"][2]))])
    await copilot.on_conversation_idle(_event(thread))
    assert "budget" not in await _profile(su, thread["contact"])


async def test_a_signal_this_version_does_not_know_is_not_stored(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The scorer ignores it; storing it would make the drawer's reasons and
    the number above them disagree on screen."""
    model.learns(
        signals=[
            ("read_their_mind", str(thread["messages"][0])),
            ("asked_price", str(thread["messages"][0])),
        ]
    )
    await copilot.on_conversation_idle(_event(thread))

    lead = await _lead(su, thread["lead"])
    assert [row["signal"] for row in json.loads(lead["score_signals"])] == ["asked_price"]
    assert lead["score"] == 10  # the unknown one contributed nothing


async def test_a_budget_they_gave_is_the_budget_signal(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The exit run's agent wrote down AED 240,000 and not the ten points that
    go with it. A budget the customer stated is the signal; code says so."""
    model.learns(updates=[("budget", "AED 240,000", str(thread["messages"][2]))])
    await copilot.on_conversation_idle(_event(thread))

    lead = await _lead(su, thread["lead"])
    signals = [row["signal"] for row in json.loads(lead["score_signals"])]
    assert "gave_budget_or_timeline_30d" in signals


async def test_a_signal_the_model_does_not_get_to_claim(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """`responsive` is arithmetic over timestamps, not something anybody says."""
    assert "responsive" not in profile_agent.PROPOSABLE
    assert "silent" not in profile_agent.PROPOSABLE


# ---------------------------------------------------------------------------
# The score
# ---------------------------------------------------------------------------


async def test_the_score_and_its_reasons_come_out_of_the_same_function(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(
        signals=[
            ("asked_price", str(thread["messages"][0])),
            ("requested_visit_or_test_drive", str(thread["messages"][2])),
        ]
    )
    await copilot.on_conversation_idle(_event(thread))

    lead = await _lead(su, thread["lead"])
    stored = json.loads(lead["score_signals"])
    total, band, _ = scoring.score(scoring.from_stored(stored))
    assert (lead["score"], lead["intent_band"]) == (total, band)


async def test_running_twice_does_not_count_a_signal_twice(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(signals=[("asked_price", str(thread["messages"][0]))])
    await copilot.on_conversation_idle(_event(thread))
    first = (await _lead(su, thread["lead"]))["score"]

    await su.execute(
        "update conversations set summary = null where id = $1", thread["conversation"]
    )
    await copilot.on_conversation_idle(_event(thread))
    assert (await _lead(su, thread["lead"]))["score"] == first


async def test_a_lead_turning_hot_tells_its_owner_once(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    evidence = str(thread["messages"][0])
    model.learns(
        signals=[
            ("asked_price", evidence),
            ("asked_availability", evidence),
            ("requested_visit_or_test_drive", evidence),
            ("negotiating_specific_car", evidence),
            ("shared_id_or_asked_payment_details", evidence),
        ]
    )
    await copilot.on_conversation_idle(_event(thread))

    assert (await _lead(su, thread["lead"]))["intent_band"] == "hot"
    told = await su.fetch(
        "select kind, title from notifications where tenant_id = $1 and user_id = $2",
        TENANT_A,
        SALES_1,
    )
    assert [row["kind"] for row in told] == ["lead_hot"]
    assert "Omar Al Mazrouei" in told[0]["title"]

    await su.execute(
        "update conversations set summary = null where id = $1", thread["conversation"]
    )
    await copilot.on_conversation_idle(_event(thread))
    assert len(await su.fetch("select 1 from notifications where user_id = $1", SALES_1)) == 1


async def test_a_lead_staying_cold_tells_nobody(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.learns(signals=[("asked_price", str(thread["messages"][0]))])
    await copilot.on_conversation_idle(_event(thread))
    assert await su.fetch("select 1 from notifications where user_id = $1", SALES_1) == []


# ---------------------------------------------------------------------------
# When not to run at all
# ---------------------------------------------------------------------------


async def test_a_conversation_with_nothing_new_costs_nothing(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """Two greetings is not worth a model call. At Pollux's volume this one
    decision is a couple of thousand calls a month."""
    await copilot.on_conversation_idle(_event(thread))
    await copilot.on_conversation_idle(_event(thread))
    assert model.calls == 1


async def test_a_customer_still_writing_is_left_for_the_next_idle(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await su.execute(
        """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                 type, body)
           values ($1, $2, 'message', 'in', 'customer', 'customer', 'text', 'and the Hilux?')""",
        TENANT_A,
        thread["conversation"],
    )
    await copilot.on_conversation_idle(_event(thread))
    assert model.calls == 0


async def test_one_new_message_is_not_enough(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await su.execute(
        "update conversations set summary = $2::jsonb where id = $1",
        thread["conversation"],
        json.dumps({"cursor_message_id": str(thread["messages"][0])}),
    )
    await copilot.on_conversation_idle(_event(thread))
    assert model.calls == 0


async def test_an_exhausted_budget_stops_the_profile_runs_too(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await su.execute("update tenants set monthly_ai_budget_usd = 0 where id = $1", TENANT_A)
    await copilot.on_conversation_idle(_event(thread))  # does not raise
    assert model.calls == 0


async def test_a_conversation_that_is_gone_is_not_an_error(
    db: None, seeded: None, model: Model
) -> None:
    await copilot.on_conversation_idle(
        Event(
            id=1,
            tenant_id=TENANT_A,
            event_type="conversation.idle",
            payload={"conversation_id": str(uuid.uuid4()), "message_id": str(uuid.uuid4())},
            attempts=1,
            dedupe_key=None,
        )
    )
    assert model.calls == 0


# ---------------------------------------------------------------------------
# The prompt, and the pure half
# ---------------------------------------------------------------------------


async def test_the_transcript_carries_message_ids(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """Without them the model cannot cite evidence, and every update is dropped."""
    await copilot.on_conversation_idle(_event(thread))
    assert str(thread["messages"][0]) in model.prompts[0]


def test_the_summary_is_asked_for_in_english_whatever_the_conversation_was() -> None:
    from dealerai.ai.prompts import load

    assert "in English" in load("profile")


@pytest.mark.parametrize(
    "field,written,stored",
    [
        ("budget", "235000", {"amount_minor": 23500000}),
        ("budget", "AED 235,000", {"amount_minor": 23500000}),
        ("trade_in", "yes", True),
        ("trade_in", "no", False),
        ("trade_in", "نعم", True),
        ("objections", "shipping cost, colour", ["shipping cost", "colour"]),
        ("objections", "price", ["price"]),
        ("destination", "dz", "DZ"),
        ("interest", "  Land Cruiser  ", "Land Cruiser"),
    ],
)
def test_the_string_the_model_wrote_becomes_what_the_field_holds(
    field: str, written: str, stored: Any
) -> None:
    assert profile_agent.coerce(field, written) == stored


@pytest.mark.parametrize("field,written", [("budget", "not sure"), ("interest", "   ")])
def test_something_unreadable_is_one_dropped_field(field: str, written: str) -> None:
    with pytest.raises(Unusable):
        profile_agent.coerce(field, written)
