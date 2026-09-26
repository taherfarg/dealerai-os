# Sales S0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** the ground every later slice stands on — teams and the manager role, "a salesperson sees
only their own customers" enforced in Postgres, `/v1/me`, generated frontend types, the app shell,
and seed data.

**Architecture:** extend the existing tenant session with a user and a scope, add visibility
predicates to the RLS policies on owner-bearing tables, revoke browser table access so the API is the
only data path, and give `apps/web` the React Query + generated-types skeleton the sales screens will
use.

**Tech stack:** Postgres 17 · asyncpg · FastAPI · Pydantic v2 · pytest · Next.js 16 · React 19 ·
TanStack Query · openapi-typescript · Tailwind v4.

**Before you start:** Docker Desktop must be running (`npm run db:up` fails otherwise). Work on
branch `sales/phase-1` in this worktree. Read [../01-architecture.md](../01-architecture.md) §3 and
[../02-data-model.md](../02-data-model.md) §4 first — they are the specification this plan implements.

---

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0006_sales_core.sql` | **Create.** Teams, identities, owner and scope columns, visibility functions, policies, grant revocation. One migration for the whole slice: while it is unmerged, re-apply it with `npm run db:reset`; once merged it is never edited (the runner refuses a changed checksum) |
| `apps/api/src/dealerai/db/session.py` | **Modify.** `tenant_session` gains `user_id` and `scope` |
| `apps/api/src/dealerai/core/permissions.py` | **Create.** Role → permissions and role → scope. Pure data and two functions, no database |
| `apps/api/src/dealerai/deps.py` | **Modify.** `manager` in `ROLES`; `TenantContext` carries scope and permissions; `require_permission` |
| `apps/api/src/dealerai/routes/me.py` | **Create.** `GET /v1/me`, `PATCH /v1/me` |
| `apps/api/src/dealerai/routes/team.py` | **Create.** `/v1/members`, `/v1/teams` |
| `apps/api/src/dealerai/db/queries/team.py` | **Create.** SQL for members and teams |
| `apps/api/src/dealerai/scripts/seed_sales.py` | **Create.** Local seed data |
| `apps/api/tests/test_sales_schema.py` | **Create.** Schema and constraint tests |
| `apps/api/tests/test_visibility.py` | **Create.** The rep/manager/owner matrix, both access paths |
| `apps/api/tests/test_permissions.py` | **Create.** Pure role → permission tests, no database |
| `apps/api/tests/test_me_and_team.py` | **Create.** Route tests |
| `apps/api/tests/conftest.py` | **Modify.** `seed_visibility()` fixture |
| `apps/web/lib/api/{schema.ts,client.ts,keys.ts,hooks.ts}` | **Create.** Generated types and the typed client |
| `apps/web/app/[tenant]/providers.tsx` | **Create.** React Query, locale, toaster |
| `apps/web/components/Shell.tsx` | **Modify.** Sales navigation, availability switch |
| `apps/web/messages/{en.ts,ar.ts}` | **Create.** Message catalogue moved out of `lib/i18n.ts` |
| `apps/web/lib/format.ts` | **Create.** Money, dates, durations |
| `package.json` | **Modify.** `db:seed`, `api-types`, `check:openapi` |

---

## Task 1: Sales core tables

**Files:**
- Create: `supabase/migrations/0006_sales_core.sql`
- Create: `apps/api/tests/test_sales_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_sales_schema.py
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
    await su.execute(
        "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'manager')",
        TENANT_A,
        user_id,
    )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm run db:up && cd apps/api && uv run pytest tests/test_sales_schema.py -v`
Expected: FAIL — `teams is missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0006_sales_core.sql
-- Sales S0: teams, customer identities, ownership, and the visibility settings
-- the policies in this file read. See docs/sales/02-data-model.md.

-- =============================================================================
-- TEAMS
-- =============================================================================
create table teams (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id) on delete cascade,
  name       text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, name)
);

