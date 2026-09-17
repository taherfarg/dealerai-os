"""Who can see whose customers. The second-highest-value test in the repository.

Tenant isolation (test_tenant_isolation.py) stops one dealership reading
another. This file stops one salesperson reading another salesperson's
customers inside the same dealership — enforced by the same mechanism, one
level down: the session states who is asking, and RLS filters.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
import pytest

from conftest import MANAGER, OWNER, SALES_1, SALES_X, TENANT_A, USER_A
from dealerai.db.session import system_session, tenant_session


async def test_scope_and_user_reach_the_database(db: None, seeded: None) -> None:
    async with tenant_session(TENANT_A, user_id=USER_A, scope="own") as conn:
        assert await conn.fetchval("select app.current_user_id()") == USER_A
        assert await conn.fetchval("select current_setting('app.scope', true)") == "own"
        assert await conn.fetchval("select app.visible_owner_ids()") == [USER_A]


async def test_scope_all_means_no_owner_filter(db: None, seeded: None) -> None:
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select app.visible_owner_ids()") is None


async def test_an_unknown_scope_is_refused_before_it_reaches_sql(db: None) -> None:
    with pytest.raises(ValueError, match="scope"):
        async with tenant_session(TENANT_A, scope="everything"):
            pass


async def test_the_session_does_not_leak_a_user_into_the_next_transaction(
    db: None, seeded: None
) -> None:
    async with tenant_session(TENANT_A, user_id=USER_A, scope="own"):
        pass
    async with system_session() as conn:
        assert await conn.fetchval("select current_setting('app.user_id', true)") in (None, "")


# --------------------------------------------------------------------------
# the matrix
# --------------------------------------------------------------------------

#: (viewer, scope, customers they must see, customers they must not see)
MATRIX = (
    (OWNER, "all", ("s1", "s2", "covered", "x", "pool_local", "pool_export"), ()),
    (MANAGER, "team", ("s1", "s2", "covered", "pool_local"), ("x", "pool_export")),
    (SALES_1, "own", ("s1", "covered", "pool_local"), ("s2", "x", "pool_export")),
    (SALES_X, "own", ("x", "pool_export"), ("s1", "s2", "covered", "pool_local")),
)


@pytest.mark.parametrize(("viewer", "scope", "visible", "hidden"), MATRIX)
async def test_who_sees_which_customers(
    db: None,
    visibility_seed: dict[str, UUID],
    viewer: UUID,
    scope: str,
    visible: tuple[str, ...],
    hidden: tuple[str, ...],
) -> None:
    async with tenant_session(TENANT_A, user_id=viewer, scope=scope) as conn:
        seen = {r["id"] for r in await conn.fetch("select id from contacts")}
    for key in visible:
        assert visibility_seed[key] in seen, f"{key} should be visible with scope {scope}"
    for key in hidden:
        assert visibility_seed[key] not in seen, f"LEAK: {key} visible with scope {scope}"


@pytest.mark.parametrize(("viewer", "scope", "visible", "hidden"), MATRIX)
async def test_conversations_and_leads_follow_the_customer(
    db: None,
    visibility_seed: dict[str, UUID],
    viewer: UUID,
    scope: str,
    visible: tuple[str, ...],
    hidden: tuple[str, ...],
) -> None:
    async with tenant_session(TENANT_A, user_id=viewer, scope=scope) as conn:
        conversations = {
            r["contact_id"] for r in await conn.fetch("select contact_id from conversations")
        }
        leads = {r["contact_id"] for r in await conn.fetch("select contact_id from leads")}
    for key in visible:
        assert visibility_seed[key] in conversations, f"{key}'s conversation should be visible"
    for key in hidden:
        assert visibility_seed[key] not in conversations, f"LEAK: {key}'s conversation is visible"
        assert visibility_seed[key] not in leads, f"LEAK: {key}'s lead is visible"


async def test_messages_follow_their_conversation(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, UUID]
) -> None:
    for key in ("s1", "s2"):
        conversation_id = await su.fetchval(
            "select id from conversations where contact_id = $1", visibility_seed[key]
        )
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, body)
               values ($1, $2, 'in', 'customer', $3)""",
            TENANT_A,
            conversation_id,
            f"secret of {key}",
        )
    async with tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        bodies = {r["body"] for r in await conn.fetch("select body from messages")}
    assert "secret of s1" in bodies
    assert "secret of s2" not in bodies, "LEAK: a salesperson read a colleague's customer messages"


async def test_identities_follow_their_customer(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, UUID]
) -> None:
    for key, phone in (("s1", "+971500000001"), ("s2", "+971500000002")):
        await su.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value)
               values ($1, $2, 'phone', $3)""",
            TENANT_A,
            visibility_seed[key],
            phone,
        )
    async with tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        phones = {r["value"] for r in await conn.fetch("select value from contact_identities")}
    assert "+971500000001" in phones
    assert "+971500000002" not in phones, "LEAK: a colleague's customer phone number is visible"


async def test_turning_the_pool_off_hides_unassigned_customers(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, UUID]
) -> None:
    await su.execute(
        """update tenants set sales_settings =
             jsonb_set(sales_settings, '{unassigned_visible_to_sales}', 'false')
           where id = $1""",
        TENANT_A,
    )
    async with tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        seen = {r["id"] for r in await conn.fetch("select id from contacts")}
    assert visibility_seed["s1"] in seen
    assert visibility_seed["pool_local"] not in seen


async def test_the_worker_still_sees_everything(db: None, visibility_seed: dict[str, UUID]) -> None:
    """Handlers act on rows already routed; a scoped worker would silently skip work."""
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select count(*) from contacts") >= 6


# --------------------------------------------------------------------------
# the browser path is closed
# --------------------------------------------------------------------------


async def test_browser_roles_cannot_read_any_table(su: asyncpg.Connection) -> None:
    """The API is the only data path, so anon and authenticated have no business
    reaching tables directly. Visibility is enforced where the API sets the
    scope; leaving PostgREST open would be a second, weaker door."""
    tables = [
        r["tablename"]
        for r in await su.fetch("select tablename from pg_tables where schemaname = 'public'")
    ]
    assert tables, "no tables found — did migrations run?"
    leaks = []
    for table in tables:
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if await su.fetchval(
                    "select has_table_privilege($1, $2, $3)", role, f"public.{table}", privilege
                ):
                    leaks.append(f"{role} can {privilege} {table}")
    assert not leaks, "browser roles still reach tables directly: " + ", ".join(leaks)
