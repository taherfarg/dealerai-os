"""The highest-value test in this repository.

Tenant leakage is the one bug that ends the company, so this file blocks merge.
It checks isolation two ways:

  * structurally  — every tenant-owned table has RLS enabled AND forced AND a
                    policy. This is what catches "someone added a table and
                    forgot", which is how leaks actually happen.
  * behaviourally — real rows through the API's access path, including views.
                    The browser path is closed; see tests/test_visibility.py.

It also asserts that connecting as service_role DOES leak. A test that cannot
fail proves nothing; that case is what gives the rest of the file its teeth.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import SEEDED_TABLES, TENANT_A, TENANT_B, USER_A, jwt_session
from dealerai.db.session import tenant_session

#: Documented exceptions, isolated by GRANT rather than RLS because the worker
#: must read them before a tenant is known. See docs/03-database-schema.md § 2.
NO_RLS_BY_DESIGN = {"events", "webhook_deliveries"}


# --------------------------------------------------------------------------
# structural
# --------------------------------------------------------------------------


async def test_every_tenant_table_has_forced_rls(su: asyncpg.Connection) -> None:
    rows = await su.fetch(
        """
        select c.relname                            as table_name,
               c.relrowsecurity                     as enabled,
               c.relforcerowsecurity                as forced,
               (select count(*) from pg_policies p
                 where p.schemaname = 'public' and p.tablename = c.relname) as policies
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relkind = 'r'
          and exists (
            select 1 from information_schema.columns col
            where col.table_schema = 'public'
              and col.table_name = c.relname
              and col.column_name = 'tenant_id')
        order by c.relname
        """
    )
    assert rows, "no tenant tables found — did migrations run?"

    failures = [
        r["table_name"]
        for r in rows
        if r["table_name"] not in NO_RLS_BY_DESIGN
        and not (r["enabled"] and r["forced"] and r["policies"] > 0)
    ]
    assert not failures, (
        f"tables with a tenant_id but without forced RLS + a policy: {failures}. "
        "Add them to the RLS loop in the migration, or document them in NO_RLS_BY_DESIGN."
    )


async def test_no_rls_tables_are_unreachable_by_browser_roles(su: asyncpg.Connection) -> None:
    """The tables we exempt from RLS must not be granted to any browser role."""
    for table in NO_RLS_BY_DESIGN:
        for role in ("authenticated", "anon"):
            granted = await su.fetchval("select has_table_privilege($1, $2, 'SELECT')", role, table)
            assert not granted, f"{role} can SELECT {table}; it has no RLS to protect it"


async def test_every_view_is_security_invoker(su: asyncpg.Connection) -> None:
    """A view without security_invoker runs as its owner and bypasses RLS silently."""
    rows = await su.fetch(
        """
        select c.relname, c.reloptions
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'v'
        """
    )
    assert rows, "no views found — did migrations run?"
    bad = [
        r["relname"]
        for r in rows
        if not any("security_invoker=true" in o for o in (r["reloptions"] or []))
    ]
    assert not bad, f"views missing security_invoker=true: {bad}"


# --------------------------------------------------------------------------
# behavioural — backend path (dealerai_app + SET LOCAL app.tenant_id)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", SEEDED_TABLES)
async def test_app_path_sees_only_its_own_tenant(db: None, seeded: None, table: str) -> None:
    async with tenant_session(TENANT_A) as conn:
        mine = await conn.fetchval(
            f"select count(*) from {table} where tenant_id = $1",
            TENANT_A,  # noqa: S608
        )
        theirs = await conn.fetchval(
            f"select count(*) from {table} where tenant_id = $1",
            TENANT_B,  # noqa: S608
        )
        total = await conn.fetchval(f"select count(*) from {table}")  # noqa: S608

    assert mine >= 1, f"{table}: tenant A cannot see its own rows"
    assert theirs == 0, f"LEAK: {table} exposed tenant B rows to tenant A"
    assert total == mine, f"LEAK: {table} total ({total}) exceeds own rows ({mine})"


async def test_app_path_cannot_write_to_another_tenant(db: None, seeded: None) -> None:
    async with tenant_session(TENANT_A) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(
                "insert into vehicles (tenant_id, make, model) values ($1, 'X', 'Y')",
                TENANT_B,
            )


async def test_app_path_views_are_isolated(db: None, seeded: None) -> None:
    async with tenant_session(TENANT_A) as conn:
        rows = await conn.fetch("select distinct tenant_id from v_vehicle_stock")
        assert [r["tenant_id"] for r in rows] == [TENANT_A]

        funnel = await conn.fetch("select distinct tenant_id from v_lead_funnel")
        assert [r["tenant_id"] for r in funnel] == [TENANT_A]


async def test_tenant_context_does_not_leak_between_transactions(db: None, seeded: None) -> None:
    """SET LOCAL is transaction-scoped, so a pooled connection cannot carry a
    tenant into the next request. Plain SET would, which is why it is never used."""
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select current_setting('app.tenant_id', true)") == str(TENANT_A)

    from dealerai.db.session import system_session

    async with system_session() as conn:
        leaked = await conn.fetchval("select current_setting('app.tenant_id', true)")
        assert leaked in (None, ""), f"tenant context leaked across transactions: {leaked}"
        # With no tenant context, RLS hides everything.
        assert await conn.fetchval("select count(*) from vehicles") == 0


# --------------------------------------------------------------------------
# browser path
#
# Closed since migration 0006: anon and authenticated hold no table privileges,
# so the browser reaches tenant data only through the API.
# tests/test_visibility.py::test_browser_roles_cannot_read_any_table proves it
# for every table; the case below stays as the concrete one.
# --------------------------------------------------------------------------


async def test_unauthenticated_sees_nothing(su: asyncpg.Connection, seeded: None) -> None:
    async with jwt_session(su, uuid.uuid4(), role="anon") as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetchval("select count(*) from vehicles")


# --------------------------------------------------------------------------
# the control case
# --------------------------------------------------------------------------


async def test_service_role_does_bypass_rls(su: asyncpg.Connection, seeded: None) -> None:
    """service_role sees everything. That is exactly why no request path may use it.

    If this test ever fails, the assertions above became vacuous — they would be
    passing because nothing can read anything, not because RLS works.
    """
    async with jwt_session(su, USER_A, role="service_role") as conn:
        tenants = await conn.fetch("select distinct tenant_id from vehicles")
    assert len(tenants) == 2, (
        "service_role no longer bypasses RLS — the isolation assertions in this "
        "file may now be passing vacuously. Investigate before trusting them."
    )
