"""Enrichment grounding.

The rules in `verify()` are pure, so most of this file needs no database and no
model. The last section is the acceptance test from the plan, run end to end
against Postgres with a model that deliberately misbehaves — because a prompt
that says "do not invent" is a request, and this asserts the enforcement.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import pytest
from google.genai import types

from conftest import TENANT_A
from dealerai.agents.content.enrichment import (
    ENRICHABLE,
    MIN_QUOTE_CHARS,
    USP,
    Enrichment,
    SpecFill,
    enrich,
    verify,
)
from dealerai.ai import gateway

DOCS = """<untrusted>
### Land Cruiser 300 specification
Engine: 3.5L V6 twin-turbo
Maximum power: 415 hp at 5200 rpm
Seating capacity: 7
</untrusted>"""

RECORD: dict[str, Any] = {
    "make": "TOYOTA",
    "model": "land cruiser",
    "trim": None,
    "power_hp": None,
    "torque_nm": None,
    "seats": None,
    "engine": None,
    "mileage_km": 12000,
    "features": ["sunroof"],
    "exterior_color": None,
}


def proposal(**kwargs: Any) -> Enrichment:
    base: dict[str, Any] = {"make": "Toyota", "model": "Land Cruiser"}
    return Enrichment(**{**base, **kwargs})


# --------------------------------------------------------------------------
# grounding — the reason this module exists
# --------------------------------------------------------------------------


def test_a_quoted_fact_is_kept() -> None:
    v = verify(
        proposal(fills=[SpecFill(field="power_hp", value="415", quote="Maximum power: 415 hp")]),
        record=RECORD,
        documents=DOCS,
    )
    assert v.updates["power_hp"] == 415
    assert v.provenance[0]["quote"] == "Maximum power: 415 hp"


def test_a_fact_with_no_quote_in_the_documents_is_dropped() -> None:
    """The model knows this car. Its knowledge is not admissible."""
    v = verify(
        proposal(
            fills=[SpecFill(field="torque_nm", value="650", quote="Maximum torque: 650 Nm")],
        ),
        record=RECORD,
        documents=DOCS,
    )
    assert "torque_nm" not in v.updates
    assert v.dropped == ["torque_nm: quote not found in the documents"]


def test_a_real_quote_cannot_justify_an_unrelated_value() -> None:
    """The subtler failure: the sentence is genuine, it just says nothing about
    the number attached to it."""
    v = verify(
        proposal(fills=[SpecFill(field="torque_nm", value="650", quote="Seating capacity: 7")]),
        record=RECORD,
        documents=DOCS,
    )
    assert "torque_nm" not in v.updates
    assert "is not in its own quote" in v.dropped[0]


def test_whitespace_and_case_differences_do_not_break_a_quote() -> None:
    """PDF extraction produces runs of spaces and stray newlines that the model
    tidies as it quotes. That is not a paraphrase."""
    v = verify(
        proposal(fills=[SpecFill(field="seats", value="7", quote="seating   capacity:\n 7")]),
        record=RECORD,
        documents=DOCS,
    )
    assert v.updates["seats"] == 7


def test_a_quote_too_short_to_mean_anything_is_dropped() -> None:
    """'7' appears in every spec sheet ever written."""
    short = "7 seats"
    assert len(short) < MIN_QUOTE_CHARS
    v = verify(
        proposal(fills=[SpecFill(field="seats", value="7", quote=short)]),
        record=RECORD,
        documents=DOCS,
    )
    assert "seats" not in v.updates


def test_with_no_documents_nothing_can_be_filled() -> None:
    v = verify(
        proposal(
            fills=[
                SpecFill(field="power_hp", value="415", quote="Maximum power: 415 hp"),
                SpecFill(field="seats", value="7", quote="Seating capacity: 7"),
            ]
        ),
        record=RECORD,
        documents="",
    )
    assert not set(v.updates) & set(ENRICHABLE)


def test_enrichment_never_overwrites_what_the_dealer_typed() -> None:
    """A value already in the record came from the dealer or their DMS, and
    beats anything read out of a PDF."""
    v = verify(
        proposal(fills=[SpecFill(field="seats", value="7", quote="Seating capacity: 7")]),
        record={**RECORD, "seats": 5},
        documents=DOCS,
    )
    assert "seats" not in v.updates
    assert v.dropped == ["seats: already set"]


def test_a_price_cannot_be_enriched_at_all() -> None:
    """Not a rule in verify() — a rule in the schema. A price list in the
    tenant's library must not become a back door around the price endpoint,
    which is what writes history and warns published content."""
    assert not {"price_minor", "min_price_minor", "mileage_km", "vin"} & set(ENRICHABLE)
    with pytest.raises(ValueError, match="price_minor"):
        SpecFill(field="price_minor", value="100", quote="Price: AED 100")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# normalisation may re-spell a name, never rewrite it
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("TOYOTA", "Toyota"),
        ("land cruiser", "Land Cruiser"),
        ("mercedes benz", "Mercedes-Benz"),
        ("تويوتا", "Toyota"),
    ],
)
def test_respelling_is_accepted(before: str, after: str) -> None:
    v = verify(proposal(make=after), record={**RECORD, "make": before}, documents="")
    assert v.updates["make"] == after


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("X5", "X5 xDrive40i"),
        ("Range Rover Sport", "Range Rover"),
        ("Patrol", "Patrol Nismo"),
    ],
)
def test_adding_or_dropping_a_word_is_not_normalisation(before: str, after: str) -> None:
    """Otherwise the model invents a trim level the dealer never typed and no
    document mentions."""
    v = verify(proposal(model=after), record={**RECORD, "model": before}, documents="")
    assert "model" not in v.updates
    assert "rewritten, not normalised" in v.dropped[0]


# --------------------------------------------------------------------------
# selling points
# --------------------------------------------------------------------------


def test_a_usp_grounded_in_a_populated_field_survives() -> None:
    v = verify(
        proposal(usps=[USP(text="Barely driven — 12,000 km", basis="mileage_km")]),
        record=RECORD,
        documents="",
    )
    assert len(v.usps) == 1


def test_a_usp_grounded_in_a_blank_field_is_dropped() -> None:
    v = verify(
        proposal(usps=[USP(text="Stunning in Solar Yellow", basis="exterior_color")]),
        record=RECORD,
        documents="",
    )
    assert v.usps == []


def test_a_usp_grounded_in_a_field_that_does_not_exist_is_dropped() -> None:
    v = verify(
        proposal(usps=[USP(text="Award winning", basis="awards")]),
        record=RECORD,
        documents="",
    )
    assert v.usps == []


def test_a_usp_may_cite_a_field_this_same_pass_filled() -> None:
    """Enrichment happens before USP extraction, so a spec sourced from a
    document is a legitimate basis."""
    v = verify(
        proposal(
            fills=[SpecFill(field="power_hp", value="415", quote="Maximum power: 415 hp")],
            usps=[USP(text="415 hp twin-turbo V6", basis="power_hp")],
        ),
        record=RECORD,
        documents=DOCS,
    )
    assert len(v.usps) == 1


def test_no_more_than_five_usps_reach_the_record() -> None:
    v = verify(
        proposal(usps=[USP(text=f"point {i}", basis="mileage_km") for i in range(9)]),
        record=RECORD,
        documents="",
    )
    assert len(v.usps) == 5


# --------------------------------------------------------------------------
# the acceptance test, end to end
# --------------------------------------------------------------------------

INVENTED = Enrichment(
    make="Toyota",
    model="Land Cruiser",
    fills=[
        SpecFill(
            field="power_hp",
            value="409",
            quote="The 3.5-litre twin-turbo V6 produces 409 horsepower.",
        )
    ],
    usps=[
        USP(text="409 horsepower of twin-turbo V6", basis="power_hp"),
        USP(text="Only 12,000 km from new", basis="mileage_km"),
    ],
)


class _FakeModels:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(role="model", parts=[types.Part(text=self.payload)]),
                    finish_reason=types.FinishReason.STOP,
                )
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=50, total_token_count=150
            ),
        )


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self.aio = type("Aio", (), {"models": _FakeModels(payload)})()


@pytest.fixture
def liar(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model that states a real figure it was never shown.

    409 hp is the correct answer for this car. That is exactly what makes it
    dangerous: it is right about the model in general and unverifiable for this
    dealer's stock, and the next one it states with equal confidence will be
    wrong.
    """
    monkeypatch.setattr(gateway, "_client", _FakeClient(INVENTED.model_dump_json()))


