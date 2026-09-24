"""The loop, driven end to end with a stubbed model.

Every test here calls the handler. None writes an ai_suggestions row by hand
and then asserts something about it — that is the mistake S2 made, and it
proved nothing about the path.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from conftest import SALES_1, TEAM_LOCAL, TENANT_A, USER_A
from dealerai.agents.sales import copilot as copilot_agent
from dealerai.agents.sales.intent import Classified, Read
from dealerai.events.bus import Event
from dealerai.events.handlers import copilot
from dealerai.orchestrator.toolloop import Conversation

NOW = datetime.now(UTC)
PRICE = 23500000  # AED 235,000


class Model:
    """The two model calls this loop makes, with whatever answers a test needs."""

    def __init__(self) -> None:
        self.read = Read(intent="price", confidence=0.95, language="en", script="latin")
        self.drafts: list[copilot_agent.Draft] = []
        self.prompts: list[str] = []
        self.calls = 0
        self.classifications = 0

    def replies(self, *texts: str, **over: Any) -> None:
        self.drafts = [
            copilot_agent.Draft.model_validate({"reply": text, "language": "en", **over})
            for text in texts
        ]

    def template(self, name: str, variables: list[str]) -> None:
        self.drafts = [
            copilot_agent.Draft(
                reply="", language="en", template_name=name, template_variables=variables
            )
        ]

    def nothing(self) -> None:
        self.drafts = [copilot_agent.Draft(reply="", language="en")]

    def next_draft(self) -> copilot_agent.Draft:
        return self.drafts[min(self.calls - 1, len(self.drafts) - 1)]


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Model:
    stub = Model()

    async def fake_classify(**kwargs: Any) -> Classified:
        stub.classifications += 1
        return Classified(read=stub.read, cost_usd=0.00002)

    async def fake_converse(task: Any, **kwargs: Any) -> Conversation:
        stub.calls += 1
        stub.prompts.append(str(kwargs.get("prompt")))
        return Conversation(text="{}", parsed=stub.next_draft(), cost_usd=0.004)

    monkeypatch.setattr(copilot, "classify", fake_classify)
    monkeypatch.setattr(copilot_agent, "converse", fake_converse)
    stub.replies(f"Yes, the Land Cruiser is available at AED {PRICE // 100:,}.")
    return stub


@pytest.fixture
async def thread(su: asyncpg.Connection, seeded: None) -> AsyncIterator[dict[str, Any]]:
    """A connected channel, an open conversation, one customer message, one car."""
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
        """insert into contacts (tenant_id, full_name, country, owner_id, team_id)
           values ($1, 'Omar Al Mazrouei', 'AE', $2, $3) returning id""",
        TENANT_A,
        SALES_1,
        TEAM_LOCAL,
    )
    conversation_id = await su.fetchval(
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, status, owner_id, assigned_to,
              wa_window_expires_at)
           values ($1, $2, $3, 'whatsapp', 'open', $4, $4, $5) returning id""",
        TENANT_A,
        contact_id,
        channel_id,
        SALES_1,
        NOW + timedelta(hours=10),
    )
    message_id = await su.fetchval(
        """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                 type, body, created_at)
           values ($1, $2, 'message', 'in', 'customer', 'customer', 'text',
                   'how much for the Land Cruiser?', $3)
           returning id""",
        TENANT_A,
        conversation_id,
        NOW - timedelta(minutes=1),
    )
    vehicle_id = await su.fetchval(
        """insert into vehicles (tenant_id, make, model, model_year, price_minor, status)
           values ($1, 'Toyota', 'Land Cruiser', 2023, $2, 'available') returning id""",
        TENANT_A,
        PRICE,
    )
    await su.execute(
        """insert into message_templates
             (tenant_id, channel_id, external_id, name, language, category, status, body)
           values ($1,$2,'t1','price_update','en','utility','approved',
                   'Hello {{1}}, the {{2}} is AED {{3}}.')""",
        TENANT_A,
        channel_id,
    )
    yield {
        "conversation": uuid.UUID(str(conversation_id)),
        "contact": uuid.UUID(str(contact_id)),
        "message": uuid.UUID(str(message_id)),
        "vehicle": uuid.UUID(str(vehicle_id)),
        "channel": uuid.UUID(str(channel_id)),
    }