-- A manager manages every team they belong to. No is_manager flag: the role
-- decides, and two sources for one fact drift.
create table team_members (
  tenant_id  uuid not null references tenants(id) on delete cascade,
  team_id    uuid not null references teams(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (team_id, user_id)
);
create index on team_members (tenant_id, user_id);

-- =============================================================================
-- CUSTOMER IDENTITIES
-- One row per way a customer can reach us. The unique index is what makes two
-- simultaneous webhooks from one new customer produce one contact, not two —
-- a jsonb of platform ids cannot enforce that.
-- =============================================================================
create table contact_identities (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  contact_id  uuid not null references contacts(id) on delete cascade,
  kind        text not null check (kind in
                ('whatsapp_user_id','phone','instagram_id','messenger_psid','email')),
  value       text not null,
  is_primary  boolean not null default false,
  verified_at timestamptz,
  created_at  timestamptz not null default now(),
  unique (tenant_id, kind, value),
  -- E.164 only. Voice gives +971…, WhatsApp gives 971…, people type 050…;
  -- normalising at the edge is the difference between one customer and three.
  constraint phone_is_e164 check (kind <> 'phone' or value ~ '^\+[1-9][0-9]{6,14}$')
);
create index on contact_identities (tenant_id, contact_id);
create unique index contact_identities_primary_uq
  on contact_identities (contact_id, kind) where is_primary;

-- Move what contacts held today, then drop it.
insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
  select tenant_id, id, 'phone', phone, true from contacts where phone is not null
  on conflict do nothing;
insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
  select tenant_id, id, 'email', lower(email), true from contacts where email is not null
  on conflict do nothing;

drop index if exists contacts_phone_uq;
drop index if exists contacts_external_refs_gin;
alter table contacts
  drop column if exists phone,
  drop column if exists email,
  drop column if exists external_refs,
  add column owner_id uuid references auth.users(id) on delete set null,
  add column team_id uuid references teams(id) on delete set null,
  add column profile jsonb not null default '{}'::jsonb,
  add column profile_updated_at timestamptz;
create index on contacts (tenant_id, owner_id);
create index on contacts (tenant_id, team_id) where owner_id is null;

-- =============================================================================
-- OWNERSHIP AND WAITING STATE
-- owner_id is denormalised onto conversations so a visibility policy reads one
-- row. app.reassign_contact, added with the CRM slice, will be the single writer
-- that keeps them equal, and brings the invariant test with it.
-- =============================================================================
alter table conversations
  add column owner_id uuid references auth.users(id) on delete set null,
  add column team_id uuid references teams(id) on delete set null,
  add column waiting_since timestamptz,
  add column sla_due_at timestamptz,
  add column first_response_at timestamptz,
  add column summary jsonb;
create index on conversations (tenant_id, owner_id);
create index on conversations (tenant_id, team_id, status) where assigned_to is null;
create index on conversations (tenant_id, sla_due_at) where waiting_since is not null;

alter table leads
  add column team_id uuid references teams(id) on delete set null;
create index on leads (tenant_id, owner_id);

-- =============================================================================
-- PEOPLE AND TENANT SETTINGS
-- =============================================================================
alter table memberships drop constraint memberships_role_check;
alter table memberships add constraint memberships_role_check
  check (role in ('owner','admin','manager','marketer','sales','viewer'));
alter table memberships
  add column languages text[] not null default '{}',
  add column accepting_chats boolean not null default true,
  add column last_assigned_at timestamptz,
  add column max_open_conversations int;
create index on memberships (tenant_id, last_assigned_at) where accepting_chats;

-- Read whole, never filtered on: jsonb, per docs/03-database-schema.md § 3.
-- Validated by the SalesSettings model at the application edge.
alter table tenants
  add column sales_settings jsonb not null default '{}'::jsonb;

-- =============================================================================
-- RLS for the new tables, same loop and same policy as 0001
-- =============================================================================
do $$
declare t text;
begin
  foreach t in array array['teams','team_members','contact_identities']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy tenant_isolation on %I
         using (app.has_tenant_access(tenant_id))
         with check (app.has_tenant_access(tenant_id))', t);
  end loop;
end $$;

create trigger teams_touch before update on teams
  for each row execute function app.touch_updated_at();
```

- [ ] **Step 4: Apply and run the test**

Run: `npm run db:reset && cd apps/api && uv run pytest tests/test_sales_schema.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Run the whole suite — the schema changed under it**

Run: `npm run test`
Expected: PASS. If `tests/test_tenant_isolation.py` fails on the new tables, add them to
`SEEDED_TABLES` only once Task 5 seeds them; the structural test should already cover them.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/0006_sales_core.sql apps/api/tests/test_sales_schema.py
git commit -m "feat(sales): teams, customer identities and ownership columns"
```

---

## Task 2: A session that knows who is asking

**Files:**
- Modify: `apps/api/src/dealerai/db/session.py:56-68`
- Modify: `supabase/migrations/0006_sales_core.sql` (append)
- Create: `apps/api/tests/test_visibility.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_visibility.py
"""Who can see whose customers. The second-highest-value test in the repo."""

from __future__ import annotations

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.db.session import tenant_session


async def test_scope_and_user_reach_the_database(db: None, seeded: None) -> None:
    from conftest import USER_A

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
    from conftest import USER_A
    from dealerai.db.session import system_session

    async with tenant_session(TENANT_A, user_id=USER_A, scope="own"):
        pass
    async with system_session() as conn:
        assert await conn.fetchval("select current_setting('app.user_id', true)") in (None, "")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/test_visibility.py -v`
Expected: FAIL — `tenant_session() got an unexpected keyword argument 'user_id'`.

- [ ] **Step 3: Append the functions to the migration**

```sql
-- === appended to 0006_sales_core.sql ===============================
-- VISIBILITY
-- The same idea as tenancy, one level down: the session states who is asking
-- and how wide they may see, and the policies enforce it. Every function is
-- wrapped in (select …) at the call site so Postgres evaluates it once per
-- statement instead of once per row.
-- =============================================================================

create or replace function app.current_user_id()
returns uuid language sql stable
set search_path = public, pg_temp as $$
  select nullif(current_setting('app.user_id', true), '')::uuid
$$;

create or replace function app.my_team_ids()
returns uuid[] language sql stable security definer
set search_path = public, pg_temp as $$
  select coalesce(array_agg(tm.team_id), '{}')
  from public.team_members tm
  where tm.user_id = app.current_user_id()
$$;

-- NULL means "no owner filter" — the scope is 'all'. An empty array would mean
-- "sees nothing", which is a different thing, so the distinction is load-bearing.
create or replace function app.visible_owner_ids()
returns uuid[] language sql stable security definer
set search_path = public, pg_temp as $$
  select case coalesce(nullif(current_setting('app.scope', true), ''), 'all')
    when 'own' then array[app.current_user_id()]
    when 'team' then (
      select coalesce(array_agg(distinct tm2.user_id), '{}') || array[app.current_user_id()]
      from public.team_members tm1
      join public.team_members tm2 on tm2.team_id = tm1.team_id
      where tm1.user_id = app.current_user_id())
    else null
  end
$$;

create or replace function app.pool_visible()
returns boolean language sql stable security definer
set search_path = public, pg_temp as $$
  select case when coalesce(nullif(current_setting('app.scope', true), ''), 'all') = 'all' then true
    else coalesce(
      (select (t.sales_settings->>'unassigned_visible_to_sales')::boolean
       from public.tenants t
       where t.id = nullif(current_setting('app.tenant_id', true), '')::uuid),
      true)
  end
$$;

revoke all on function app.my_team_ids(), app.visible_owner_ids(), app.pool_visible() from public;
grant execute on function app.current_user_id() to dealerai_app, authenticated;
grant execute on function app.my_team_ids() to dealerai_app, authenticated;
grant execute on function app.visible_owner_ids() to dealerai_app, authenticated;
grant execute on function app.pool_visible() to dealerai_app, authenticated;
```

- [ ] **Step 4: Widen the session**

```python
# apps/api/src/dealerai/db/session.py — replace tenant_session
SCOPES = ("own", "team", "all")


@contextlib.asynccontextmanager
async def tenant_session(
    tenant_id: UUID | str,
    *,
    user_id: UUID | str | None = None,
    scope: str = "all",
) -> AsyncIterator[asyncpg.Connection]:
    """Open a transaction scoped to one tenant, and optionally to one person.

    `scope` is what a salesperson may see: their own customers, their team's, or
    everything. The worker keeps the default — it acts on rows already routed.

    All three settings are transaction-scoped (set_config(..., true)), so a
    pooled connection cannot carry a tenant *or a user* into the next request.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; expected one of {SCOPES}")
    async with _require_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """select set_config('app.tenant_id', $1, true),
                          set_config('app.user_id', $2, true),
                          set_config('app.scope', $3, true)""",
                str(tenant_id),
                str(user_id) if user_id else "",
                scope,
            )
            yield conn
```

- [ ] **Step 5: Run the test**

Run: `npm run db:reset && cd apps/api && uv run pytest tests/test_visibility.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/0006_sales_core.sql apps/api/src/dealerai/db/session.py apps/api/tests/test_visibility.py
git commit -m "feat(sales): session carries the user and their scope"
```

---

## Task 3: The visibility matrix

**Files:**
- Modify: `apps/api/tests/conftest.py` (add `seed_visibility`)
- Modify: `apps/api/tests/test_visibility.py` (add the matrix)
- Modify: `supabase/migrations/0006_sales_core.sql` (append policies)

- [ ] **Step 1: Add the fixture**

```python
# apps/api/tests/conftest.py — append

OWNER = uuid.UUID("cccccccc-1111-4000-8000-000000000001")
MANAGER = uuid.UUID("cccccccc-1111-4000-8000-000000000002")
SALES_1 = uuid.UUID("cccccccc-1111-4000-8000-000000000003")
SALES_2 = uuid.UUID("cccccccc-1111-4000-8000-000000000004")
SALES_X = uuid.UUID("cccccccc-1111-4000-8000-000000000005")
TEAM_LOCAL = uuid.UUID("dddddddd-1111-4000-8000-000000000001")
TEAM_EXPORT = uuid.UUID("dddddddd-1111-4000-8000-000000000002")


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
            "insert into memberships (tenant_id, user_id, role) values ($1, $2, $3)",
            TENANT_A,
            user_id,
            role,
        )
    for team_id, name in ((TEAM_LOCAL, "Local sales"), (TEAM_EXPORT, "Export")):
        await conn.execute(
            "insert into teams (id, tenant_id, name) values ($1, $2, $3)", team_id, TENANT_A, name
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
        """insert into conversations (tenant_id, contact_id, surface, owner_id, team_id, assigned_to)
           values ($1, $2, 'whatsapp', $3, $4, $5)""",
        TENANT_A,
        contact_id,
        owner_id,
        team_id,
        assigned_to if assigned_to is not None else owner_id,
    )
    await conn.execute(
        """insert into leads (tenant_id, contact_id, stage, owner_id, team_id)
           values ($1, $2, 'new', $3, $4)""",
        TENANT_A,
        contact_id,
        owner_id,
        team_id,
    )
    return contact_id


@pytest.fixture
async def visibility_seed(su: asyncpg.Connection) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Five people, two teams and five customers with different owners."""
    await _wipe(su)
    await _seed_tenant(su, TENANT_A, USER_A, "alpha")
    await _seed_tenant(su, TENANT_B, USER_B, "beta")
    await _seed_people(su)
    ids = {
        "s1": await _seed_customer(su, "s1 customer", SALES_1, TEAM_LOCAL),
        "s2": await _seed_customer(su, "s2 customer", SALES_2, TEAM_LOCAL),
        # S2 owns the customer, S1 is covering the conversation.
        "covered": await _seed_customer(su, "covered customer", SALES_2, TEAM_LOCAL, SALES_1),
        "x": await _seed_customer(su, "x customer", SALES_X, TEAM_EXPORT),
        "pool_local": await _seed_customer(su, "local pool", None, TEAM_LOCAL),
        "pool_export": await _seed_customer(su, "export pool", None, TEAM_EXPORT),
    }
    yield ids
    await _wipe(su)
```

Then widen `_wipe` so it removes these people too, and add a reseed for the synchronous route tests,
which cannot consume an async fixture:

```python
# apps/api/tests/conftest.py — replace _wipe, and append reseed_with_people
PEOPLE_IDS = [OWNER, MANAGER, SALES_1, SALES_2, SALES_X]


async def _wipe(conn: asyncpg.Connection) -> None:
    await conn.execute("delete from tenants")
    await conn.execute(
        "delete from auth.users where id = any($1::uuid[])", [USER_A, USER_B, *PEOPLE_IDS]
    )


async def reseed_with_people() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await _wipe(conn)
        await _seed_tenant(conn, TENANT_A, USER_A, "alpha")
        await _seed_tenant(conn, TENANT_B, USER_B, "beta")
        await _seed_people(conn)
    finally:
        await conn.close()
```

The constants stay at module level; the tests import them from `conftest`.

- [ ] **Step 2: Write the failing matrix test**

```python
# apps/api/tests/test_visibility.py — append

from conftest import MANAGER, OWNER, SALES_1, SALES_X  # noqa: E402

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
    visibility_seed: dict,
    viewer,
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
async def test_conversations_and_messages_follow_the_customer(
    db: None, visibility_seed: dict, viewer, scope: str, visible: tuple, hidden: tuple
) -> None:
    async with tenant_session(TENANT_A, user_id=viewer, scope=scope) as conn:
        contact_ids = {r["contact_id"] for r in await conn.fetch("select contact_id from conversations")}
    for key in visible:
        assert visibility_seed[key] in contact_ids, f"{key}'s conversation should be visible"
    for key in hidden:
        assert visibility_seed[key] not in contact_ids, f"LEAK: {key}'s conversation is visible"


async def test_turning_the_pool_off_hides_unassigned_customers(
    db: None, su: asyncpg.Connection, visibility_seed: dict
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


async def test_the_worker_still_sees_everything(db: None, visibility_seed: dict) -> None:
    """Handlers act on rows already routed; a scoped worker would silently skip work."""
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select count(*) from contacts") >= 6
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/test_visibility.py -k who_sees -v`
Expected: FAIL — every viewer currently sees every customer.

- [ ] **Step 4: Append the policies to the migration**

```sql
-- === appended to 0006_sales_core.sql ===============================
-- The tenant predicate stays exactly as it was; visibility is an extra clause.
-- WITH CHECK stays tenant-only on purpose: reassigning a conversation to a
-- colleague makes it invisible to the person doing it, and a visibility check
-- on the new row would make that update fail. Who may reassign is a permission,
-- checked in the route; who may see is RLS.
-- =============================================================================

drop policy tenant_isolation on contacts;
create policy tenant_visibility on contacts
  using (
    app.has_tenant_access(tenant_id)
    and (
      (select app.visible_owner_ids()) is null
      or owner_id = any (coalesce((select app.visible_owner_ids()), '{}'))
      or (owner_id is null and team_id = any (coalesce((select app.my_team_ids()), '{}'))
          and (select app.pool_visible()))
      or exists (select 1 from public.conversations c
                 where c.contact_id = contacts.id
                   and c.assigned_to = (select app.current_user_id()))
    )
  )
  with check (app.has_tenant_access(tenant_id));

drop policy tenant_isolation on conversations;
create policy tenant_visibility on conversations
  using (
    app.has_tenant_access(tenant_id)
    and (
      (select app.visible_owner_ids()) is null
      or owner_id = any (coalesce((select app.visible_owner_ids()), '{}'))
      or assigned_to = (select app.current_user_id())
      or (owner_id is null and assigned_to is null
          and team_id = any (coalesce((select app.my_team_ids()), '{}'))
          and (select app.pool_visible()))
    )
  )
  with check (app.has_tenant_access(tenant_id));

drop policy tenant_isolation on leads;
create policy tenant_visibility on leads
  using (
    app.has_tenant_access(tenant_id)
    and (
      (select app.visible_owner_ids()) is null
      or owner_id = any (coalesce((select app.visible_owner_ids()), '{}'))
      or (owner_id is null and team_id = any (coalesce((select app.my_team_ids()), '{}'))
          and (select app.pool_visible()))
    )
  )
  with check (app.has_tenant_access(tenant_id));

-- Children inherit: the inner select is itself filtered by the policy above.
drop policy tenant_isolation on messages;
create policy tenant_visibility on messages
  using (
    app.has_tenant_access(tenant_id)
    and exists (select 1 from public.conversations c where c.id = messages.conversation_id)
  )
  with check (app.has_tenant_access(tenant_id));

drop policy tenant_isolation on activities;
create policy tenant_visibility on activities
  using (
    app.has_tenant_access(tenant_id)
    and (
      (select app.visible_owner_ids()) is null
      or exists (select 1 from public.leads l where l.id = activities.lead_id)
      or exists (select 1 from public.contacts c where c.id = activities.contact_id)
    )
  )
  with check (app.has_tenant_access(tenant_id));

-- Replace, never add: permissive policies are OR'ed, so the tenant-only policy
-- left beside this one would quietly undo it.
drop policy tenant_isolation on contact_identities;
create policy tenant_visibility on contact_identities
  using (
    app.has_tenant_access(tenant_id)
    and exists (select 1 from public.contacts c where c.id = contact_identities.contact_id)
  )
  with check (app.has_tenant_access(tenant_id));
```

- [ ] **Step 5: Run the matrix and the whole suite**

Run: `npm run db:reset && cd apps/api && uv run pytest tests/test_visibility.py -v && cd ../.. && npm run test`
Expected: PASS. The existing `test_tenant_isolation.py` must stay green — its sessions use the
default scope `all`, so nothing there changes.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/0006_sales_core.sql apps/api/tests/conftest.py apps/api/tests/test_visibility.py
git commit -m "feat(sales): a salesperson sees only their own customers"
```

---

## Task 4: Close the browser's direct path to the tables

**Files:**
- Modify: `supabase/migrations/0006_sales_core.sql` (append)
- Modify: `apps/api/tests/test_visibility.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_visibility.py — append

async def test_browser_roles_cannot_read_any_table(su: asyncpg.Connection) -> None:
    """The API is the only data path now, so the anon and authenticated roles
    have no business reading tables directly. Visibility is enforced for the
    backend path; leaving PostgREST open would be a second, weaker door."""
    tables = [
        r["tablename"]
        for r in await su.fetch(
            "select tablename from pg_tables where schemaname = 'public'"
        )
    ]
    assert tables
    leaks = []
    for table in tables:
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if await su.fetchval(
                    "select has_table_privilege($1, $2, $3)", role, table, privilege
                ):
                    leaks.append(f"{role} can {privilege} {table}")
    assert not leaks, "browser roles still reach tables directly: " + ", ".join(leaks)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/test_visibility.py -k browser_roles -v`
Expected: FAIL — `authenticated` can SELECT every table (granted in 0001).

- [ ] **Step 3: Append the revocation**

```sql
-- === appended to 0006_sales_core.sql ===============================
-- The browser no longer reads tables. docs/sales/README.md records this as a
-- change to DealerAI OS 01 § 2 path A: every read now goes through FastAPI,
-- where the scope is set and the visibility policies apply.
-- =============================================================================
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;

-- The browser asked this one directly while it still had a path; it does not now.
revoke execute on function app.tenants_for_user(uuid) from authenticated;
```

- [ ] **Step 4: Run the test and the suite**

Run: `npm run db:reset && npm run test`
Expected: two existing tests now FAIL with `InsufficientPrivilegeError`:
`test_jwt_path_sees_only_its_own_tenant` and `test_jwt_path_message_bodies_do_not_cross` in
`tests/test_tenant_isolation.py`. That is the change working — they assert what the browser can read
from tables, and the browser can no longer read tables at all.

Delete both functions, and replace the "behavioural — browser path" section header with:

```python
# --------------------------------------------------------------------------
# browser path
#
# Closed since migration 0006: anon and authenticated hold no table privileges,
# so the browser reaches tenant data only through the API.
# tests/test_visibility.py::test_browser_roles_cannot_read_any_table proves it
# for every table; test_unauthenticated_sees_nothing below stays as the
# concrete case.
# --------------------------------------------------------------------------
```

Remove the now-unused `USER_A` and `jwt_session` imports if nothing else in the file uses them, then
run `npm run test` again. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0006_sales_core.sql apps/api/tests/test_visibility.py
git commit -m "feat(sales): the API is the only path to tenant data"
```

---

## Task 5: Permissions as data

**Files:**
- Create: `apps/api/src/dealerai/core/permissions.py`
- Create: `apps/api/tests/test_permissions.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_permissions.py
"""Pure logic, no database — the same reason orchestrator/gate.py is pure:
an authorisation rule you cannot test in milliseconds is one nobody re-checks."""

from __future__ import annotations

import pytest

from dealerai.core.permissions import ROLES, permissions_for, scope_for


def test_every_role_has_a_scope_and_a_permission_set() -> None:
    for role in ROLES:
        assert scope_for(role) in ("own", "team", "all")
        assert isinstance(permissions_for(role), frozenset)


@pytest.mark.parametrize(
    ("role", "scope"),
    [("owner", "all"), ("admin", "all"), ("viewer", "all"),
     ("manager", "team"), ("sales", "own"), ("marketer", "own")],
)
def test_scope_by_role(role: str, scope: str) -> None:
    assert scope_for(role) == scope


def test_a_salesperson_may_send_but_not_reassign() -> None:
    sales = permissions_for("sales")
    assert "inbox.send" in sales
    assert "contacts.reassign" not in sales
    assert "settings.team" not in sales


def test_a_manager_may_assign_and_route_but_not_change_channels() -> None:
    manager = permissions_for("manager")
    assert {"inbox.assign", "contacts.reassign", "dashboard.manager", "settings.routing"} <= manager
    assert "settings.channels" not in manager


def test_a_viewer_may_do_nothing() -> None:
    assert permissions_for("viewer") == frozenset()


def test_an_unknown_role_gets_nothing_rather_than_everything() -> None:
    """Fail closed: a role added to the database but not here must not inherit power."""
    assert permissions_for("nonsense") == frozenset()
    assert scope_for("nonsense") == "own"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/test_permissions.py -v`
Expected: FAIL — `No module named 'dealerai.core.permissions'`.

- [ ] **Step 3: Write the module**

```python
# apps/api/src/dealerai/core/permissions.py
"""Who may do what, as data.

Visibility (whose rows you see) is enforced in Postgres; permissions (what you
may do) are enforced here and in the routes. Keeping them apart is deliberate:
one is a leak if it is wrong, the other is a button that should not have worked.
"""

from __future__ import annotations

#: Ordered least to most privileged. deps.require_role compares by index.
ROLES = ("viewer", "sales", "marketer", "manager", "admin", "owner")

_ADMIN = frozenset(
    {
        "inbox.send",
        "inbox.assign",
        "contacts.reassign",
        "contacts.merge",
        "leads.mark_won_lost",
        "pipeline.edit_stages",
        "dashboard.manager",
        "settings.channels",
        "settings.team",
        "settings.routing",
        "settings.quick_replies",
        "settings.knowledge",
        "settings.ai",
    }
)

PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": _ADMIN,
    "admin": _ADMIN,
    "manager": frozenset(
        {
            "inbox.send",
            "inbox.assign",
            "contacts.reassign",
            "contacts.merge",
            "leads.mark_won_lost",
            "dashboard.manager",
            "settings.routing",
            "settings.quick_replies",
        }
    ),
    "sales": frozenset({"inbox.send", "leads.mark_won_lost"}),
    "marketer": frozenset(),
    "viewer": frozenset(),
}

#: What a role may see. 'all' means no owner filter at all.
SCOPES: dict[str, str] = {
    "owner": "all",
    "admin": "all",
    "viewer": "all",
    "manager": "team",
    "sales": "own",
    "marketer": "own",
}


def permissions_for(role: str) -> frozenset[str]:
    """Unknown roles get nothing. Fail closed."""
    return PERMISSIONS.get(role, frozenset())


def scope_for(role: str) -> str:
    """Unknown roles see only their own rows, which for them is nothing."""
    return SCOPES.get(role, "own")
```

- [ ] **Step 4: Run the test**

Run: `cd apps/api && uv run pytest tests/test_permissions.py -v`
Expected: PASS, 10 tests, with no database.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/core/permissions.py apps/api/tests/test_permissions.py
git commit -m "feat(sales): roles carry permissions and a visibility scope"
```

---

## Task 6: The request knows its scope

**Files:**
- Modify: `apps/api/src/dealerai/deps.py:22-33,47-83`
- Create: `apps/api/tests/test_deps_scope.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_deps_scope.py
from __future__ import annotations

import pytest

from dealerai.core.errors import Forbidden
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext, require_permission
from conftest import TENANT_A, SALES_1


def _ctx(role: str) -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A,
        user=AuthedUser(id=SALES_1, email="s1@example.test"),
        role=role,
    )


def test_context_derives_scope_and_permissions_from_the_role() -> None:
    assert _ctx("sales").scope == "own"
    assert _ctx("manager").scope == "team"
    assert _ctx("owner").scope == "all"
    assert _ctx("manager").may("inbox.assign")
    assert not _ctx("sales").may("inbox.assign")


def test_manager_outranks_sales_and_marketer() -> None:
    assert _ctx("manager").at_least("sales")
    assert _ctx("manager").at_least("marketer")
    assert not _ctx("sales").at_least("manager")


async def test_require_permission_refuses_and_allows() -> None:
    guard = require_permission("contacts.reassign")
    with pytest.raises(Forbidden):
        await guard(_ctx("sales"))
    assert await guard(_ctx("manager")) is not None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/test_deps_scope.py -v`
Expected: FAIL — `cannot import name 'require_permission'`.

- [ ] **Step 3: Update `deps.py`**

Replace the `ROLES` constant and `TenantContext`, and add the new guard:

```python
from .core.permissions import ROLES, permissions_for, scope_for  # replaces the local ROLES tuple


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID
    user: AuthedUser
    role: str

    @property
    def scope(self) -> str:
        """What this caller may see: own, team or all. Passed to tenant_session."""
        return scope_for(self.role)

    @property
    def permissions(self) -> frozenset[str]:
        return permissions_for(self.role)

    def may(self, permission: str) -> bool:
        return permission in self.permissions

    def at_least(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


def require_permission(permission: str) -> Callable[[TenantContext], Awaitable[TenantContext]]:
    """Guard a route by permission rather than by rank.

    Rank is the wrong question for most actions here: a manager may reassign a
    customer and an admin may not do it better. Usage:
    `_: Annotated[TenantContext, Depends(require_permission("contacts.reassign"))]`
    """

    async def guard(ctx: Ctx) -> TenantContext:
        if not ctx.may(permission):
            raise Forbidden(f"this action requires the {permission} permission")
        return ctx

    return guard
```

- [ ] **Step 4: Run the test and the suite**

Run: `cd apps/api && uv run pytest tests/test_deps_scope.py -v && uv run pytest`
Expected: PASS. `tests/test_tenants.py` still passes — `require_role` is unchanged and `manager`
simply sits between `marketer` and `admin`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/deps.py apps/api/tests/test_deps_scope.py
git commit -m "feat(sales): requests carry their scope and permissions"
```

---

## Task 7: `GET /v1/me`

**Files:**
- Create: `apps/api/src/dealerai/routes/me.py`
- Modify: `apps/api/src/dealerai/main.py:48-52`
- Create: `apps/api/tests/test_me_and_team.py`

- [ ] **Step 1: Write the failing test**

Follow the pattern every route test in this repo uses (see `tests/test_approvals.py`): a
module-level `SECRET`, an autouse fixture that installs it as the JWT secret, a `client` fixture
that reseeds and wraps `TestClient(app)`, and an `auth()` helper that mints a Supabase-shaped token
with `mint_test_token`. The repo has no shared auth helper; do not invent one.

```python
# apps/api/tests/test_me_and_team.py
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed_with_people())
    with TestClient(app) as c:
        yield c


def auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


def test_me_returns_role_scope_and_permissions(client: TestClient) -> None:
    response = client.get("/v1/me", headers=auth(SALES_1))
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "sales"
    assert body["scope"] == "own"
    assert "inbox.send" in body["permissions"]
    assert "contacts.reassign" not in body["permissions"]
    assert body["tenant"]["slug"] == "alpha"
    assert body["accepting_chats"] is True


def test_me_includes_the_teams_a_manager_manages(client) -> None:
    response = client.get("/v1/me", headers=auth(MANAGER))
    assert response.status_code == 200
    assert len(response.json()["team_ids"]) == 1


def test_availability_can_be_switched_off(client) -> None:
    response = client.patch(
        "/v1/me", json={"accepting_chats": False}, headers=auth(SALES_1)
    )
    assert response.status_code == 200
    assert response.json()["accepting_chats"] is False
```

(`reseed_with_people()` from Task 3 gives the route tests the same people and teams as the
database tests.)

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/test_me_and_team.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Write the route**

```python
# apps/api/src/dealerai/routes/me.py
"""Who am I, here. The first call every screen makes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from ..db.session import tenant_session
from ..deps import Ctx

router = APIRouter(prefix="/v1", tags=["me"])


class TenantOut(BaseModel):
    id: UUID
    slug: str
    name: str
    timezone: str
    currency: str
    logo_url: str | None = None
    accent_color: str | None = None


class UserOut(BaseModel):
    id: UUID
    name: str | None
    email: str | None
    avatar_url: str | None = None


class MeOut(BaseModel):
    user: UserOut
    tenant: TenantOut
    role: str
    scope: str
    team_ids: list[UUID]
    permissions: list[str]
    accepting_chats: bool


class MePatch(BaseModel):
    accepting_chats: bool


async def _load(ctx: Ctx) -> MeOut:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        tenant = await conn.fetchrow(
            """select t.id, t.slug, t.name, t.timezone, t.currency,
                      -- the logo lives in brand_assets behind a signed URL; it joins
                      -- this response with the brand settings screen
                      b.colors->>'primary' as accent_color
               from tenants t
               left join brand_profiles b on b.tenant_id = t.id
               where t.id = $1""",
            ctx.tenant_id,
        )
        member = await conn.fetchrow(
            """select m.accepting_chats, p.full_name, p.email, p.avatar_url
               from memberships m
               left join profiles p on p.id = m.user_id
               where m.tenant_id = $1 and m.user_id = $2""",
            ctx.tenant_id,
            ctx.user.id,
        )
        teams = await conn.fetch(
            "select team_id from team_members where user_id = $1", ctx.user.id
        )
    data: dict[str, Any] = dict(member or {})
    return MeOut(
        user=UserOut(
            id=ctx.user.id,
            name=data.get("full_name"),
            email=data.get("email") or ctx.user.email,
            avatar_url=data.get("avatar_url"),
        ),
        tenant=TenantOut(**dict(tenant)),
        role=ctx.role,
        scope=ctx.scope,
        team_ids=[t["team_id"] for t in teams],
        permissions=sorted(ctx.permissions),
        accepting_chats=bool(data.get("accepting_chats", True)),
    )


@router.get("/me", response_model=MeOut)
async def get_me(ctx: Ctx) -> MeOut:
    return await _load(ctx)


@router.patch("/me", response_model=MeOut)
async def patch_me(ctx: Ctx, patch: MePatch) -> MeOut:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await conn.execute(
            """update memberships set accepting_chats = $3
               where tenant_id = $1 and user_id = $2""",
            ctx.tenant_id,
            ctx.user.id,
            patch.accepting_chats,
        )
    return await _load(ctx)
```

Register it in `main.py` beside the other routers:

```python
from .routes import approvals, content, imports, me, runs, tenants, vehicles
...
    app.include_router(me.router)
```

- [ ] **Step 4: Run the test**

Run: `cd apps/api && uv run pytest tests/test_me_and_team.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/routes/me.py apps/api/src/dealerai/main.py apps/api/tests/test_me_and_team.py
git commit -m "feat(sales): GET /v1/me"
```

---

## Task 8: Members and teams

**Files:**
- Create: `apps/api/src/dealerai/routes/team.py`
- Create: `apps/api/src/dealerai/db/queries/team.py`
- Modify: `apps/api/src/dealerai/main.py`
- Modify: `apps/api/tests/test_me_and_team.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_me_and_team.py — append

def test_members_list_shows_availability_and_languages(client) -> None:
    response = client.get("/v1/members", headers=auth(MANAGER))
    assert response.status_code == 200
    roles = {m["role"] for m in response.json()}
    assert {"owner", "manager", "sales"} <= roles


def test_only_settings_team_may_change_a_member(client) -> None:
    from conftest import SALES_2

    denied = client.patch(
        f"/v1/members/{SALES_2}",
        json={"languages": ["ar", "fr"]},
        headers=auth(MANAGER),  # manager lacks settings.team
    )
    assert denied.status_code == 403

    from conftest import OWNER

    allowed = client.patch(
        f"/v1/members/{SALES_2}",
        json={"languages": ["ar", "fr"]},
        headers=auth(OWNER),
    )
    assert allowed.status_code == 200
    assert allowed.json()["languages"] == ["ar", "fr"]


def test_the_last_owner_cannot_be_demoted(client) -> None:
    from conftest import OWNER

    response = client.patch(
        f"/v1/members/{OWNER}", json={"role": "sales"}, headers=auth(OWNER)
    )
    assert response.status_code == 409
    assert "owner" in response.json()["detail"].lower()


def test_teams_can_be_created_and_listed(client) -> None:
    from conftest import OWNER

    created = client.post(
        "/v1/teams", json={"name": "Aftersales"}, headers=auth(OWNER)
    )
    assert created.status_code == 201
    listed = client.get("/v1/teams", headers=auth(OWNER))
    assert "Aftersales" in {t["name"] for t in listed.json()}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/api && uv run pytest tests/test_me_and_team.py -v`
Expected: FAIL — 404 on `/v1/members`.

- [ ] **Step 3: Write the queries**

```python
# apps/api/src/dealerai/db/queries/team.py
"""SQL for members and teams. Plain asyncpg, like every other query module."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

