"""What 0006_sales_core.sql must be true about, before anything reads it."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import TENANT_A

NEW_TABLES = ("teams", "team_members", "contact_identities")


@pytest.mark.parametrize("table", NEW_TABLES)
async def test_new_tables_have_forced_rls(su: asyncpg.Connection, table: str) -> None:
    row = await su.fetchrow(
        """select c.relrowsecurity as enabled, c.relforcerowsecurity as forced
           from pg_class c join pg_namespace n on n.oid = c.relnamespace
           where n.nspname = 'public' and c.relname = $1""",
        table,
    )
    assert row is not None, f"{table} is missing"
    assert row["enabled"] and row["forced"], f"{table} is not protected by forced RLS"


async def test_identity_columns_moved_off_contacts(su: asyncpg.Connection) -> None:
    names = {
        r["column_name"]
        for r in await su.fetch(
            "select column_name from information_schema.columns where table_name = 'contacts'"
        )
    }
    assert {"owner_id", "team_id", "profile", "profile_updated_at"} <= names
    assert not ({"phone", "email", "external_refs"} & names), (
        "phone, email and platform ids belong in contact_identities, where a unique index can "
        "stop two webhooks creating two customers"
    )


async def test_one_identity_value_belongs_to_one_customer(
    su: asyncpg.Connection, seeded: None
) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    for contact_id in (first, second):
        await su.execute(
            "insert into contacts (id, tenant_id, full_name) values ($1, $2, 'x')",
            contact_id,
            TENANT_A,
        )
    await su.execute(
        """insert into contact_identities (tenant_id, contact_id, kind, value)
           values ($1, $2, 'whatsapp_user_id', 'AE.123')""",
        TENANT_A,
        first,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value)
               values ($1, $2, 'whatsapp_user_id', 'AE.123')""",
            TENANT_A,
            second,
        )


async def test_a_phone_identity_must_be_e164(su: asyncpg.Connection, seeded: None) -> None:
    contact_id = uuid.uuid4()
    await su.execute(
        "insert into contacts (id, tenant_id, full_name) values ($1, $2, 'x')",
        contact_id,
        TENANT_A,
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await su.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value)
               values ($1, $2, 'phone', '0501234567')""",
            TENANT_A,
            contact_id,
        )


async def test_manager_is_a_valid_role(su: asyncpg.Connection, seeded: None) -> None:
    user_id = uuid.uuid4()
    await su.execute("insert into auth.users (id, email) values ($1, 'm@example.test')", user_id)
    try:
        await su.execute(
            "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'manager')",
            TENANT_A,
            user_id,
        )
    finally:
        await su.execute("delete from auth.users where id = $1", user_id)
