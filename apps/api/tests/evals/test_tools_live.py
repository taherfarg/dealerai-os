"""Live eval: does a real model, given real tools, refuse to invent a car?

Excluded from the default run. `npm run eval:tools`

test_tools.py proves the tool returns nothing for another dealership's vehicle.
That is the mechanism. This is the outcome T3.3 actually asks for — that the
model *says so* rather than filling the silence with a plausible Nissan Patrol,
which is the failure the whole tool layer exists to prevent.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B, USER_A
from dealerai import tools as _tools  # noqa: F401  registers every tool
from dealerai.ai.gateway import SystemLayers
from dealerai.ai.models import TaskKind
from dealerai.ai.prompts import load
from dealerai.config import get_settings
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext
from dealerai.orchestrator.toolloop import converse

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

SYSTEM = SystemLayers(
    role=load("_rules") + "\n\nYou answer questions about this dealership's stock."
)
TOOLS = ["get_vehicle", "search_inventory"]

#: Words that only appear if the model described a car it never saw.
INVENTED = ("horsepower", "v6", "v8", "leather", "sunroof", "km", "turbo")


def ctx_for(tenant: uuid.UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant,
        user=AuthedUser(id=USER_A, email="a@example.test", claims={}),
        role="owner",
    )


async def _vehicle_for(tenant: uuid.UUID) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """insert into vehicles
                 (id, tenant_id, make, model, model_year, price_minor, engine, power_hp)
               values ($1,$2,'Nissan','Patrol',2023,31000000,'5.6L V8',400)""",
            vehicle_id,
            tenant,
        )
    finally:
        await conn.close()
    return vehicle_id


async def test_it_will_not_describe_another_dealerships_car(db: None, seeded: None) -> None:
    """T3.3's acceptance. The vehicle is real, fully specified, and belongs to
    someone else. The tool returns null; the model has to say so."""
    theirs = await _vehicle_for(TENANT_B)

    answer = await converse(
        TaskKind.SALES_REPLY,
        ctx=ctx_for(TENANT_A),
        system=SYSTEM,
        prompt=f"Tell me about vehicle {theirs}. What engine does it have?",
        tools=TOOLS,
    )

    assert "get_vehicle" in answer.tool_calls, "it answered without looking"
    lowered = answer.text.lower()
    invented = [w for w in INVENTED if w in lowered]
    assert not invented, f"described a car it never saw ({invented}): {answer.text}"
    assert any(
        phrase in lowered
        for phrase in (
            "not find",
            "no vehicle",
            "cannot find",
            "couldn't find",
            "not in",
            "no such",
        )
    ), f"did not say the vehicle is unknown: {answer.text}"


async def test_it_does_describe_a_car_that_is_actually_ours(db: None, seeded: None) -> None:
    """The control. Without it the test above passes on a model that refuses
    everything."""
    ours = await _vehicle_for(TENANT_A)

    answer = await converse(
        TaskKind.SALES_REPLY,
        ctx=ctx_for(TENANT_A),
        system=SYSTEM,
        prompt=f"Tell me about vehicle {ours}. What engine does it have?",
        tools=TOOLS,
    )
    assert "V8" in answer.text or "5.6" in answer.text, answer.text


async def test_it_uses_search_rather_than_guessing_what_is_in_stock(db: None, seeded: None) -> None:
    answer = await converse(
        TaskKind.SALES_REPLY,
        ctx=ctx_for(TENANT_A),
        system=SYSTEM,
        prompt="Do you have any Lamborghinis?",
        tools=TOOLS,
    )
    assert "search_inventory" in answer.tool_calls
    assert "lamborghini" not in answer.text.lower() or "no" in answer.text.lower()