MEMBERS = """
select m.user_id as id, m.role, m.languages, m.accepting_chats, m.last_assigned_at,
       p.full_name as name, p.email, p.avatar_url,
       coalesce(array_agg(tm.team_id) filter (where tm.team_id is not null), '{}') as team_ids,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open')                   as open_conversations
from memberships m
left join profiles p on p.id = m.user_id
left join team_members tm on tm.user_id = m.user_id and tm.tenant_id = m.tenant_id
where m.tenant_id = $1
group by m.user_id, m.role, m.languages, m.accepting_chats, m.last_assigned_at,
         p.full_name, p.email, p.avatar_url
order by p.full_name nulls last
"""


async def list_members(conn: asyncpg.Connection, tenant_id: UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in await conn.fetch(MEMBERS, tenant_id)]


async def count_owners(conn: asyncpg.Connection, tenant_id: UUID) -> int:
    return int(
        await conn.fetchval(
            "select count(*) from memberships where tenant_id = $1 and role = 'owner'", tenant_id
        )
    )
```

- [ ] **Step 4: Write the routes**

```python
# apps/api/src/dealerai/routes/team.py
"""Members and teams: who is here, what they may do, and who they work with."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from ..core.errors import Conflict, NotFound
from ..core.permissions import ROLES
from ..db.queries import team as q
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission

router = APIRouter(prefix="/v1", tags=["team"])

RequiresTeamAdmin = Annotated[TenantContext, Depends(require_permission("settings.team"))]


class MemberOut(BaseModel):
    id: UUID
    name: str | None
    email: str | None
    avatar_url: str | None
    role: str
    team_ids: list[UUID]
    languages: list[str]
    accepting_chats: bool
    open_conversations: int


class MemberPatch(BaseModel):
    role: str | None = None
    team_ids: list[UUID] | None = None
    languages: list[str] | None = None
    accepting_chats: bool | None = None


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    member_ids: list[UUID] = []


class TeamOut(BaseModel):
    id: UUID
    name: str
    member_ids: list[UUID]


@router.get("/members", response_model=list[MemberOut])
async def list_members(ctx: Ctx) -> list[MemberOut]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        return [MemberOut(**row) for row in await q.list_members(conn, ctx.tenant_id)]


@router.patch("/members/{user_id}", response_model=MemberOut)
async def patch_member(ctx: RequiresTeamAdmin, user_id: UUID, patch: MemberPatch) -> MemberOut:
    if patch.role is not None and patch.role not in ROLES:
        raise Conflict(f"unknown role {patch.role!r}")

    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        current = await conn.fetchrow(
            "select role from memberships where tenant_id = $1 and user_id = $2",
            ctx.tenant_id,
            user_id,
        )
        if current is None:
            raise NotFound("no such member")

        # A workspace with no owner cannot be recovered: nobody can invite, and
        # nobody can delete it. Refuse rather than explain it afterwards.
        if current["role"] == "owner" and patch.role not in (None, "owner"):
            if await q.count_owners(conn, ctx.tenant_id) == 1:
                raise Conflict("this is the last owner; promote someone else first")

        await conn.execute(
            """update memberships
               set role = coalesce($3, role),
                   languages = coalesce($4, languages),
                   accepting_chats = coalesce($5, accepting_chats)
               where tenant_id = $1 and user_id = $2""",
            ctx.tenant_id,
            user_id,
            patch.role,
            patch.languages,
            patch.accepting_chats,
        )
        if patch.team_ids is not None:
            await conn.execute(
                "delete from team_members where tenant_id = $1 and user_id = $2",
                ctx.tenant_id,
                user_id,
            )
            for team_id in patch.team_ids:
                await conn.execute(
                    """insert into team_members (tenant_id, team_id, user_id)
                       values ($1, $2, $3) on conflict do nothing""",
                    ctx.tenant_id,
                    team_id,
                    user_id,
                )
        rows = await q.list_members(conn, ctx.tenant_id)
    return next(MemberOut(**r) for r in rows if r["id"] == user_id)


@router.get("/teams", response_model=list[TeamOut])
async def list_teams(ctx: Ctx) -> list[TeamOut]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            """select t.id, t.name,
                      coalesce(array_agg(tm.user_id) filter (where tm.user_id is not null), '{}')
                        as member_ids
               from teams t
               left join team_members tm on tm.team_id = t.id
               where t.tenant_id = $1
               group by t.id, t.name order by t.name""",
            ctx.tenant_id,
        )
    return [TeamOut(**dict(r)) for r in rows]


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(ctx: RequiresTeamAdmin, body: TeamIn) -> TeamOut:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        team_id = await conn.fetchval(
            "insert into teams (tenant_id, name) values ($1, $2) returning id",
            ctx.tenant_id,
            body.name,
        )
        for user_id in body.member_ids:
            await conn.execute(
                """insert into team_members (tenant_id, team_id, user_id)
                   values ($1, $2, $3) on conflict do nothing""",
                ctx.tenant_id,
                team_id,
                user_id,
            )
    return TeamOut(id=team_id, name=body.name, member_ids=body.member_ids)
```

Register `team.router` in `main.py` next to `me.router`. `Conflict` (status 409) already exists in
`core/errors.py`.

- [ ] **Step 5: Run the tests and the suite**

Run: `cd apps/api && uv run pytest tests/test_me_and_team.py -v && uv run pytest && uv run mypy src && uv run ruff check .`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai/routes/team.py apps/api/src/dealerai/db/queries/team.py \
        apps/api/src/dealerai/main.py apps/api/tests/test_me_and_team.py
git commit -m "feat(sales): members and teams"
```

---

## Task 9: Seed a workspace worth looking at

**Files:**
- Create: `apps/api/src/dealerai/scripts/seed_sales.py`
- Modify: `package.json` (add `db:seed`)

- [ ] **Step 1: Write the script**

Timestamps are relative to now, so the inbox always looks alive. It refuses to run outside `local`,
for the same reason the test suite refuses a non-local DSN.

```python
# apps/api/src/dealerai/scripts/seed_sales.py
"""Local seed data: Pollux Motors with a team, cars and customers.