def _event(thread: dict[str, Any], **over: Any) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="copilot.draft_requested",
        payload={
            "conversation_id": str(thread["conversation"]),
            "message_id": str(thread["message"]),
            **over,
        },
        attempts=1,
        dedupe_key=None,
    )


async def _suggestions(su: asyncpg.Connection, conversation_id: uuid.UUID) -> list[asyncpg.Record]:
    return await su.fetch(  # type: ignore[no-any-return]
        """select status, text, template, confidence, intent, sources, actions,
                  blocked_reason, run_id, language
             from ai_suggestions where conversation_id = $1 order by created_at""",
        conversation_id,
    )


async def _one(su: asyncpg.Connection, conversation_id: uuid.UUID) -> asyncpg.Record:
    rows = await _suggestions(su, conversation_id)
    assert len(rows) == 1, f"expected one suggestion, found {len(rows)}"
    return rows[0]


async def _open_leads(su: asyncpg.Connection, contact_id: uuid.UUID) -> int:
    return await su.fetchval(  # type: ignore[no-any-return]
        """select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
            where l.contact_id = $1 and s.category = 'open'""",
        contact_id,
    )


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_a_customer_message_produces_a_draft_a_person_can_send(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert row["status"] == "ready"
    assert "235,000" in row["text"]
    assert row["confidence"] in ("high", "medium", "low")
    assert row["intent"] == "price"
    assert row["run_id"] is not None  # "why did it say that" is one join away


async def test_the_cost_lands_on_the_run(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The cost envelope in § 10 is measured from these rows in pilot week one."""
    await copilot.on_draft_requested(_event(thread))
    row = await _one(su, thread["conversation"])
    cost = await su.fetchval("select cost_usd from agent_runs where id = $1", row["run_id"])
    assert float(cost) > 0
    status = await su.fetchval("select status from agent_runs where id = $1", row["run_id"])
    assert status == "completed"


async def test_a_well_grounded_price_answer_is_high_confidence(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.replies(
        f"Yes, the Land Cruiser is available at AED {PRICE // 100:,}. Saturday at 11:00?",
        used_vehicle_ids=[str(thread["vehicle"])],
    )
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert row["confidence"] == "high"
    sources = json.loads(row["sources"])
    assert sources[0]["kind"] == "vehicle" and "Land Cruiser" in sources[0]["label"]


async def test_a_source_the_draft_did_not_use_is_not_shown(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """A chip that opens nothing is worse than no chip."""
    model.replies("AED 235,000.", used_vehicle_ids=[str(uuid.uuid4())])
    await copilot.on_draft_requested(_event(thread))
    assert json.loads((await _one(su, thread["conversation"]))["sources"]) == []


# ---------------------------------------------------------------------------
# The six refusals, each before the first model call
# ---------------------------------------------------------------------------


async def _close_the_conversation(su: asyncpg.Connection, thread: dict[str, Any]) -> None:
    await su.execute(
        "update conversations set status = 'closed' where id = $1", thread["conversation"]
    )


async def _disconnect_the_channel(su: asyncpg.Connection, thread: dict[str, Any]) -> None:
    await su.execute("update channels set status = 'expired' where id = $1", thread["channel"])


async def _switch_drafts_off(su: asyncpg.Connection, thread: dict[str, Any]) -> None:
    await su.execute(
        """update tenants set sales_settings = sales_settings
             || '{"drafts_enabled": false}'::jsonb where id = $1""",
        TENANT_A,
    )


async def _opt_the_customer_out(su: asyncpg.Connection, thread: dict[str, Any]) -> None:
    await su.execute(
        """update contacts set consent = consent || '{"opted_out_at": "2026-09-01"}'::jsonb
            where id = $1""",
        thread["contact"],
    )


async def _a_newer_message_arrives(su: asyncpg.Connection, thread: dict[str, Any]) -> None:
    await su.execute(
        """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                 type, body)
           values ($1, $2, 'message', 'in', 'customer', 'customer', 'text', 'and the Hilux?')""",
        TENANT_A,
        thread["conversation"],
    )


async def _somebody_replied(su: asyncpg.Connection, thread: dict[str, Any]) -> None:
    await su.execute(
        """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                 type, body)
           values ($1, $2, 'message', 'out', 'human', 'inbox', 'text', 'AED 235,000.')""",
        TENANT_A,
        thread["conversation"],
    )


@pytest.mark.parametrize(
    "arrange",
    [
        _close_the_conversation,
        _disconnect_the_channel,
        _switch_drafts_off,
        _opt_the_customer_out,
        _a_newer_message_arrives,
        _somebody_replied,
    ],
)
async def test_six_reasons_not_to_spend_a_model_call(
    arrange: Any, db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await arrange(su, thread)
    await copilot.on_draft_requested(_event(thread))

    assert await _suggestions(su, thread["conversation"]) == []
    assert model.classifications == 0, "a precondition was checked after the model call"
    assert model.calls == 0


async def test_a_person_asking_again_skips_the_staleness_checks(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """Regenerate means "draft for the conversation as it is now", even though
    a colleague has already replied to it."""
    await _somebody_replied(su, thread)
    await copilot.on_draft_requested(_event(thread, forced=True))
    assert (await _one(su, thread["conversation"]))["status"] == "ready"


async def test_a_person_asking_again_does_not_skip_the_opt_out(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The two staleness checks, and nothing else."""
    await _opt_the_customer_out(su, thread)
    await copilot.on_draft_requested(_event(thread, forced=True))
    assert await _suggestions(su, thread["conversation"]) == []


