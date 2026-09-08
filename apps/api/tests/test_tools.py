"""The tool layer.

The registry half is pure. The tool half runs against Postgres, because the
property that matters — an agent cannot see another dealership's cars — is
enforced by RLS, and a test with a stubbed database would prove nothing about
it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B, USER_A, reseed
from dealerai import tools as _tools  # noqa: F401  registers every tool
from dealerai.config import get_settings
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext
from dealerai.tools import registry
from dealerai.tools.registry import ToolError, tool

# --------------------------------------------------------------------------
# the registry — pure
# --------------------------------------------------------------------------


@pytest.fixture
def clean_registry() -> Iterator[None]:
    saved = dict(registry._REGISTRY)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)


def test_a_declaration_is_generated_from_the_signature() -> None:
    schema = registry.get("search_inventory").declaration().parameters_json_schema
    assert set(schema["properties"]) == {
        "make",
        "model",
        "max_price_minor",
        "min_days_in_stock",
        "limit",
    }


def test_the_tenant_context_is_never_offered_to_the_model() -> None:
    """The model does not choose which dealership it is acting for. A tenant id
    it could name is a tenant id it could name wrongly."""
    for name in registry.names():
        schema = registry.get(name).declaration().parameters_json_schema
        assert "ctx" not in schema.get("properties", {}), f"{name} exposes ctx"


def test_the_docstring_is_what_the_model_reads() -> None:
    declaration = registry.get("get_vehicle").declaration()
    assert "Returns null if this dealership has no such vehicle" in declaration.description


def test_a_tool_without_a_docstring_is_refused(clean_registry: None) -> None:
    with pytest.raises(TypeError, match="needs a docstring"):

        @tool(name="undocumented", group="test")
        async def undocumented(ctx: TenantContext) -> None: ...


def test_a_positional_parameter_is_refused(clean_registry: None) -> None:
    """The model supplies arguments by name; a positional one is a parameter the
    declaration cannot describe."""
    with pytest.raises(TypeError, match="must be keyword-only"):

        @tool(name="positional", group="test")
        async def positional(ctx: TenantContext, thing: str) -> None:
            """Does a thing."""


def test_an_unannotated_parameter_is_refused(clean_registry: None) -> None:
    with pytest.raises(TypeError, match="needs a type annotation"):

        @tool(name="untyped", group="test")
        async def untyped(ctx: TenantContext, *, thing) -> None:  # type: ignore[no-untyped-def]
            """Does a thing."""


def test_a_duplicate_name_is_refused(clean_registry: None) -> None:
    with pytest.raises(ValueError, match="already registered"):

        @tool(name="get_vehicle", group="test")
        async def clash(ctx: TenantContext) -> None:
            """Clashes."""


def test_declarations_reject_a_tool_that_does_not_exist() -> None:
    with pytest.raises(ValueError, match="no such tool: teleport"):
        registry.declarations(["get_vehicle", "teleport"])


def test_declarations_are_ordered_so_the_cache_prefix_is_stable() -> None:
    """Tools are part of the cached prefix; a non-deterministic order silently
    destroys every cache hit."""
    first = registry.declarations(["get_vehicle", "search_inventory"])
    second = registry.declarations(["search_inventory", "get_vehicle"])
    assert [d.name for d in first[0].function_declarations] == [
        d.name for d in second[0].function_declarations
    ]


def test_an_empty_tool_list_produces_no_tool_block() -> None:
    assert registry.declarations([]) == []


def test_groups_are_how_least_privilege_is_expressed() -> None:
    """An agent's tools are fixed in code. The copywriter is given the brand
    group and not the publish group, and no prompt can change that."""
    assert "create_draft" in registry.in_group("content")
    assert "create_draft" not in registry.in_group("inventory")


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------


def ctx_for(tenant: uuid.UUID = TENANT_A) -> TenantContext:
    return TenantContext(
        tenant_id=tenant,
        user=AuthedUser(id=USER_A, email="a@example.test", claims={}),
        role="owner",
    )


@pytest.fixture
def clean(_migrated: None) -> None:
    asyncio.run(reseed())


async def test_a_bad_argument_comes_back_as_something_the_model_can_read(
    db: None, clean: None
) -> None:
    """Not a stack trace. The model is the one that has to recover."""
    with pytest.raises(ToolError, match="limit"):
        await registry.call("search_inventory", ctx_for(), {"limit": "twenty"})


async def test_calling_a_tool_that_does_not_exist_is_a_tool_error(db: None, clean: None) -> None:
    with pytest.raises(ToolError, match="no tool called"):
        await registry.call("teleport", ctx_for(), {})


async def test_every_call_is_traced(db: None, clean: None) -> None:
    await registry.call("search_inventory", ctx_for(), {})
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        row = await conn.fetchrow(
            """select kind, name, status, payload from agent_traces
                where tenant_id = $1 and kind = 'tool' order by created_at desc limit 1""",
            TENANT_A,
        )
    finally:
        await conn.close()
    assert row is not None
    assert row["name"] == "search_inventory"
    assert row["status"] == "ok"


async def test_a_failing_tool_is_traced_as_an_error(
    db: None, clean: None, clean_registry: None
) -> None:
    @tool(name="explode", group="test")
    async def explode(ctx: TenantContext) -> None:
        """Always fails."""
        raise ToolError("nope")

    with pytest.raises(ToolError):
        await registry.call("explode", ctx_for(), {})

    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        row = await conn.fetchrow(
            "select status, error from agent_traces where name = 'explode' limit 1"
        )
    finally:
        await conn.close()
    assert row is not None
    assert row["status"] == "error"
    assert row["error"] == "nope"


# --------------------------------------------------------------------------
# the acceptance property: an agent cannot reach another dealership's cars
# --------------------------------------------------------------------------


async def _vehicle_for(tenant: uuid.UUID, **fields: Any) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """insert into vehicles (id, tenant_id, make, model, price_minor, status)
               values ($1,$2,$3,$4,$5,$6)""",
            vehicle_id,
            tenant,
            fields.get("make", "Nissan"),
            fields.get("model", "Patrol"),
            fields.get("price_minor", 31000000),
            fields.get("status", "available"),
        )
    finally:
        await conn.close()
    return vehicle_id


async def test_another_tenants_vehicle_simply_does_not_exist(db: None, clean: None) -> None:
    """T3.3's acceptance, at the layer that enforces it. The tool does not
    reject the request — RLS means the row is not there to return, which is why
    there is no check here that someone can forget to write."""
    theirs = await _vehicle_for(TENANT_B)
    assert (
        await registry.call("get_vehicle", ctx_for(TENANT_A), {"vehicle_id": str(theirs)}) is None
    )


async def test_the_same_vehicle_is_visible_to_its_own_tenant(db: None, clean: None) -> None:
    """The control. Without it the test above passes on a tool that always
    returns None."""
    theirs = await _vehicle_for(TENANT_B)
    found = await registry.call("get_vehicle", ctx_for(TENANT_B), {"vehicle_id": str(theirs)})
    assert found is not None
    assert found["make"] == "Nissan"


async def test_search_never_crosses_tenants(db: None, clean: None) -> None:
    await _vehicle_for(TENANT_B, make="Lamborghini", model="Urus")
    results = await registry.call("search_inventory", ctx_for(TENANT_A), {"make": "Lamborghini"})
    assert results == []


async def test_a_malformed_id_is_not_found_rather_than_an_error(db: None, clean: None) -> None:
    """A model will pass "the blue one". Returning null lets it recover; raising
    ends the task."""
    assert await registry.call("get_vehicle", ctx_for(), {"vehicle_id": "the blue one"}) is None
    assert await registry.call("get_vehicle_media", ctx_for(), {"vehicle_id": "nope"}) == []
    assert await registry.call("days_in_stock", ctx_for(), {"vehicle_id": "nope"}) is None
    assert await registry.call("price_history", ctx_for(), {"vehicle_id": "nope"}) == []


# --------------------------------------------------------------------------
# what a customer-facing agent may see
# --------------------------------------------------------------------------


async def test_the_discount_floor_is_never_returned(db: None, clean: None) -> None:
    """An agent that can read min_price will reason its way down to it. It is
    told a limit it may go to; it never sees the floor itself."""
    vehicle_id = await _vehicle_for(TENANT_A)
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "update vehicles set min_price_minor = 28000000 where id = $1", vehicle_id
        )
    finally:
        await conn.close()

    found = await registry.call("get_vehicle", ctx_for(), {"vehicle_id": str(vehicle_id)})
    assert "min_price_minor" not in found
    assert "min_price" not in found

    listed = await registry.call("search_inventory", ctx_for(), {})
    assert all("min_price_minor" not in v for v in listed)


async def test_search_returns_only_available_stock(db: None, clean: None) -> None:
    """A sold car offered to a customer costs the dealer the sale and the trust,
    so the tool cannot be asked for one."""
    await _vehicle_for(TENANT_A, make="Ferrari", status="sold")
    assert await registry.call("search_inventory", ctx_for(), {"make": "Ferrari"}) == []


async def test_search_caps_a_greedy_limit(db: None, clean: None) -> None:
    """The model asked for 5000 rows. It does not get them into its context."""
    results = await registry.call("search_inventory", ctx_for(), {"limit": 5000})
    assert len(results) <= 50


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


async def test_a_draft_is_created_as_a_draft(db: None, clean: None) -> None:
    """Nothing in the content group publishes. Publishing is a separate group an
    agent has to be given explicitly."""
    created = await registry.call(
        "create_draft",
        ctx_for(),
        {"kind": "post", "concept": "hero shot", "caption": "A very fine car."},
    )
    assert created["status"] == "draft"

    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        copy = await conn.fetchval(
            "select caption from content_copy where content_item_id = $1", uuid.UUID(created["id"])
        )
        audited = await conn.fetchval(
            "select action from audit_log where entity_id = $1", uuid.UUID(created["id"])
        )
    finally:
        await conn.close()
    assert copy == "A very fine car."
    assert audited == "content.draft_created", "a mutating tool is answerable, not just traced"


async def test_a_draft_with_an_unusable_vehicle_id_still_gets_made(db: None, clean: None) -> None:
    created = await registry.call(
        "create_draft", ctx_for(), {"kind": "post", "concept": "x", "vehicle_id": "not-a-uuid"}
    )
    assert created["status"] == "draft"


async def _confirm_brand(**fields: Any) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """insert into brand_profiles
                 (tenant_id, display_name, forbidden_terms, cta_styles, required_disclaimers)
               values ($1,$2,$3,$4,$5)
               on conflict (tenant_id) do update set
                 display_name = excluded.display_name,
                 forbidden_terms = excluded.forbidden_terms,
                 cta_styles = excluded.cta_styles,
                 required_disclaimers = excluded.required_disclaimers""",
            TENANT_A,
            fields.get("display_name", "Alpha Motors"),
            fields.get("forbidden_terms", []),
            json.dumps(fields.get("cta_styles", [])),
            json.dumps(fields.get("required_disclaimers", {})),
        )
    finally:
        await conn.close()


async def test_an_unconfirmed_brand_says_so_rather_than_inventing_a_voice(
    db: None, clean: None
) -> None:
    profile = await registry.call("get_brand_profile", ctx_for(), {})
    assert profile["confirmed"] is False
    assert profile["name"] == "Alpha", "it still knows the dealership's name"


async def test_only_this_markets_disclaimer_is_returned(db: None, clean: None) -> None:
    """Handing the model every country's wording invites it to pick the wrong
    one, which is a legal problem rather than a style one."""
    await _confirm_brand(required_disclaimers={"AE": "Prices exclude registration.", "SA": "Other"})
    profile = await registry.call("get_brand_profile", ctx_for(), {})
    assert profile["required_disclaimer"] == "Prices exclude registration."


async def test_cta_styles_are_read_in_either_shape(db: None, clean: None) -> None:
    """The onboarding screen has written both. A guard that silently stops
    matching is worse than one that never ran."""
    await _confirm_brand(cta_styles=["DM to book", {"text": "Visit us"}])
    profile = await registry.call("get_brand_profile", ctx_for(), {})
    assert profile["ctas"] == ["DM to book", "Visit us"]


async def test_brand_rules_can_be_checked_before_a_caption_is_finished(
    db: None, clean: None
) -> None:
    await _confirm_brand(forbidden_terms=["bargain"], cta_styles=["DM to book"])

    bad = await registry.call("check_brand_rules", ctx_for(), {"text": "What a bargain!"})
    assert bad["ok"] is False
    assert {p["detail"] for p in bad["problems"]} == {"bargain", "DM to book"}

    good = await registry.call("check_brand_rules", ctx_for(), {"text": "A fine car. DM to book."})
    assert good["ok"] is True