async def test_an_unsourced_fact_never_reaches_the_vehicle(
    db: None, seeded: None, su: asyncpg.Connection, liar: None
) -> None:
    """The plan's acceptance criterion for T2.5, and the codified form of
    "never invent a fact about a car".

    The tenant has no documents at all, so there is nothing the horsepower
    figure could have come from.
    """
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, mileage_km)
           values ($1, $2, 'TOYOTA', 'Land Cruiser', 12000)""",
        vehicle_id,
        TENANT_A,
    )

    verified = await enrich(tenant_id=TENANT_A, vehicle_id=vehicle_id)

    row = await su.fetchrow("select power_hp, make, specs from vehicles where id = $1", vehicle_id)
    assert row is not None
    assert row["power_hp"] is None, "an unsourced horsepower figure reached the database"
    assert row["make"] == "Toyota", "the safe half of the enrichment was still applied"

    usps = [u.text for u in verified.usps]
    assert not any("horsepower" in u.lower() or "hp" in u.lower() for u in usps)
    assert usps == ["Only 12,000 km from new"], "the grounded selling point survived"


async def test_a_sourced_fact_does_reach_the_vehicle(
    db: None, seeded: None, su: asyncpg.Connection, liar: None
) -> None:
    """The control. Without it the test above passes just as well on a function
    that writes nothing at all."""
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, mileage_km)
           values ($1, $2, 'TOYOTA', 'Land Cruiser', 12000)""",
        vehicle_id,
        TENANT_A,
    )
    await su.execute(
        """insert into documents (tenant_id, kind, status, title, content)
           values ($1, 'spec_sheet', 'ready', 'LC300', $2)""",
        TENANT_A,
        "Land Cruiser 300.\nThe 3.5-litre twin-turbo V6 produces 409 horsepower.",
    )

    await enrich(tenant_id=TENANT_A, vehicle_id=vehicle_id)

    row = await su.fetchrow("select power_hp, specs from vehicles where id = $1", vehicle_id)
    assert row is not None
    assert row["power_hp"] == 409
    filled = json.loads(row["specs"])["enrichment"]["filled"]
    assert filled[0]["quote"].startswith("The 3.5-litre"), "provenance is stored with the value"