async def test_a_customer_who_asks_to_stop_is_recorded_and_not_drafted_for(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The ingest handler catches the exact phrases; this catches the sentence."""
    model.read = Read(intent="opt_out", confidence=0.9, language="en", script="latin", opt_out=True)
    await copilot.on_draft_requested(_event(thread))

    assert await _suggestions(su, thread["conversation"]) == []
    assert model.calls == 0
    consent = await su.fetchval("select consent from contacts where id = $1", thread["contact"])
    assert json.loads(consent)["opted_out_at"]


# ---------------------------------------------------------------------------
# The guards, and the one regeneration
# ---------------------------------------------------------------------------


async def test_a_wrong_price_is_blocked_rather_than_shown(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The one zero-tolerance failure in this product."""
    model.replies("The Land Cruiser is yours for AED 199,000.")
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert row["status"] == "blocked"
    assert "199,000" in row["blocked_reason"]
    assert row["text"] is None


async def test_a_rejected_draft_gets_exactly_one_more_try(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.replies("I can do a 10% discount for you.", f"The price is AED {PRICE // 100:,}.")
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert row["status"] == "ready"
    assert row["confidence"] == "low", "a draft that needed a second attempt is low"
    assert model.calls == 2


async def test_a_reserved_car_may_be_named_but_not_called_available(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """Blocked by name, every English reply about a reserved car was blocked
    twice and left the customer with nothing. It may be named; it may not be
    called available."""
    await su.execute("update vehicles set status = 'reserved' where id = $1", thread["vehicle"])
    model.read = Read.model_validate(
        {
            "intent": "price",
            "confidence": 0.95,
            "language": "en",
            "script": "latin",
            "entities": {"model": "Land Cruiser"},
        }
    )
    model.replies(
        f"Yes, the Land Cruiser is available at AED {PRICE // 100:,}, but it is reserved.",
        f"The Land Cruiser is AED {PRICE // 100:,} and reserved for another customer.",
    )
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert model.calls == 2
    assert "reserved for another customer, and this says 'available'" in model.prompts[1]
    assert row["status"] == "ready"


async def test_two_rejections_block_it(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.replies("A 10% discount.", "Fine, a 5% discount then.")
    await copilot.on_draft_requested(_event(thread))

    assert (await _one(su, thread["conversation"]))["status"] == "blocked"
    assert model.calls == 2, "never a third attempt"


async def test_the_retry_is_told_exactly_what_was_wrong(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.replies("A 10% discount.", f"AED {PRICE // 100:,}.")
    await copilot.on_draft_requested(_event(thread))
    assert "discount" in model.prompts[1]
    assert "change nothing else" in model.prompts[1]


async def test_an_internal_note_is_not_quoted_back_to_the_customer(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    note = "He is desperate to buy before the end of the month, push the Prado hard"
    await su.execute(
        """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                 type, body)
           values ($1, $2, 'note', 'out', 'human', 'inbox', 'text', $3)""",
        TENANT_A,
        thread["conversation"],
        note,
    )
    model.replies(f"You are desperate to buy before the end of the month, so {note[-20:]}")
    await copilot.on_draft_requested(_event(thread))
    assert "internal note" in (await _one(su, thread["conversation"]))["blocked_reason"]


async def test_a_model_that_answers_with_nothing_blocks(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.nothing()
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert row["status"] == "blocked" and row["blocked_reason"] == "no usable draft"
    assert model.calls == 1, "an empty answer is not worth a retry"


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


async def _close_the_window(su: asyncpg.Connection, thread: dict[str, Any]) -> None:
    await su.execute(
        "update conversations set wa_window_expires_at = $2 where id = $1",
        thread["conversation"],
        NOW - timedelta(hours=1),
    )


async def test_a_closed_window_produces_a_template_not_free_text(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await _close_the_window(su, thread)
    model.template("price_update", ["Omar", "Land Cruiser", "235,000"])
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert row["status"] == "ready"
    assert row["text"] is None
    assert json.loads(row["template"])["name"] == "price_update"
    # The message itself, for the panel to show — not the template's name.
    assert json.loads(row["template"])["preview"] == "Hello Omar, the Land Cruiser is AED 235,000."


async def test_the_template_sent_is_the_one_in_the_replys_language(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """By name alone the exit run was about to send a French customer the
    English body with French variables in it."""
    french = await su.fetchval(
        """insert into message_templates
             (tenant_id, channel_id, external_id, name, language, category, status, body)
           values ($1,$2,'t2','price_update','fr','utility','approved',
                   'Bonjour {{1}}, le {{2}} est à AED {{3}}.') returning id""",
        TENANT_A,
        thread["channel"],
    )
    await _close_the_window(su, thread)
    model.drafts = [
        copilot_agent.Draft(
            reply="",
            language="fr",
            template_name="price_update",
            template_variables=["Omar", "Land Cruiser", f"{PRICE // 100:,}"],
        )
    ]
    await copilot.on_draft_requested(_event(thread))

    row = await _one(su, thread["conversation"])
    assert json.loads(row["template"])["template_id"] == str(french)


async def test_a_template_short_of_variables_goes_back_for_the_rest(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """Two for a three-variable body: the send route would refuse it, and the
    salesperson's Send would be what failed."""
    await _close_the_window(su, thread)
    model.drafts = [
        copilot_agent.Draft(
            reply="",
            language="en",
            template_name="price_update",
            template_variables=["Land Cruiser", f"{PRICE // 100:,}"],
        ),
        copilot_agent.Draft(
            reply="",
            language="en",
            template_name="price_update",
            template_variables=["Omar", "Land Cruiser", f"{PRICE // 100:,}"],
        ),
    ]
    await copilot.on_draft_requested(_event(thread))

    assert "takes 3 variables, in order, and this fills 2" in model.prompts[1]
    assert (await _one(su, thread["conversation"]))["status"] == "ready"


async def test_free_text_in_a_closed_window_is_blocked(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The prompt says templates only. The guard is what makes it true."""
    await _close_the_window(su, thread)
    model.replies("Hello again!")
    await copilot.on_draft_requested(_event(thread))
    assert "window is closed" in (await _one(su, thread["conversation"]))["blocked_reason"]


async def test_a_template_that_does_not_exist_is_blocked(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await _close_the_window(su, thread)
    model.template("invented_template", [])
    await copilot.on_draft_requested(_event(thread))
    assert "no approved template" in (await _one(su, thread["conversation"]))["blocked_reason"]


async def test_a_templates_filled_text_goes_through_the_guards(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """The variables are the model's, so the rendered message is what matters."""
    await _close_the_window(su, thread)
    model.template("price_update", ["Omar", "Land Cruiser", "199,000"])
    await copilot.on_draft_requested(_event(thread))
    assert "199,000" in (await _one(su, thread["conversation"]))["blocked_reason"]


# ---------------------------------------------------------------------------
# Superseding, and the stale claim
# ---------------------------------------------------------------------------


async def test_a_newer_draft_supersedes_the_live_one(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """Two drafts on screen is a salesperson sending the older one."""
    await copilot.on_draft_requested(_event(thread))
    await copilot.on_draft_requested(_event(thread, forced=True))

    statuses = [row["status"] for row in await _suggestions(su, thread["conversation"])]
    assert statuses == ["superseded", "ready"]


async def test_a_dead_worker_does_not_block_the_conversation_for_ever(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """A `generating` row and the partial unique index: without the release,
    one crashed run means this customer never gets another draft."""
    await su.execute(
        """insert into ai_suggestions (tenant_id, conversation_id, status, created_at)
           values ($1, $2, 'generating', now() - interval '10 minutes')""",
        TENANT_A,
        thread["conversation"],
    )
    await copilot.on_draft_requested(_event(thread))

    rows = await _suggestions(su, thread["conversation"])
    assert [row["status"] for row in rows] == ["superseded", "ready"]


# ---------------------------------------------------------------------------
# Automatic leads — docs/sales/04-ai-copilot.md § 5
# ---------------------------------------------------------------------------


async def test_a_price_question_creates_a_lead(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    assert await _open_leads(su, thread["contact"]) == 0
    await copilot.on_draft_requested(_event(thread))
    assert await _open_leads(su, thread["contact"]) == 1


async def test_a_second_question_does_not_create_a_second_lead(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await copilot.on_draft_requested(_event(thread))
    await copilot.on_draft_requested(_event(thread, forced=True))
    assert await _open_leads(su, thread["contact"]) == 1


async def test_a_greeting_creates_no_lead(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    model.read = Read(intent="greeting", confidence=0.95, language="en", script="latin")
    await copilot.on_draft_requested(_event(thread))
    assert await _open_leads(su, thread["contact"]) == 0


async def test_a_new_lead_says_so_in_the_conversation(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """A lead nobody created appearing on the board with no explanation is the
    kind of thing that makes people distrust the whole product."""
    await copilot.on_draft_requested(_event(thread))
    line = await su.fetchval(
        """select event->>'text' from messages
            where conversation_id = $1 and kind = 'event' and event->>'type' = 'lead_created'""",
        thread["conversation"],
    )
    assert line == "Lead created from this conversation"


async def test_the_lead_belongs_to_the_customers_own_salesperson(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await copilot.on_draft_requested(_event(thread))
    owner = await su.fetchval("select owner_id from leads where contact_id = $1", thread["contact"])
    assert owner == SALES_1


async def test_an_export_question_lands_on_the_export_board(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await su.execute(
        """insert into pipelines (tenant_id, name, position) values ($1, 'Export', 1)""",
        TENANT_A,
    )
    pipeline_id = await su.fetchval(
        "select id from pipelines where tenant_id = $1 and name = 'Export'", TENANT_A
    )
    await su.execute(
        """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
           values ($1, $2, 'Enquiry', 0, 'open'), ($1, $2, 'Won', 1, 'won')""",
        TENANT_A,
        pipeline_id,
    )
    model.read = Read(intent="export_shipping", confidence=0.9, language="en", script="latin")
    await copilot.on_draft_requested(_event(thread))

    board = await su.fetchval(
        """select p.name from leads l join pipelines p on p.id = l.pipeline_id
            where l.contact_id = $1""",
        thread["contact"],
    )
    assert board == "Export"


async def test_a_lead_from_an_ad_records_where_it_came_from(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    await su.execute(
        'update messages set referral = \'{"source_type": "ad"}\'::jsonb where id = $1',
        thread["message"],
    )
    await copilot.on_draft_requested(_event(thread))
    source = await su.fetchval("select source from leads where contact_id = $1", thread["contact"])
    assert source == "ad"


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


async def test_an_exhausted_budget_produces_no_draft_and_no_failed_event(
    db: None, su: asyncpg.Connection, thread: dict[str, Any], model: Model
) -> None:
    """A tenant at its ceiling still gets its messages ingested, assigned,
    answered and delivered. Only the drafts stop."""
    await su.execute("update tenants set monthly_ai_budget_usd = 0 where id = $1", TENANT_A)

    await copilot.on_draft_requested(_event(thread))  # does not raise
    assert await _suggestions(su, thread["conversation"]) == []

    await copilot.on_draft_requested(_event(thread, forced=True))
    kinds = await su.fetch(
        "select kind from notifications where tenant_id = $1 and user_id = $2", TENANT_A, USER_A
    )
    # Told once a day, not once a message — otherwise the bell is the first
    # thing people stop opening.
    assert [row["kind"] for row in kinds] == ["ai_budget_exhausted"]