Run with `npm run db:seed`. Everything it writes is fictional; phone numbers use
an obviously fake block so nobody can message a real person from a demo.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg

from ..config import get_settings

TENANT = UUID("11111111-0000-4000-8000-000000000001")
PEOPLE = (
    ("Khalid Al Suwaidi", "owner", ("ar", "en"), None),
    ("Sara Mansour", "manager", ("ar", "en"), "both"),
    ("Ahmed Nasser", "sales", ("ar", "en"), "local"),
    ("Mohamed Riad", "sales", ("ar", "en"), "local"),
    ("Salem Bousaid", "sales", ("ar", "fr", "en"), "export"),
)
VEHICLES = (
    ("Toyota", "Hilux GR Sport", 2025, 16500000, "Black"),
    ("Toyota", "Hilux 2.8 Diesel", 2026, 12800000, "White"),
    ("Toyota", "Land Cruiser 4.0", 2024, 23500000, "Pearl"),
    ("BYD", "Seal 05", 2025, 8900000, "Blue"),
    ("BYD", "Leopard 7 Ultra", 2026, 21500000, "Black"),
    ("Changan", "X5 Plus", 2026, 7600000, "Grey"),
)
CUSTOMERS = (
    ("Omar Al Mazrouei", "+971500000101", "AE", "ar", "local"),
    ("Karim Benali", "+213500000102", "DZ", "fr", "export"),
    ("Youssef El Idrissi", "+212500000103", "MA", "fr", "export"),
    ("James Whitfield", "+971500000104", "AE", "en", "local"),
    ("Mona Fathy", "+201000000105", "EG", "ar", "local"),
)


async def seed() -> int:
    settings = get_settings()
    if settings.env != "local":
        print(f"refusing to seed: ENV is {settings.env!r}, expected 'local'", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(settings.migration_dsn)
    try:
        await conn.execute("delete from tenants where id = $1", TENANT)
        await conn.execute(
            """insert into tenants (id, slug, name, timezone, currency, locales, sales_settings)
               values ($1, 'pollux-motors', 'Pollux Motors', 'Asia/Dubai', 'AED',
                       '{en,ar,fr}', $2::jsonb)""",
            TENANT,
            '{"first_response_target_min": 5, "unassigned_visible_to_sales": true}',
        )
        teams = {}
        for key, name in (("local", "Local sales"), ("export", "Export")):
            teams[key] = await conn.fetchval(
                "insert into teams (tenant_id, name) values ($1, $2) returning id", TENANT, name
            )

        users: dict[str, UUID] = {}
        for full_name, role, languages, team in PEOPLE:
            user_id = uuid4()
            email = full_name.split()[0].lower() + "@pollux.test"
            await conn.execute("insert into auth.users (id, email) values ($1, $2)", user_id, email)
            await conn.execute(
                "insert into profiles (id, full_name, email) values ($1, $2, $3)",
                user_id,
                full_name,
                email,
            )
            await conn.execute(
                """insert into memberships (tenant_id, user_id, role, languages)
                   values ($1, $2, $3, $4)""",
                TENANT,
                user_id,
                role,
                list(languages),
            )
            for key in (("local", "export") if team == "both" else ([team] if team else [])):
                await conn.execute(
                    "insert into team_members (tenant_id, team_id, user_id) values ($1, $2, $3)",
                    TENANT,
                    teams[key],
                    user_id,
                )
            users[full_name.split()[0].lower()] = user_id

        for make, model, year, price, colour in VEHICLES:
            await conn.execute(
                """insert into vehicles (tenant_id, make, model, model_year, price_minor,
                                         exterior_color, status, listed_at)
                   values ($1, $2, $3, $4, $5, $6, 'available', now() - interval '40 days')""",
                TENANT,
                make,
                model,
                year,
                price,
                colour,
            )

        now = datetime.now(UTC)
        for i, (name, phone, country, language, kind) in enumerate(CUSTOMERS):
            owner = users["salem"] if kind == "export" else users["ahmed" if i % 2 else "mohamed"]
            team = teams["export" if kind == "export" else "local"]
            contact_id = uuid4()
            await conn.execute(
                """insert into contacts (id, tenant_id, full_name, locale, country, owner_id,
                                         team_id, last_seen_at)
                   values ($1, $2, $3, $4, $5, $6, $7, $8)""",
                contact_id,
                TENANT,
                name,
                language,
                country,
                owner,
                team,
                now - timedelta(hours=i),
            )
            await conn.execute(
                """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
                   values ($1, $2, 'phone', $3, true)""",
                TENANT,
                contact_id,
                phone,
            )
        print(f"seeded tenant {TENANT} — pollux-motors")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(seed()))
```

- [ ] **Step 2: Add the npm script**

```json
"db:seed": "cd apps/api && uv run python -m dealerai.scripts.seed_sales",
```

- [ ] **Step 3: Run it twice**

Run: `npm run db:seed && npm run db:seed`
Expected: both succeed — re-seeding deletes the tenant first, so it is repeatable.

- [ ] **Step 4: Check the visibility rules against real seed data**

```bash
cd apps/api && uv run python - <<'PY'
import asyncio
from dealerai.db.session import init_pool, tenant_session
from dealerai.scripts.seed_sales import TENANT

async def main():
    await init_pool()
    async with tenant_session(TENANT) as conn:
        rows = await conn.fetch("select full_name, owner_id from contacts order by full_name")
        print(len(rows), "customers seeded")
asyncio.run(main())
PY
```
Expected: `5 customers seeded`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/scripts/seed_sales.py package.json
git commit -m "feat(sales): local seed data for a dealer workspace"
```

---

## Task 10: Sign in locally as any seeded person

Local Postgres has no Supabase Auth server, so without this nobody can see the app as Ahmed or Sara.
It mints the token Supabase would, for a seeded person, and exists only when `ENV=local` — checked
when the router is registered **and** inside every handler, so a misconfigured deploy fails closed
twice.

**Files:**
- Modify: `apps/api/src/dealerai/scripts/seed_sales.py` (deterministic people)
- Create: `apps/api/src/dealerai/routes/dev.py`
- Modify: `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_dev_session.py`
- Create: `apps/web/lib/dev-auth.ts`
- Create: `apps/web/app/(auth)/dev-login/page.tsx`
- Modify: `apps/web/proxy.ts`, `apps/web/lib/supabase/server.ts`

- [ ] **Step 1: Make seeded people deterministic**

In `seed_sales.py`, add these helpers below the constants and use them in `seed()` in place of
`uuid4()` and the inline email for people:

```python
from uuid import NAMESPACE_URL, uuid5

TENANT_SLUG = "pollux-motors"
_PEOPLE_NS = uuid5(NAMESPACE_URL, "dealerai-os/seed/people")


def person_id(full_name: str) -> UUID:
    """Stable across re-seeds, so a dev session survives `npm run db:seed`."""
    return uuid5(_PEOPLE_NS, full_name)


def person_email(full_name: str) -> str:
    return full_name.split()[0].lower() + "@pollux.test"
```

```python
# inside seed(), in the people loop
        user_id = person_id(full_name)
        email = person_email(full_name)
```

- [ ] **Step 2: Write the failing test**

```python
# apps/api/tests/test_dev_session.py
from __future__ import annotations

from types import SimpleNamespace

import pytest

from dealerai.core.errors import NotFound
from dealerai.core.security import decode_supabase_jwt
from dealerai.routes import dev
from dealerai.scripts.seed_sales import PEOPLE, TENANT_SLUG, person_email, person_id


async def test_a_dev_session_is_a_token_the_api_accepts() -> None:
    name = PEOPLE[2][0]  # a salesperson
    session = await dev.create_session(dev.DevSessionIn(email=person_email(name)))
    user = decode_supabase_jwt(session.access_token)
    assert user.id == person_id(name)
    assert session.tenant_slug == TENANT_SLUG


async def test_an_unknown_email_gets_nothing() -> None:
    with pytest.raises(NotFound):
        await dev.create_session(dev.DevSessionIn(email="stranger@example.test"))


@pytest.mark.parametrize("env", ["staging", "production"])
async def test_outside_local_the_routes_do_not_exist(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setattr(dev, "get_settings", lambda: SimpleNamespace(env=env, supabase_jwt_secret="x"))
    with pytest.raises(NotFound):
        await dev.list_people()
    with pytest.raises(NotFound):
        await dev.create_session(dev.DevSessionIn(email=person_email(PEOPLE[0][0])))
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/test_dev_session.py -v`
Expected: FAIL — `cannot import name 'dev' from 'dealerai.routes'`.

- [ ] **Step 4: Write the route**

```python
# apps/api/src/dealerai/routes/dev.py
"""Local-only sign-in as a seeded person.

Mints the same HS256 token Supabase Auth would issue, using mint_test_token so
the claim shape cannot drift from what decode_supabase_jwt verifies. Registered
only when ENV=local, and every handler re-checks: a deploy that somehow includes
the router still answers 404.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import get_settings
from ..core.errors import NotFound
from ..core.security import mint_test_token
from ..scripts.seed_sales import PEOPLE, TENANT, TENANT_SLUG, person_email, person_id

router = APIRouter(prefix="/internal/dev", tags=["dev"])


class DevPerson(BaseModel):
    email: str
    name: str
    role: str


class DevSessionIn(BaseModel):
    email: str


class DevSession(BaseModel):
    access_token: str
    tenant_id: UUID
    tenant_slug: str


def _local_only() -> None:
    if get_settings().env != "local":
        raise NotFound("not found")


@router.get("/people", response_model=list[DevPerson])
async def list_people() -> list[DevPerson]:
    _local_only()
    return [DevPerson(email=person_email(name), name=name, role=role) for name, role, *_ in PEOPLE]


@router.post("/session", response_model=DevSession)
async def create_session(body: DevSessionIn) -> DevSession:
    _local_only()
    by_email = {person_email(name): name for name, *_ in PEOPLE}
    name = by_email.get(body.email)
    if name is None:
        raise NotFound("no seeded person with that email")
    token = mint_test_token(
        person_id(name),
        secret=get_settings().supabase_jwt_secret,
        email=body.email,
        expires_in_seconds=12 * 3600,
    )
    return DevSession(access_token=token, tenant_id=TENANT, tenant_slug=TENANT_SLUG)
```

