from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

from dealerai.config import get_settings
from dealerai.db import session
from dealerai.scripts.migrate import run as run_migrations

TENANT_A = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")
USER_A = uuid.UUID("aaaaaaaa-1111-4000-8000-000000000001")
USER_B = uuid.UUID("bbbbbbbb-1111-4000-8000-000000000002")

#: Tables the behavioural isolation tests seed and assert against. The
#: structural test (test_every_tenant_table_has_forced_rls) covers the rest —
#: it catches the real regression, which is "someone added a table and forgot".
SEEDED_TABLES = (
    "vehicles",
    "contacts",
    "conversations",
    "messages",
    "leads",
    "content_items",
    "agent_runs",
)


@pytest.fixture(scope="session", autouse=True)
def _migrated() -> None:
    assert asyncio.run(run_migrations()) == 0, "migrations failed"
    asyncio.run(_grant_service_role())


async def _grant_service_role() -> None:
    """Reproduce Supabase's service_role table grants on the local container.

    Supabase ships these; the local shim cannot, because it runs before any
    table exists. Without them the control test (test_service_role_does_bypass_rls)
    would fail on a permission error rather than proving that BYPASSRLS is what
    lets service_role read across tenants.
    """
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "grant select, insert, update, delete on all tables in schema public to service_role"
        )
    finally:
        await conn.close()


@pytest.fixture
async def su() -> AsyncIterator[asyncpg.Connection]:
    """Superuser connection. Bypasses RLS — used only to seed and to inspect."""
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def db() -> AsyncIterator[None]:
    """The real application pool, connected as the NOBYPASSRLS dealerai_app role."""
    await session.init_pool()
    try:
        yield
    finally:
        await session.close_pool()


async def _wipe(conn: asyncpg.Connection) -> None:
    await conn.execute("delete from tenants")
    await conn.execute("delete from auth.users where id = any($1::uuid[])", [USER_A, USER_B])


async def _seed_tenant(
    conn: asyncpg.Connection, tenant_id: uuid.UUID, user_id: uuid.UUID, slug: str
) -> None:
    await conn.execute(
        "insert into tenants (id, slug, name) values ($1, $2, $3)",
        tenant_id,
        slug,
        slug.title(),
    )
    await conn.execute(
        "insert into auth.users (id, email) values ($1, $2)", user_id, f"{slug}@example.test"
    )
    await conn.execute(
        "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'owner')",
        tenant_id,
        user_id,
    )
    await conn.execute(
        """insert into vehicles (id, tenant_id, make, model, price_minor)
           values ($1, $2, 'MG', 'MG6', 6600000)""",
        uuid.uuid4(),
        tenant_id,
    )
    contact_id = uuid.uuid4()
    await conn.execute(
        "insert into contacts (id, tenant_id, full_name) values ($1, $2, $3)",
        contact_id,
        tenant_id,
        f"{slug} customer",
    )
    conversation_id = uuid.uuid4()
    await conn.execute(
        """insert into conversations (id, tenant_id, contact_id, surface)
           values ($1, $2, $3, 'whatsapp')""",
        conversation_id,
        tenant_id,
        contact_id,
    )
    await conn.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, body)
           values ($1, $2, 'in', 'customer', $3)""",
        tenant_id,
        conversation_id,
        f"secret of {slug}",
    )
    await conn.execute(
        "insert into leads (tenant_id, contact_id, stage) values ($1, $2, 'new')",
        tenant_id,
        contact_id,
    )
    await conn.execute("insert into content_items (tenant_id, kind) values ($1, 'post')", tenant_id)
    await conn.execute(
        """insert into agent_runs (tenant_id, trigger_type, autonomy)
           values ($1, 'user', 'copilot')""",
        tenant_id,
    )


async def reseed() -> None:
    """Reset to two tenants, on a connection of its own.

    Callable from sync tests via asyncio.run — route tests drive TestClient,
    which is synchronous and therefore cannot consume an async fixture.
    """
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await _wipe(conn)
        await _seed_tenant(conn, TENANT_A, USER_A, "alpha")
        await _seed_tenant(conn, TENANT_B, USER_B, "beta")
    finally:
        await conn.close()


async def wipe_all() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await _wipe(conn)
    finally:
        await conn.close()


@pytest.fixture
async def seeded(su: asyncpg.Connection) -> AsyncIterator[None]:
    await _wipe(su)
    await _seed_tenant(su, TENANT_A, USER_A, "alpha")
    await _seed_tenant(su, TENANT_B, USER_B, "beta")
    yield
    await _wipe(su)


class jwt_session:
    """Simulate the browser path exactly as PostgREST does it.

    PostgREST opens a transaction, issues `set local role authenticated` and
    `set local request.jwt.claims`, then runs the query. auth.uid() reads the
    sub claim out of that GUC. Reproducing it here means the JWT-path assertions
    exercise the same policy branch a real browser request would.
    """

    def __init__(self, conn: asyncpg.Connection, user_id: uuid.UUID, role: str = "authenticated"):
        self._conn = conn
        self._user_id = user_id
        self._role = role
        self._tx: asyncpg.transaction.Transaction | None = None

    async def __aenter__(self) -> asyncpg.Connection:
        self._tx = self._conn.transaction()
        await self._tx.start()
        await self._conn.execute(
            "select set_config('request.jwt.claims', $1, true)",
            json.dumps({"sub": str(self._user_id), "role": self._role}),
        )
        await self._conn.execute(f"set local role {self._role}")
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        assert self._tx is not None
        await self._tx.rollback()