async def test_another_tenants_document_is_not_a_source(
    db: None, seeded: None, su: asyncpg.Connection, liar: None
) -> None:
    """RLS makes this true; the test makes it stay true. A spec sheet belonging
    to one dealer must not fill in another dealer's stock."""
    from conftest import TENANT_B

    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, mileage_km)
           values ($1, $2, 'TOYOTA', 'Land Cruiser', 12000)""",
        vehicle_id,
        TENANT_A,
    )
    await su.execute(
        """insert into documents (tenant_id, kind, status, title, content)
           values ($1, 'spec_sheet', 'ready', 'LC300', $2)""",
        TENANT_B,
        "Land Cruiser 300.\nThe 3.5-litre twin-turbo V6 produces 409 horsepower.",
    )

    await enrich(tenant_id=TENANT_A, vehicle_id=vehicle_id)

    power = await su.fetchval("select power_hp from vehicles where id = $1", vehicle_id)
    assert power is None


async def test_enrichment_is_traced_like_any_other_model_call(
    db: None, seeded: None, su: asyncpg.Connection, liar: None
) -> None:
    vehicle_id = uuid.uuid4()
    await su.execute(
        "insert into vehicles (id, tenant_id, make, model) values ($1, $2, 'Kia', 'Sportage')",
        vehicle_id,
        TENANT_A,
    )
    await enrich(tenant_id=TENANT_A, vehicle_id=vehicle_id)
    name = await su.fetchval(
        "select name from agent_traces where tenant_id = $1 order by created_at desc limit 1",
        TENANT_A,
    )
    assert name == "enrichment"