In `main.py`, inside `create_app()` after the other routers:

```python
from .routes import dev
...
    if get_settings().env == "local":
        app.include_router(dev.router)
```

- [ ] **Step 5: Run the test**

Run: `npm run db:seed && cd apps/api && uv run pytest tests/test_dev_session.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: The web side — a dev login page and a cookie**

```ts
// apps/web/lib/dev-auth.ts
/**
 * Local-only sign-in. Active only when NEXT_PUBLIC_DEV_AUTH=1 in a non-production
 * build; the API route it calls exists only when the API runs with ENV=local.
 */
export const DEV_AUTH =
  process.env.NEXT_PUBLIC_DEV_AUTH === "1" && process.env.NODE_ENV !== "production";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DevPerson = { email: string; name: string; role: string };

export async function listDevPeople(): Promise<DevPerson[]> {
  const res = await fetch(`${API}/internal/dev/people`, { cache: "no-store" });
  if (!res.ok) throw new Error(`dev people: ${res.status}`);
  return res.json();
}

export async function startDevSession(email: string): Promise<string> {
  const res = await fetch(`${API}/internal/dev/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error(`dev session: ${res.status}`);
  const session: { access_token: string; tenant_slug: string } = await res.json();
  document.cookie = `dev_token=${session.access_token}; path=/; samesite=lax; max-age=43200`;
  return session.tenant_slug;
}
```

```tsx
// apps/web/app/(auth)/dev-login/page.tsx
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DEV_AUTH, listDevPeople, startDevSession, type DevPerson } from "@/lib/dev-auth";

export default function DevLoginPage() {
  const router = useRouter();
  const [people, setPeople] = useState<DevPerson[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (DEV_AUTH) listDevPeople().then(setPeople, (e: Error) => setError(e.message));
  }, []);

  if (!DEV_AUTH) return null;

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-3 p-6">
      <h1 className="text-xl font-semibold">Local sign-in</h1>
      <p className="text-muted text-sm">Seeded people only. This page does not exist in production.</p>
      {error && <p role="alert" className="text-danger text-sm">{error}</p>}
      {people.map((p) => (
        <button
          key={p.email}
          onClick={async () => router.push(`/${await startDevSession(p.email)}`)}
          className="border-border hover:bg-surface flex justify-between rounded-md border px-3 py-2 text-start text-sm"
        >
          <span>{p.name}</span>
          <span className="text-muted">{p.role}</span>
        </button>
      ))}
    </main>
  );
}
```

In `proxy.ts`, at the top of `proxy()` — the real Supabase path below it stays untouched:

```ts
  if (process.env.NEXT_PUBLIC_DEV_AUTH === "1" && process.env.NODE_ENV !== "production") {
    const { pathname } = request.nextUrl;
    if (pathname.startsWith("/dev-login") || request.cookies.get("dev_token")) {
      return NextResponse.next({ request });
    }
    const url = request.nextUrl.clone();
    url.pathname = "/dev-login";
    return NextResponse.redirect(url);
  }
```

In `lib/supabase/server.ts`, at the top of `getAccessToken()`:

```ts
  if (process.env.NEXT_PUBLIC_DEV_AUTH === "1" && process.env.NODE_ENV !== "production") {
    return (await cookies()).get("dev_token")?.value ?? null;
  }
```

Add `NEXT_PUBLIC_DEV_AUTH=1` to `apps/web/.env.local` (gitignored). Never to `.env.example`.

- [ ] **Step 7: Check it by hand**

Run: `npm run db:seed`, `npm run api` and in another terminal `npm run web`, then open
`http://localhost:3000`.
Expected: redirected to `/dev-login`; five seeded people; clicking Ahmed lands on
`/pollux-motors` without a Supabase project.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/dealerai/scripts/seed_sales.py apps/api/src/dealerai/routes/dev.py \
        apps/api/src/dealerai/main.py apps/api/tests/test_dev_session.py \
        apps/web/lib/dev-auth.ts "apps/web/app/(auth)/dev-login/page.tsx" \
        apps/web/proxy.ts apps/web/lib/supabase/server.ts
git commit -m "feat(sales): local sign-in as any seeded person"
```

---

## Task 11: Generated types and the typed client

**Files:**
- Create: `apps/api/src/dealerai/scripts/export_openapi.py`
- Modify: `apps/api/src/dealerai/routes/dev.py` (keep it out of the schema)
- Modify: `package.json` (root), `apps/web/package.json`
- Create: `apps/web/lib/api/{openapi.json,schema.ts}` (generated, committed)
- Create: `apps/web/lib/auth/token.ts`, `apps/web/lib/api/{client.ts,context.tsx,keys.ts,hooks.ts}`
- Create: `apps/web/lib/api/client.test.ts`, `apps/web/vitest.config.ts`
- Create: `apps/web/app/[tenant]/providers.tsx`
- Modify: `apps/web/app/[tenant]/layout.tsx`

- [ ] **Step 1: Install the dependencies**

Run:
```bash
npm install --workspace web @tanstack/react-query openapi-fetch
npm install --workspace web -D openapi-typescript vitest
```

- [ ] **Step 2: Write the failing test**

```ts
// apps/web/lib/api/client.test.ts
import { describe, expect, it } from "vitest";
import { ApiError, unwrap } from "./client";

describe("unwrap", () => {
  it("returns the data of a successful response", () => {
    const result = { data: { ok: 1 }, response: new Response(null, { status: 200 }) };
    expect(unwrap(result)).toEqual({ ok: 1 });
  });

  it("turns problem+json into an ApiError that carries the detail", () => {
    const problem = {
      type: "https://api.dealerai.os/errors/window-closed",
      title: "The 24-hour window is closed",
      status: 422,
      detail: "Send an approved template.",
    };
    try {
      unwrap({ error: problem, response: new Response(null, { status: 422 }) });
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).problem.status).toBe(422);
      expect((error as ApiError).message).toBe("Send an approved template.");
    }
  });

  it("still produces an error when a gateway answers without JSON", () => {
    const response = new Response(null, { status: 502, statusText: "Bad Gateway" });
    expect(() => unwrap({ error: undefined, response })).toThrow("Bad Gateway");
  });
});
```

```ts
// apps/web/vitest.config.ts
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: { environment: "node" },
});
```

In `apps/web/package.json` add `"test": "vitest run"` and append `&& npm run test` to `"check"`.

- [ ] **Step 3: Run it and watch it fail**

Run: `npm run test --workspace web`
Expected: FAIL — `Failed to resolve import "./client"`.

- [ ] **Step 4: Export the OpenAPI document deterministically**

```python
# apps/api/src/dealerai/scripts/export_openapi.py
"""Write the API's OpenAPI document where the web app generates its types from.

Sorted keys and a fixed indent make the output deterministic, so
`npm run check:openapi` can fail on any diff: a route or model changed without
regenerating the frontend types is drift, and drift is how a field quietly
disappears from a screen.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..main import app

OUT = Path(__file__).resolve().parents[4] / "web" / "lib" / "api" / "openapi.json"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The dev router must not appear in the schema, or local and CI output would differ. In
`routes/dev.py`:

```python
router = APIRouter(prefix="/internal/dev", tags=["dev"], include_in_schema=False)
```

Root `package.json` scripts:

```json
"api-types": "cd apps/api && uv run python -m dealerai.scripts.export_openapi && cd ../web && npx openapi-typescript lib/api/openapi.json -o lib/api/schema.ts",
"check:openapi": "npm run api-types && git diff --exit-code -- apps/web/lib/api/openapi.json apps/web/lib/api/schema.ts",
```

Run: `npm run api-types`
Expected: `wrote …/apps/web/lib/api/openapi.json` and a generated `schema.ts` containing `"/v1/me"`.

- [ ] **Step 5: Write the client**

```ts
// apps/web/lib/auth/token.ts
import { DEV_AUTH } from "@/lib/dev-auth";
import { createClient } from "@/lib/supabase/client";

/** The access token for API calls from the browser: the local dev cookie, or the Supabase session. */
export async function getBrowserAccessToken(): Promise<string | null> {
  if (DEV_AUTH) {
    const match = document.cookie.match(/(?:^|; )dev_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }
  const { data } = await createClient().auth.getSession();
  return data.session?.access_token ?? null;
}
```

```ts
// apps/web/lib/api/client.ts
import createFetchClient, { type Middleware } from "openapi-fetch";
import { getBrowserAccessToken } from "@/lib/auth/token";
import type { paths } from "./schema";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** RFC 9457 problem+json — the only error shape the API emits. */
export type Problem = {
  type: string;
  title: string;
  status: number;
  detail?: string;
  trace_id?: string;
};

export class ApiError extends Error {
  constructor(readonly problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

/**
 * openapi-fetch returns `{ data, error }`. Screens want a value or an exception,
 * because an exception is what React Query stores as the error state.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const e = (result.error ?? {}) as Partial<Problem>;
    throw new ApiError({
      type: e.type ?? "about:blank",
      title: e.title ?? result.response.statusText,
      status: e.status ?? result.response.status,
      detail: e.detail,
      trace_id: e.trace_id,
    });
  }
  return result.data as T;
}

/** A client bound to one tenant. The tenant is stated on every request, never remembered. */
export function createApiClient(tenantId: string) {
  const client = createFetchClient<paths>({ baseUrl: BASE });
  const auth: Middleware = {
    async onRequest({ request }) {
      const token = await getBrowserAccessToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      request.headers.set("X-Tenant-Id", tenantId);
      return request;
    },
  };
  client.use(auth);
  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;
```

```tsx
// apps/web/lib/api/context.tsx
"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createApiClient, type ApiClient } from "./client";

type TenantApi = { tenantId: string; slug: string; api: ApiClient };

const TenantApiContext = createContext<TenantApi | null>(null);

export function TenantApiProvider({
  tenantId,
  slug,
  children,
}: {
  tenantId: string;
  slug: string;
  children: ReactNode;
}) {
  const value = useMemo(() => ({ tenantId, slug, api: createApiClient(tenantId) }), [tenantId, slug]);
  return <TenantApiContext.Provider value={value}>{children}</TenantApiContext.Provider>;
}

export function useTenantApi(): TenantApi {
  const value = useContext(TenantApiContext);
  if (!value) throw new Error("useTenantApi must be used inside TenantApiProvider");
  return value;
}
```

```ts
// apps/web/lib/api/keys.ts
/** Every query key in one place, so an invalidation can never miss a spelling. */
export const keys = {
  me: (tenantId: string) => ["me", tenantId] as const,
  members: (tenantId: string) => ["members", tenantId] as const,
  teams: (tenantId: string) => ["teams", tenantId] as const,
};
```

```ts
// apps/web/lib/api/hooks.ts
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { unwrap } from "./client";
import { useTenantApi } from "./context";
import { keys } from "./keys";

export function useMe() {
  const { api, tenantId } = useTenantApi();
  return useQuery({
    queryKey: keys.me(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/me")),
  });
}

export function useSetAcceptingChats() {
  const { api, tenantId } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (accepting_chats: boolean) =>
      unwrap(await api.PATCH("/v1/me", { body: { accepting_chats } })),
    onSuccess: (me) => queryClient.setQueryData(keys.me(tenantId), me),
  });
}
```

```tsx
// apps/web/app/[tenant]/providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { TenantApiProvider } from "@/lib/api/context";

export function Providers({
  tenantId,
  slug,
  children,
}: {
  tenantId: string;
  slug: string;
  children: ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // A 403 or 404 will not turn into a 200 by asking again.
            retry: (count, error) =>
              !(error instanceof ApiError && error.problem.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <TenantApiProvider tenantId={tenantId} slug={slug}>
        {children}
      </TenantApiProvider>
    </QueryClientProvider>
  );
}
```

In `app/[tenant]/layout.tsx`, wrap the shell:

```tsx
import { Providers } from "./providers";
...
  return (
    <Providers tenantId={tenant.id} slug={tenant.slug}>
      <Shell tenant={tenant} tenants={tenants} locale={locale} pendingApprovals={pending}>
        {children}
      </Shell>
    </Providers>
  );
```

- [ ] **Step 6: Run the tests and the checks**

Run: `npm run test --workspace web && npm run check:web && npm run check:openapi`
Expected: 3 tests pass; typecheck, `check:rtl` and lint clean; `check:openapi` reports no diff
after the generated files are staged.

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json apps/web/package.json apps/web/vitest.config.ts \
        apps/api/src/dealerai/scripts/export_openapi.py apps/api/src/dealerai/routes/dev.py \
        apps/web/lib/api apps/web/lib/auth "apps/web/app/[tenant]/providers.tsx" \
        "apps/web/app/[tenant]/layout.tsx"
git commit -m "feat(sales): generated API types, typed client and React Query"
```

---

## Task 12: Catalogue, formatting and the sales shell

**Files:**
- Create: `apps/web/messages/en.ts`, `apps/web/messages/ar.ts`, `apps/web/messages/messages.test.ts`
- Modify: `apps/web/lib/i18n.ts`
- Create: `apps/web/lib/i18n-client.tsx`
- Create: `apps/web/lib/format.ts`, `apps/web/lib/format.test.ts`
- Create: `apps/web/components/{NavLinks,AvailabilitySwitch,ComingSoon}.tsx`
- Modify: `apps/web/components/Shell.tsx`, `apps/web/app/[tenant]/providers.tsx`, `apps/web/app/[tenant]/layout.tsx`, `apps/web/app/globals.css`
- Move: `apps/web/app/[tenant]/page.tsx` → `apps/web/app/[tenant]/command/page.tsx`
- Create: `apps/web/app/[tenant]/page.tsx` (redirect) and placeholder pages for inbox, today, customers, pipeline, tasks, dashboard

- [ ] **Step 1: Write the failing tests**

```ts
// apps/web/lib/format.test.ts
import { describe, expect, it } from "vitest";
import { countryFlag, formatDuration, formatMoney, formatRelative } from "./format";

describe("formatMoney", () => {
  it("shows whole dirhams without decimals", () => {
    expect(formatMoney({ amount_minor: 16500000, currency: "AED" })).toBe("AED 165,000");
  });
  it("keeps fils when there are some", () => {
    expect(formatMoney({ amount_minor: 16500050, currency: "AED" })).toBe("AED 165,000.50");
  });
});

describe("formatDuration", () => {
  it.each([
    [59, "59s"],
    [130, "2m 10s"],
    [3600, "1h"],
    [3720, "1h 2m"],
  ])("%i seconds reads as %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-09-16T12:00:00Z");
  it.each([
    ["2026-09-16T11:59:30Z", "<1m"],
    ["2026-09-16T11:57:00Z", "3m"],
    ["2026-09-16T09:00:00Z", "3h"],
    ["2026-09-14T12:00:00Z", "2d"],
  ])("%s is %s ago", (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });
});

describe("countryFlag", () => {
  it("turns an ISO code into a flag", () => {
    expect(countryFlag("dz")).toBe("🇩🇿");
  });
  it("returns nothing for junk rather than a broken glyph", () => {
    expect(countryFlag(null)).toBe("");
    expect(countryFlag("Algeria")).toBe("");
  });
});
```

```ts
// apps/web/messages/messages.test.ts
import { describe, expect, it } from "vitest";
import { ar } from "./ar";
import { en } from "./en";

describe("message catalogue", () => {
  it("has a non-empty Arabic string for every English key", () => {
    const missing = Object.keys(en).filter((key) => !ar[key as keyof typeof ar]?.trim());
    expect(missing).toEqual([]);
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npm run test --workspace web`
Expected: FAIL — `Failed to resolve import "./format"`.

- [ ] **Step 3: Write the formatting helpers**

```ts
// apps/web/lib/format.ts
/**
 * Money and time for display. Latin digits in both languages: prices and phone
 * numbers are read the same way everywhere in the UAE, and a price that changes
 * digit shape between languages invites a double-take on the one number that
 * must not be misread.
 */
export type Money = { amount_minor: number; currency: string };

export function formatMoney(money: Money): string {
  const major = money.amount_minor / 100;
  const digits = Number.isInteger(major) ? 0 : 2;
  const amount = major.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${money.currency} ${amount}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = Math.round(seconds % 60);
    return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

export function formatRelative(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "<1m";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)}d`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function formatDateTime(iso: string, timeZone: string, locale: "en" | "ar" = "en"): string {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-AE-u-nu-latn" : "en-GB", {
    timeZone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function countryFlag(iso2: string | null): string {
  if (!iso2 || !/^[A-Za-z]{2}$/.test(iso2)) return "";
  return String.fromCodePoint(
    ...[...iso2.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65),
  );
}
```

- [ ] **Step 4: Move the catalogue into `messages/`**

```ts
// apps/web/messages/en.ts
export const en = {
  "nav.inbox": "Inbox",
  "nav.today": "My day",
  "nav.customers": "Customers",
  "nav.pipeline": "Pipeline",
  "nav.tasks": "Tasks",
  "nav.dashboard": "Dashboard",
  "nav.inventory": "Inventory",
  "nav.approvals": "Approvals",
  "nav.settings": "Settings",
  "nav.marketing": "Marketing",
  "nav.command": "Command Center",
  "nav.content": "Content",
  "availability.taking": "Taking chats",
  "availability.away": "Not taking chats",
  "common.comingSoon": "This screen arrives in a later slice.",
  "approvals.title": "Approvals",
  "approvals.empty": "Nothing waiting on you.",
  "approvals.approve": "Approve",
  "approvals.reject": "Reject",
  "approvals.requires": "Requires",
  "auth.signIn": "Sign in",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.working": "Signing in…",
  "workspace.switch": "Workspace",
  "workspace.none": "No workspace yet",
} as const;
```

```ts
// apps/web/messages/ar.ts
import type { en } from "./en";

// `satisfies` makes a missing Arabic key a type error, not a blank button in Dubai.
export const ar = {
  "nav.inbox": "المحادثات",
  "nav.today": "يومي",
  "nav.customers": "العملاء",
  "nav.pipeline": "مسار المبيعات",
  "nav.tasks": "المهام",
  "nav.dashboard": "لوحة المتابعة",
  "nav.inventory": "المخزون",
  "nav.approvals": "الموافقات",
  "nav.settings": "الإعدادات",
  "nav.marketing": "التسويق",
  "nav.command": "مركز القيادة",
  "nav.content": "المحتوى",
  "availability.taking": "أستقبل المحادثات",
  "availability.away": "لا أستقبل المحادثات",
  "common.comingSoon": "هذه الشاشة قادمة في مرحلة لاحقة.",
  "approvals.title": "الموافقات",
  "approvals.empty": "لا يوجد ما ينتظر موافقتك.",
  "approvals.approve": "موافقة",
  "approvals.reject": "رفض",
  "approvals.requires": "يتطلب",
  "auth.signIn": "تسجيل الدخول",
  "auth.email": "البريد الإلكتروني",
  "auth.password": "كلمة المرور",
  "auth.working": "جارٍ تسجيل الدخول…",
  "workspace.switch": "مساحة العمل",
  "workspace.none": "لا توجد مساحة عمل",
} satisfies Record<keyof typeof en, string>;
```

Replace the `MESSAGES` object in `lib/i18n.ts`, keeping `LOCALES`, `dirFor` and `t` exactly as they are:

```ts
import { ar } from "@/messages/ar";
import { en } from "@/messages/en";

const MESSAGES = { en, ar } as const;

export type MessageKey = keyof typeof en;
```

```tsx
// apps/web/lib/i18n-client.tsx
"use client";

import { createContext, useContext, type ReactNode } from "react";
import { type Locale, type MessageKey, t } from "./i18n";

const LocaleContext = createContext<Locale>("en");

export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

export function useT(): (key: MessageKey) => string {
  const locale = useContext(LocaleContext);
  return (key) => t(locale, key);
}
```

Give `Providers` the locale, and pass it from the layout, which already reads it from the cookie:

```tsx
// apps/web/app/[tenant]/providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { TenantApiProvider } from "@/lib/api/context";
import type { Locale } from "@/lib/i18n";
import { LocaleProvider } from "@/lib/i18n-client";

export function Providers({
  tenantId,
  slug,
  locale,
  children,
}: {
  tenantId: string;
  slug: string;
  locale: Locale;
  children: ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // A 403 or 404 will not turn into a 200 by asking again.
            retry: (count, error) =>
              !(error instanceof ApiError && error.problem.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <TenantApiProvider tenantId={tenantId} slug={slug}>
        <LocaleProvider locale={locale}>{children}</LocaleProvider>
      </TenantApiProvider>
    </QueryClientProvider>
  );
}
```

```tsx
// apps/web/app/[tenant]/layout.tsx — the opening tag of the wrapper
    <Providers tenantId={tenant.id} slug={tenant.slug} locale={locale}>
```

- [ ] **Step 5: Run the tests**

Run: `npm run test --workspace web`
Expected: PASS — the unwrap tests from Task 11, 11 formatting cases and the catalogue check.

- [ ] **Step 6: The sales shell**

Add the status colour the availability dot needs, beside the existing tokens in `globals.css`
(light block `--success: #067647;`, dark block `--success: #47cd89;`, and
`--color-success: var(--success);` inside `@theme inline`).

```tsx
// apps/web/components/NavLinks.tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

export type NavItem = { href: string; key: MessageKey; permission?: string };

/** Links a role cannot use are hidden. Cosmetic only — the API refuses anyway. */
export function NavLinks({
  slug,
  items,
  badges = {},
}: {
  slug: string;
  items: readonly NavItem[];
  badges?: Partial<Record<MessageKey, number>>;
}) {
  const t = useT();
  const pathname = usePathname();
  const me = useMe();
  const allowed = items.filter(
    (item) => !item.permission || me.data?.permissions.includes(item.permission),
  );
  return (
    <>
      {allowed.map((item) => {
        const href = `/${slug}${item.href}`;
        const active = pathname.startsWith(href);
        return (
          <Link
            key={item.key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-start transition-colors ${
              active ? "bg-background font-medium" : "hover:bg-background"
            }`}
          >
            <span>{t(item.key)}</span>
            {(badges[item.key] ?? 0) > 0 && (
              <span className="bg-accent min-w-5 rounded-full px-1.5 py-0.5 text-center text-xs font-medium text-black">
                {badges[item.key]}
              </span>
            )}
          </Link>
        );
      })}
    </>
  );
}
```

```tsx
// apps/web/components/AvailabilitySwitch.tsx
"use client";

import { useMe, useSetAcceptingChats } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

export function AvailabilitySwitch() {
  const t = useT();
  const me = useMe();
  const setAccepting = useSetAcceptingChats();
  if (!me.data) return null;
  const on = me.data.accepting_chats;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={setAccepting.isPending}
      onClick={() => setAccepting.mutate(!on)}
      className="hover:bg-background flex items-center gap-2 rounded-md px-3 py-2 text-sm"
    >
      <span aria-hidden className={`size-2 rounded-full ${on ? "bg-success" : "bg-muted"}`} />
      {on ? t("availability.taking") : t("availability.away")}
    </button>
  );
}
```

```tsx
// apps/web/components/ComingSoon.tsx
"use client";

import { useMe } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

/** A placeholder that also proves who the API thinks you are. */
export function ComingSoon({ titleKey }: { titleKey: MessageKey }) {
  const t = useT();
  const me = useMe();
  return (
    <section className="flex flex-col gap-2">
      <h1 className="text-2xl font-semibold tracking-tight">{t(titleKey)}</h1>
      <p className="text-muted text-sm">{t("common.comingSoon")}</p>
      {me.data && (
        <p className="text-muted text-xs">
          {me.data.user.name} · {me.data.role} · {me.data.scope}
        </p>
      )}
      {me.isError && (
        <p role="alert" className="text-danger text-sm">
          {me.error.message}
        </p>
      )}
    </section>
  );
}
```

In `components/Shell.tsx`, replace `NAV` and the `<nav>` block (the grid layout, logo, locale toggle
and workspace switcher stay):

```tsx
import { AvailabilitySwitch } from "./AvailabilitySwitch";
import { NavLinks, type NavItem } from "./NavLinks";

const SALES: readonly NavItem[] = [
  { href: "/inbox", key: "nav.inbox" },
  { href: "/today", key: "nav.today" },
  { href: "/customers", key: "nav.customers" },
  { href: "/pipeline", key: "nav.pipeline" },
  { href: "/tasks", key: "nav.tasks" },
  { href: "/dashboard", key: "nav.dashboard", permission: "dashboard.manager" },
  { href: "/inventory", key: "nav.inventory" },
  { href: "/approvals", key: "nav.approvals" },
  { href: "/settings", key: "nav.settings" },
];
const MARKETING: readonly NavItem[] = [
  { href: "/command", key: "nav.command" },
  { href: "/content", key: "nav.content" },
];
const MOBILE: readonly NavItem[] = SALES.slice(0, 4).concat({ href: "/settings", key: "nav.settings" });

// …inside the <aside>, in place of the old <nav>:
        <nav className="hidden flex-col gap-1 md:flex">
          <NavLinks slug={tenant.slug} items={SALES} badges={{ "nav.approvals": pendingApprovals }} />
          <p className="text-muted mt-4 px-3 text-xs uppercase tracking-wide">
            {t(locale, "nav.marketing")}
          </p>
          <NavLinks slug={tenant.slug} items={MARKETING} />
        </nav>
        <div className="mt-auto hidden md:block">
          <AvailabilitySwitch />
        </div>

// …and after <main>, the phone navigation:
      <nav className="border-border bg-surface fixed inset-x-0 bottom-0 flex justify-around border-t p-2 md:hidden">
        <NavLinks slug={tenant.slug} items={MOBILE} />
      </nav>
```

Give `<main>` `pb-20 md:pb-8` so the bottom bar never covers content. The approvals count now
reaches the sidebar through the `badges` prop above, so delete the old inline badge markup from
`Shell` along with the old `NAV` loop.

- [ ] **Step 7: Routes**

```bash
git mv "apps/web/app/[tenant]/page.tsx" "apps/web/app/[tenant]/command/page.tsx"
```

```tsx
// apps/web/app/[tenant]/page.tsx
import { redirect } from "next/navigation";

export default async function TenantHome({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = await params;
  redirect(`/${tenant}/inbox`);
}
```

One placeholder per new route, for example:

```tsx
// apps/web/app/[tenant]/inbox/page.tsx
import { ComingSoon } from "@/components/ComingSoon";

export default function InboxPage() {
  return <ComingSoon titleKey="nav.inbox" />;
}
```

Create the same for `today` (`nav.today`), `customers` (`nav.customers`), `pipeline`
(`nav.pipeline`), `tasks` (`nav.tasks`) and `dashboard` (`nav.dashboard`).

- [ ] **Step 8: Check it by hand, in both languages**

Run: `npm run db:seed`, `npm run api`, `npm run web`; sign in at `/dev-login`.
Expected:
- As **Ahmed**: lands on Inbox; the placeholder reads "Ahmed Nasser · sales · own"; no Dashboard link.
- As **Sara**: the Dashboard link is visible; the placeholder reads "… · manager · team".
- The availability switch survives a page reload.
- Switching to العربية mirrors the sidebar to the right and the labels are Arabic.
- At 360px the bottom bar shows five items and covers nothing.

- [ ] **Step 9: Run the checks and commit**

Run: `npm run check:web`
Expected: typecheck, `check:rtl`, lint and tests all pass.

```bash
git add apps/web
git commit -m "feat(sales): sales navigation, availability switch and the message catalogue"
```

---

## Task 13: CI and the finish line

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/sales/README.md`

- [ ] **Step 1: Test on the Postgres version production runs**

The `api` job still uses `pgvector/pgvector:pg15`, while the local container and the Supabase
project run 17. Row-level security is exactly the behaviour a major-version difference can change,
so in `ci.yml`:

```yaml
    services:
      db:
        image: pgvector/pgvector:pg17
```

- [ ] **Step 2: Run the web unit tests in CI**

In the `web` job's "Check web" step:

```yaml
        run: |
          npm run typecheck
          npm run check:rtl
          npm run lint
          npm run test
          npm run build
```

- [ ] **Step 3: Fail CI when the generated types are stale**

Add a third job:

```yaml
  contract:
    runs-on: ubuntu-latest
    env:
      ENV: local
      LOG_LEVEL: warning
      DATABASE_URL: postgresql://dealerai_app:dealerai_app@localhost:54332/dealerai
      MIGRATION_DATABASE_URL: postgresql://postgres:postgres@localhost:54332/dealerai
      GOOGLE_API_KEY: ""
      SUPABASE_JWT_SECRET: super-secret-jwt-token-with-at-least-32-characters-long
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm

      - run: npm ci

      - name: Install API
        working-directory: apps/api
        run: uv sync --all-extras --dev

      # A route or model changed without regenerating apps/web/lib/api is drift.
      # Exporting the schema needs no database: nothing connects at import time.
      - name: Generated API types are current
        run: npm run check:openapi
```

- [ ] **Step 4: Run the S0 exit criteria locally**

```bash
npm run db:reset && npm run db:seed
npm run check
npm run check:openapi
```

Expected: ruff, mypy, pytest (including `test_sales_schema`, `test_visibility`, `test_permissions`,
`test_deps_scope`, `test_me_and_team`, `test_dev_session`), the 100%-branch guard suite, web
typecheck, `check:rtl`, lint and Vitest all pass; `check:openapi` shows no diff.

Then repeat the walkthrough from Task 12 Step 8 as Khalid, Sara, Ahmed and Salem.

- [ ] **Step 5: Record the state**

In `docs/sales/README.md`, replace the Code row of the status table:

```markdown
| Code | **S0 foundation complete** on `sales/phase-1`: visibility enforced in Postgres, `/v1/me`, members and teams, local sign-in, generated types, the sales shell |
```

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml docs/sales/README.md
git commit -m "ci(sales): Postgres 17, web unit tests and the OpenAPI drift check"
```

---

## Spec coverage

| S0 scope ([../09-implementation-plan.md](../09-implementation-plan.md)) | Task |
|---|---|
| Migration `0006_sales_core`: teams, identities, ownership columns | 1 |
| Visibility carried by the session | 2 |
| Visibility policies and the rep / manager / owner matrix | 3 |
| Browser table access revoked ([../01-architecture.md](../01-architecture.md) §2 A) | 4 |
| Manager role, permissions and scope | 5, 6 |
| `/v1/me` | 7 |
| Members and teams routes | 8 |
| Seed script | 9 |
| Local sign-in ([../01-architecture.md](../01-architecture.md) §7) | 10 |
| Generated frontend types, typed client, React Query | 11 |
| Message catalogue, formatting helpers, sales shell | 12 |
| CI additions | 13 |

## Deliberately not in this slice

| Item | Arrives with |
|---|---|
| Identity resolution code and conversation ingest | S1 |
| Live-update triggers and the SSE stream | S2 |
| shadcn/ui components | S2, with the first screen that needs them |
| `tasks` table and its visibility policy | S3 |
| `app.reassign_contact`, `app.merge_contacts` and the owner invariant test | S3 |
| `pipelines`, `pipeline_stages` and the leads stage change | S3 |

## Execution

Run task by task on `sales/phase-1`, with `superpowers:subagent-driven-development` (a fresh subagent
per task and a review between tasks) or `superpowers:executing-plans` (one session, with
checkpoints). Every task ends with a green suite and one commit.
