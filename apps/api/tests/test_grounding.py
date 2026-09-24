"""What reaches the prompt, and what must not.

Against the database, because what is being tested is the SQL: which rows a
draft may be built from is the difference between a reply that is right and one
that is merely plausible.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.agents.sales.intent import Entities, Read
from dealerai.sales import grounding

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)


def _json(value: Any) -> str | None:
    """`su` is a raw connection with no jsonb codec — only the app pool has one."""
    return None if value is None else json.dumps(value)


def _read(**over: Any) -> Read:
    return Read.model_validate(
        {"intent": "price", "confidence": 0.9, "language": "en", "script": "latin", **over}
    )


@pytest.fixture
async def thread(su: asyncpg.Connection, seeded: None) -> AsyncIterator[dict[str, uuid.UUID]]:
    """One conversation with everything a draft has to cope with.

    Two typed messages and a voice note, a reply of ours, a grey event line, an
    internal note, an open lead, one available car and one reserved, a closed
    24-hour window and an approved template.
    """
    channel_id = await su.fetchval(
        """insert into channels (tenant_id, platform, external_id, handle, status)
           values ($1, 'whatsapp', $2, '+971 4 123 4567', 'connected') returning id""",
        TENANT_A,
        f"wa-{uuid.uuid4()}",
    )
    contact_id = await su.fetchval(
        """insert into contacts (tenant_id, full_name, country, locale, profile)
           values ($1, 'Omar Al Mazrouei', 'AE', 'ar', $2::jsonb) returning id""",
        TENANT_A,
        json.dumps({"interest": {"value": "Land Cruiser, white", "source": "ai"}}),
    )
    conversation_id = await su.fetchval(
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, status, wa_window_expires_at)
           values ($1, $2, $3, 'whatsapp', 'open', $4) returning id""",
        TENANT_A,
        contact_id,
        channel_id,
        NOW - timedelta(hours=2),  # closed two hours ago
    )

    async def say(kind: str, direction: str, body: str | None, **extra: Any) -> uuid.UUID:
        return await su.fetchval(  # type: ignore[no-any-return]
            """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                     type, body, transcript, event, created_at)
               values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11) returning id""",
            TENANT_A,
            conversation_id,
            kind,
            direction,
            "customer" if direction == "in" else "human",
            "customer" if direction == "in" else extra.get("origin", "inbox"),
            extra.get("type", "text"),
            body,
            _json(extra.get("transcript")),
            _json(extra.get("event")),
            extra.get("at", NOW - timedelta(hours=3)),
        )

    first = await say("message", "in", "how much for the Land Cruiser?")
    await say("message", "out", "Let me check for you.", at=NOW - timedelta(hours=2, minutes=50))
    await say(
        "message",
        "in",
        None,
        type="audio",
        transcript={"text": "and shipping to Algeria?", "language": "en"},
        at=NOW - timedelta(hours=2, minutes=40),
    )
    await say(
        "event",
        "out",
        None,
        origin="system",
        event={"type": "assigned", "text": "Assigned to Ahmed Nasser"},
        at=NOW - timedelta(hours=2, minutes=30),
    )
    await say(
        "note",
        "out",
        "He is in a hurry, his lease ends this month",
        origin="inbox",
        at=NOW - timedelta(hours=2, minutes=20),
    )

    available = await su.fetchval(
        """insert into vehicles (tenant_id, make, model, model_year, price_minor, status,
                                 exterior_color)
           values ($1, 'Toyota', 'Land Cruiser', 2023, 23500000, 'available', 'White')
           returning id""",
        TENANT_A,
    )
    await su.execute(
        """insert into vehicles (tenant_id, make, model, model_year, price_minor, status)
           values ($1, 'Toyota', 'Land Cruiser', 2022, 21000000, 'reserved')""",
        TENANT_A,
    )
    pipeline_id, stage_id = await su.fetchrow(  # type: ignore[misc]
        """select p.id, s.id from pipelines p
             join pipeline_stages s on s.pipeline_id = p.id and s.category = 'open'
            where p.tenant_id = $1 order by p.position, s.position limit 1""",
        TENANT_A,
    )
    await su.execute(
        """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                              vehicle_id, budget_minor)
           values ($1,$2,$3,$4,$5,$6,23000000)""",
        TENANT_A,
        contact_id,
        conversation_id,
        pipeline_id,
        stage_id,
        available,
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
        "conversation": conversation_id,
        "contact": contact_id,
        "vehicle": available,
        "first_message": first,
    }


