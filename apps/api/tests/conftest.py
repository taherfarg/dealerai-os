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

#: People and teams for the visibility matrix (tests/test_visibility.py).
OWNER = uuid.UUID("cccccccc-1111-4000-8000-000000000001")
MANAGER = uuid.UUID("cccccccc-1111-4000-8000-000000000002")
SALES_1 = uuid.UUID("cccccccc-1111-4000-8000-000000000003")
SALES_2 = uuid.UUID("cccccccc-1111-4000-8000-000000000004")
SALES_X = uuid.UUID("cccccccc-1111-4000-8000-000000000005")
TEAM_LOCAL = uuid.UUID("dddddddd-1111-4000-8000-000000000001")
TEAM_EXPORT = uuid.UUID("dddddddd-1111-4000-8000-000000000002")
PEOPLE_IDS = [OWNER, MANAGER, SALES_1, SALES_2, SALES_X]

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


LOCAL_HOSTS = ("localhost", "127.0.0.1", "@db:", "@db/")


def assert_database_is_local() -> None:
    """Refuse to run the suite against anything but a local database.

    conftest's _wipe() issues `delete from tenants`, which cascades to every
    row a dealership owns. Pointed at a real Supabase project — one stray
    DATABASE_URL edit — that is the whole customer's data, gone, from a
    command someone ran to check a test.
    """
    settings = get_settings()
    for dsn in (settings.database_url, settings.migration_dsn):
        if not any(h in dsn for h in LOCAL_HOSTS):
            raise RuntimeError(
                "REFUSING TO RUN: the test suite deletes every tenant, and "
                f"{dsn.split('@')[-1]} is not a local database. "
                "Point DATABASE_URL and MIGRATION_DATABASE_URL at the docker "
                "container (localhost:54332). A Supabase project belongs in "
                "staging config, never in test config."
            )
    if settings.env != "local":
        raise RuntimeError(f"REFUSING TO RUN: ENV is {settings.env!r}, expected 'local'")


@pytest.fixture(scope="session")
def _migrated() -> None:
    """Not autouse: the gate, money and contract suites are pure logic and must
    stay runnable with no database at all. Only fixtures that touch Postgres
    request this."""
    assert_database_is_local()
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
async def su(_migrated: None) -> AsyncIterator[asyncpg.Connection]:
    """Superuser connection. Bypasses RLS — used only to seed and to inspect."""
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def db(_migrated: None) -> AsyncIterator[None]:
    """The real application pool, connected as the NOBYPASSRLS dealerai_app role."""
    await session.init_pool()
    try:
        yield
    finally:
        await session.close_pool()


async def _wipe(conn: asyncpg.Connection) -> None:
    await conn.execute("delete from tenants")
    await conn.execute(
        "delete from auth.users where id = any($1::uuid[])", [USER_A, USER_B, *PEOPLE_IDS]
    )


#: The stages a new workspace starts with (docs/sales/02-data-model.md § 2).
DEFAULT_STAGES = (
    ("New", "open"),
    ("Contacted", "open"),
    ("Qualified", "open"),
    ("Won", "won"),
    ("Lost", "lost"),
)


