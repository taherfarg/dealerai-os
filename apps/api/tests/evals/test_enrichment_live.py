"""Live eval: does the real model quote well enough to be verifiable?

Excluded from the default run. `npm run eval:enrichment`

The unit tests prove `verify()` drops what it cannot ground. They cannot prove
the useful half — that a real model returns a quote copied character for
character rather than a tidied paraphrase. If it paraphrases, every fill is
dropped and enrichment becomes an expensive no-op that fills nothing and
reports nothing wrong. That is the failure this file exists to catch.

The other half: given a document that says nothing about torque, does the model
volunteer the figure it knows anyway? `verify()` would catch it either way, so
this measures the prompt, not the safety.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.agents.content.enrichment import enrich
from dealerai.config import get_settings

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

SPEC_SHEET = """Nissan Patrol Y62 — dealer specification sheet

Bodystyle              Full-size SUV, five doors
Engine                 5.6-litre V8 petrol
Maximum power          400 hp
Transmission           7-speed automatic
Drive                  Four-wheel drive
Seating capacity       8

Colours available on request. Prices on application.
"""


async def _vehicle(su: asyncpg.Connection, **overrides: object) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, model_year, mileage_km)
           values ($1, $2, 'NISSAN', 'Patrol', 2023, 18000)""",
        vehicle_id,
        TENANT_A,
    )
    return vehicle_id


async def test_a_real_spec_sheet_actually_fills_fields(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """The quote-matching check has to be survivable by a real model.

    If this fails while the unit tests pass, the verifier is too strict — not
    the model too loose — and the fix is in `_squash`, never in loosening the
    grounding rule itself.
    """
    vehicle_id = await _vehicle(su)
    await su.execute(
        """insert into documents (tenant_id, kind, status, title, content)
           values ($1, 'spec_sheet', 'ready', 'Patrol Y62 specification', $2)""",
        TENANT_A,
        SPEC_SHEET,
    )

    verified = await enrich(tenant_id=TENANT_A, vehicle_id=vehicle_id)

    assert verified.updates, f"nothing survived verification. dropped: {verified.dropped}"
    row = await su.fetchrow(
        "select power_hp, seats, transmission from vehicles where id = $1", vehicle_id
    )
    assert row is not None
    assert row["power_hp"] == 400, f"power not filled from a sheet that states it: {verified}"
    assert row["seats"] == 8


async def test_what_the_documents_omit_stays_null(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """Torque is absent from the sheet and famous for this engine. The model
    knows it; the record must not learn it."""
    vehicle_id = await _vehicle(su)
    await su.execute(
        """insert into documents (tenant_id, kind, status, title, content)
           values ($1, 'spec_sheet', 'ready', 'Patrol Y62 specification', $2)""",
        TENANT_A,
        SPEC_SHEET,
    )

    await enrich(tenant_id=TENANT_A, vehicle_id=vehicle_id)

    torque = await su.fetchval("select torque_nm from vehicles where id = $1", vehicle_id)
    assert torque is None


async def test_selling_points_are_written_and_grounded(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _vehicle(su)
    verified = await enrich(tenant_id=TENANT_A, vehicle_id=vehicle_id)

    assert len(verified.usps) >= 2, f"no usable selling points: {verified.dropped}"
    for usp in verified.usps:
        assert usp.text.strip()
        assert usp.basis in ("make", "model", "model_year", "mileage_km", "vehicle_condition")