async def test_the_customers_words_are_marked_untrusted(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    layer = grounding.context_layer(ground, _read())
    assert "<untrusted>" in layer
    assert layer.count("<untrusted>") == layer.count("</untrusted>")


async def test_a_voice_note_reaches_the_prompt_as_its_transcript(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """Otherwise the draft answers the typed messages and ignores the one the
    customer actually spoke."""
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert any("shipping to Algeria" in row["text"] for row in ground.tail)
    assert "voice note, transcribed" in grounding.context_layer(ground, _read())


async def test_an_internal_note_is_labelled_as_never_to_be_repeated(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert ground.notes == ["He is in a hurry, his lease ends this month"]
    assert "never to be repeated to the customer" in grounding.context_layer(ground, _read())


async def test_a_note_is_not_part_of_the_conversation(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """It is about the customer, not to them, and a model reading it in the
    thread will answer it."""
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert not any("lease ends" in row["text"] for row in ground.tail)


async def test_event_lines_are_not_part_of_the_conversation(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """'Assigned to Ahmed' is a grey line in the inbox. To a model it reads as
    something the customer can see."""
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert not any("Assigned to" in row["text"] for row in ground.tail)


async def test_a_reserved_car_is_shown_and_marked(db: None, thread: dict[str, uuid.UUID]) -> None:
    """A model that cannot see it says it does not exist, which is worse than
    saying it is reserved."""
    ground = await grounding.load(
        TENANT_A,
        thread["conversation"],
        _read(entities=Entities(model="Land Cruiser")),
        now=NOW,
    )
    assert ground is not None
    statuses = set(ground.vehicle_statuses().values())
    assert statuses == {"available", "reserved"}
    assert "reserved" in grounding.context_layer(ground, _read())


async def test_the_prices_the_guard_allows_are_the_prices_the_prompt_showed(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """The one invariant this module exists for. Load them separately and a
    draft eventually quotes a price its own guard rejects."""
    ground = await grounding.load(
        TENANT_A, thread["conversation"], _read(entities=Entities(model="Land Cruiser")), now=NOW
    )
    assert ground is not None
    layer = grounding.context_layer(ground, _read())
    assert ground.allowed_prices()
    for price in ground.allowed_prices():
        assert f"{price:,.0f}" in layer


async def test_a_price_is_written_the_way_a_person_writes_one(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """Handing the model 23500000 is how a draft offers a Land Cruiser for
    AED 23,500,000."""
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    layer = grounding.context_layer(ground, _read())
    assert "AED 235,000" in layer
    assert "23500000" not in layer


async def test_a_closed_window_offers_templates_instead_of_free_text(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert ground.window_open is False
    layer = grounding.context_layer(ground, _read())
    assert "24-hour window is closed" in layer
    assert "price_update" in layer


async def test_an_open_window_says_so(db: None, su: asyncpg.Connection, thread: dict) -> None:
    await su.execute(
        "update conversations set wa_window_expires_at = $2 where id = $1",
        thread["conversation"],
        NOW + timedelta(hours=10),
    )
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert ground.window_open is True
    assert "write a normal message" in grounding.context_layer(ground, _read())


async def test_arabic_in_latin_letters_is_answered_in_latin_letters(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """The model reads "reply in" and nothing else. Told only "ar", it wrote
    Arabic script to "3andkom hilux?" and the script guard sent it back."""
    read = _read(language="ar", script="latin")
    ground = await grounding.load(TENANT_A, thread["conversation"], read, now=NOW)
    assert ground is not None
    assert "- reply in: ar, in Latin letters" in grounding.context_layer(ground, read)
    arabic = _read(language="ar", script="arabic")
    assert "Latin letters" not in grounding.context_layer(ground, arabic)


async def test_a_customer_who_named_no_car_still_sees_the_stock(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """Without the fallback, a greeting gets a draft that cannot name a single
    thing for sale."""
    ground = await grounding.load(
        TENANT_A, thread["conversation"], _read(intent="greeting"), now=NOW
    )
    assert ground is not None
    assert ground.vehicles


async def test_the_dealerships_own_number_is_loaded_for_the_pii_guard(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert ground.own_contacts == {"+971 4 123 4567"}


async def test_the_open_lead_and_its_car_are_in_the_prompt(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """The difference between 'a customer' and 'the one who has been
    negotiating the white Land Cruiser for a week'."""
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert len(ground.leads) == 1
    assert "Land Cruiser" in grounding.context_layer(ground, _read())


async def test_only_the_customers_own_words_go_to_the_script_guard(
    db: None, thread: dict[str, uuid.UUID]
) -> None:
    """Our own replies are in whatever script we chose last time. Judging the
    customer's script by our own output is how a mistake compounds."""
    ground = await grounding.load(TENANT_A, thread["conversation"], _read(), now=NOW)
    assert ground is not None
    assert "Let me check for you" not in ground.customer_wrote
    assert "how much for the Land Cruiser?" in ground.customer_wrote


async def test_a_conversation_that_is_gone_grounds_nothing(db: None, seeded: None) -> None:
    assert await grounding.load(TENANT_A, uuid.uuid4(), _read(), now=NOW) is None