async def _default_board(
    conn: asyncpg.Connection, tenant_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """The default pipeline and its first open stage.

    A lead cannot exist without a stage to sit on, so the fixtures create the
    same board routes/tenants.py gives a real workspace.
    """
    pipeline_id = await conn.fetchval(
        """insert into pipelines (tenant_id, name, is_default) values ($1, 'Sales', true)
           returning id""",
        tenant_id,
    )
    first_open: uuid.UUID | None = None
    for position, (name, category) in enumerate(DEFAULT_STAGES):
        stage_id = await conn.fetchval(
            """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
               values ($1, $2, $3, $4, $5) returning id""",
            tenant_id,
            pipeline_id,
            name,
            position,
            category,
        )
        if category == "open" and first_open is None:
            first_open = stage_id
    assert first_open is not None
    return pipeline_id, first_open


async def _open_board(
    conn: asyncpg.Connection, tenant_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """The board a workspace already has, and where a new lead lands on it."""
    row = await conn.fetchrow(
        """select p.id as pipeline_id, s.id as stage_id
             from pipelines p
             join pipeline_stages s on s.pipeline_id = p.id and s.category = 'open'
            where p.tenant_id = $1
            order by p.is_default desc, p.position, s.position
            limit 1""",
        tenant_id,
    )
    assert row is not None, "seed the tenant before its customers"
    return row["pipeline_id"], row["stage_id"]


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
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
           values ($1, $2, 'in', 'customer', 'customer', $3)""",
        tenant_id,
        conversation_id,
        f"secret of {slug}",
    )
    pipeline_id, stage_id = await _default_board(conn, tenant_id)
    await conn.execute(
        """insert into leads (tenant_id, contact_id, pipeline_id, stage_id)
           values ($1, $2, $3, $4)""",
        tenant_id,
        contact_id,
        pipeline_id,
        stage_id,
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


# --------------------------------------------------------------------------
# people, teams and customers for the visibility matrix
# --------------------------------------------------------------------------


async def _seed_people(conn: asyncpg.Connection) -> None:
    people = (
        (OWNER, "owner", "owner"),
        (MANAGER, "manager", "manager"),
        (SALES_1, "sales1", "sales"),
        (SALES_2, "sales2", "sales"),
        (SALES_X, "salesx", "sales"),
    )
    for user_id, name, role in people:
        await conn.execute(
            "insert into auth.users (id, email) values ($1, $2)", user_id, f"{name}@example.test"
        )
        await conn.execute(
            "insert into profiles (id, full_name, email) values ($1, $2, $3)",
            user_id,
            name,
            f"{name}@example.test",
        )
        await conn.execute(
            "insert into memberships (tenant_id, user_id, role) values ($1, $2, $3)",
            TENANT_A,
            user_id,
            role,
        )
    for team_id, team_name in ((TEAM_LOCAL, "Local sales"), (TEAM_EXPORT, "Export")):
        await conn.execute(
            "insert into teams (id, tenant_id, name) values ($1, $2, $3)",
            team_id,
            TENANT_A,
            team_name,
        )
    for team_id, user_id in (
        (TEAM_LOCAL, MANAGER),
        (TEAM_LOCAL, SALES_1),
        (TEAM_LOCAL, SALES_2),
        (TEAM_EXPORT, SALES_X),
    ):
        await conn.execute(
            "insert into team_members (tenant_id, team_id, user_id) values ($1, $2, $3)",
            TENANT_A,
            team_id,
            user_id,
        )


async def _seed_customer(
    conn: asyncpg.Connection,
    name: str,
    owner_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    assigned_to: uuid.UUID | None = None,
) -> uuid.UUID:
    """One customer with one conversation and one lead, owned as stated."""
    contact_id = uuid.uuid4()
    await conn.execute(
        """insert into contacts (id, tenant_id, full_name, owner_id, team_id)
           values ($1, $2, $3, $4, $5)""",
        contact_id,
        TENANT_A,
        name,
        owner_id,
        team_id,
    )
    await conn.execute(
        """insert into conversations
             (tenant_id, contact_id, surface, owner_id, team_id, assigned_to)
           values ($1, $2, 'whatsapp', $3, $4, $5)""",
        TENANT_A,
        contact_id,
        owner_id,
        team_id,
        assigned_to if assigned_to is not None else owner_id,
    )
    pipeline_id, stage_id = await _open_board(conn, TENANT_A)
    await conn.execute(
        """insert into leads (tenant_id, contact_id, pipeline_id, stage_id, owner_id, team_id)
           values ($1, $2, $3, $4, $5, $6)""",
        TENANT_A,
        contact_id,
        pipeline_id,
        stage_id,
        owner_id,
        team_id,
    )
    return contact_id


@pytest.fixture
async def visibility_seed(su: asyncpg.Connection) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Five people, two teams and six customers with different owners."""
    await _wipe(su)
    await _seed_tenant(su, TENANT_A, USER_A, "alpha")
    await _seed_tenant(su, TENANT_B, USER_B, "beta")
    await _seed_people(su)
    ids = {
        "s1": await _seed_customer(su, "s1 customer", SALES_1, TEAM_LOCAL),
        "s2": await _seed_customer(su, "s2 customer", SALES_2, TEAM_LOCAL),
        # S2 owns the customer; S1 is covering the conversation.
        "covered": await _seed_customer(su, "covered customer", SALES_2, TEAM_LOCAL, SALES_1),
        "x": await _seed_customer(su, "x customer", SALES_X, TEAM_EXPORT),
        "pool_local": await _seed_customer(su, "local pool", None, TEAM_LOCAL),
        "pool_export": await _seed_customer(su, "export pool", None, TEAM_EXPORT),
    }
    yield ids
    await _wipe(su)


async def reseed_with_people() -> None:
    """reseed() plus the visibility people, for synchronous route tests."""
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await _wipe(conn)
        await _seed_tenant(conn, TENANT_A, USER_A, "alpha")
        await _seed_tenant(conn, TENANT_B, USER_B, "beta")
        await _seed_people(conn)
    finally:
        await conn.close()
