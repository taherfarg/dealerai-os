# Sales S3 — CRM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** a lead goes from new to won in the browser. A salesperson opens a customer from the
thread, records what the customer wants, creates a lead, moves it through the stages, books the
follow-up as a task, completes it and marks the lead won — and a manager reassigns that customer to
someone else and watches the conversations, leads and tasks move with them.

**Architecture:** the CRM is the same rows the inbox already writes, given names and structure.
Pipelines and stages become tables so a dealership can shape its own board; `leads.stage` (a text
enum) becomes `stage_id`, and stage history moves to `activities`, which already exists. Two
SECURITY DEFINER functions — `app.reassign_contact` and `app.merge_contacts` — are the single
writers for the two operations that touch five tables at once, because an ownership change that
half-applies is worse than one that fails. Everything a person can know about a customer lives in
one `contacts.profile` jsonb where every field carries who set it: a value the AI inferred is
marked, and editing it makes it a person's. Scoring is a pure function over signals, so S4 can add
AI signals without touching the arithmetic. Live updates reuse S2's trigger → `pg_notify` → SSE
path; `leads` and `tasks` join it by extending one trigger function.

**Tech stack:** Postgres 17 (RLS, SECURITY DEFINER, triggers, jsonb) · asyncpg · FastAPI · Pydantic
v2 · Next.js 16 · React 19 · TanStack Query · Tailwind v4 · Vitest · pytest.

**Before you start:**

- Docker Desktop running; prefix database commands with `COMPOSE_PROJECT_NAME=dealeraios` in this
  worktree. Branch `sales/phase-1`.
- **Stop the worker before running the suite.** A worker attached to the development database
  claims the tests' events; it cost an afternoon in S2 ([s2-inbox.md](s2-inbox.md) § Review).
- Read [../06-api-contract.md](../06-api-contract.md) §4–§6 (the routes),
  [../08-screens.md](../08-screens.md) §5–§10 (the six screens), [../02-data-model.md](../02-data-model.md)
  §2–§6 (the tables, the policies, the indexes) and [../05-workflows.md](../05-workflows.md) §9–§10
  (reassign and merge). They are the specification; this plan implements them.
- **The lesson S2 left:** the exit run found three defects behind 874 passing tests, and the worst
  one — a reply that never stopped the waiting timer — survived a whole task about the waiting timer
  because its test did the clearing itself in SQL and asserted the quiet that followed. **A test that
  sets up state the production code should have written proves nothing about the path.** Drive the
  real path, or you are testing your own fixture.

---

## What this slice does not build

| Item | Arrives with |
|---|---|
| AI-written profile fields, summaries, automatic leads, AI signals in the score ([04](../04-ai-copilot.md) §4–§5) | S4 |
| AI follow-up tasks, the follow-up card and `POST /v1/tasks/{id}/send-draft` | S4 |
| Instagram and Messenger identities on the customer record | S5 (the channels arrive there) |
| `GET /v1/customers/{id}/export` and `DELETE /v1/customers/{id}` — PDPL export and erasure | S6, with the retention job in [02](../02-data-model.md) §7. **Must land before the pilot in S7** |
| The manager dashboard, the daily brief, settings screens | S6 |
| Bulk reassign from the customers list ([08](../08-screens.md) §7) | S6 — the single-customer path is here, and bulk is the same call in a loop behind a confirm |
| Per-tenant scoring weights in the UI ([04](../04-ai-copilot.md) §5) | Not in Phase 1; they live in `sales_settings` and are read by this slice |

---

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0009_sales_crm.sql` | **Create.** `pipelines`, `pipeline_stages`, `tasks`; `leads` gains a pipeline and loses its enum; policies, indexes, live-update triggers; `app.reassign_contact`, `app.merge_contacts` |
| `apps/api/src/dealerai/sales/profile.py` | **Create.** The customer profile: which fields exist, and who set each value |
| `apps/api/src/dealerai/sales/scoring.py` | **Create.** Pure: signals in, score, band and reasons out |
| `apps/api/src/dealerai/db/queries/crm.py` | **Create.** The customers, timeline, leads and tasks SQL, in one place |
| `apps/api/src/dealerai/routes/customers.py` | **Create.** List, detail, timeline, edit, reassign, merge |
| `apps/api/src/dealerai/routes/pipelines.py` | **Create.** `GET /v1/pipelines`, `PUT /v1/pipelines/{id}/stages` |
| `apps/api/src/dealerai/routes/leads.py` | **Create.** List, create, detail, stage and owner moves |
| `apps/api/src/dealerai/routes/tasks.py` | **Create.** List by bucket, create, edit, complete |
| `apps/api/src/dealerai/routes/dashboard.py` | **Create.** `GET /v1/dashboard/me` — My day |
| `apps/api/src/dealerai/events/handlers/crm.py` | **Create.** `contact.reassigned` → tell the new owner |
| `apps/api/src/dealerai/events/handlers/parked.py` | **Modify.** Remove `contact.reassigned` |
| `apps/api/src/dealerai/routes/tenants.py` | **Modify.** A new workspace gets a default pipeline |
| `apps/api/src/dealerai/scripts/seed_sales.py` | **Modify.** Two pipelines, leads across the board, tasks due today and overdue |
| `apps/web/lib/api/{keys,hooks}.ts`, `lib/live.tsx` | **Modify.** Customer, lead and task queries; what a `lead.*` or `task.*` event invalidates |
| `apps/web/lib/filters.ts` | **Create.** Filters that live in the URL, so a shared link shows the same list |
| `apps/web/app/[tenant]/customers/page.tsx`, `[contactId]/page.tsx` | **Create.** The list and the 360 |
| `apps/web/app/[tenant]/pipeline/page.tsx` | **Create.** The board and the lead drawer |
| `apps/web/app/[tenant]/tasks/page.tsx`, `today/page.tsx` | **Create.** Tasks and My day |
| `apps/web/components/crm/*` | **Create.** Customer panel, profile editor, timeline, reassign and merge dialogs, lead card, board column, lead drawer, task row |
| `apps/web/messages/{en,ar}.ts` | **Modify.** Every string this slice shows |

---
## Task 1: The tables a pipeline needs

**Files:**
- Create: `supabase/migrations/0009_sales_crm.sql`
- Create: `apps/api/tests/test_crm_schema.py`

`leads.stage` is a text enum with seven values. Every dealership sorts its work differently, and
Pollux already needs two boards, so the enum becomes rows. Nothing reads the column yet — the CRM
code does not exist — which is what makes this the cheap moment.

- [ ] **Step 1: Write the migration**

```sql
-- docs/sales/02-data-model.md § 2, § 4, § 5, § 6
-- =============================================================================
-- PIPELINES
-- A stage is a row because every dealership sorts its work differently, and
-- Pollux needs two boards on day one. "At least one lost stage" and "a stage
-- with leads cannot be deleted" are checked in the API, with the count in the
-- error: a deferred constraint trigger for a rule one endpoint can break is not
-- worth its weight.
-- =============================================================================
create table pipelines (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  name        text not null,
  position    int not null default 0,
  is_default  boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, name)
);
create unique index pipelines_default_uq on pipelines (tenant_id) where is_default;

create table pipeline_stages (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  pipeline_id uuid not null references pipelines(id) on delete cascade,
  name        text not null,
  position    int not null default 0,
  category    text not null check (category in ('open', 'won', 'lost')),
  created_at  timestamptz not null default now(),
  unique (pipeline_id, name)
);
create unique index pipeline_stages_won_uq on pipeline_stages (pipeline_id)
  where category = 'won';
create index on pipeline_stages (tenant_id, pipeline_id, position);

-- =============================================================================
-- TASKS
-- assignee_id is the visibility column: a task is somebody's, always.
-- A lead's "next action" is its earliest open task — computed, never stored,
-- which is why leads.next_action_at goes below.
-- =============================================================================
create table tasks (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  title           text not null,
  kind            text not null default 'todo'
                    check (kind in ('follow_up', 'call', 'meeting', 'todo')),
  due_at          timestamptz not null,
  status          text not null default 'open'
                    check (status in ('open', 'done', 'cancelled')),
  completed_at    timestamptz,
  cancel_reason   text,
  assignee_id     uuid not null references auth.users(id) on delete cascade,
  created_by      uuid references auth.users(id) on delete set null,
  contact_id      uuid references contacts(id) on delete set null,
  lead_id         uuid references leads(id) on delete set null,
  conversation_id uuid references conversations(id) on delete set null,
  source          text not null default 'human' check (source in ('human', 'ai', 'rule')),
  ai_draft        jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index on tasks (tenant_id, assignee_id, status, due_at);
create index on tasks (tenant_id, due_at) where status = 'open';
create index on tasks (tenant_id, lead_id, due_at) where status = 'open';

create trigger tasks_touch before update on tasks
  for each row execute function app.touch_updated_at();
create trigger pipelines_touch before update on pipelines
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- LEADS MOVE ONTO A PIPELINE
-- The view depends on the column being dropped, so it goes first and comes back
-- at the end over pipeline_stages.category.
-- =============================================================================
drop view if exists v_lead_funnel;

alter table leads
  add column pipeline_id      uuid references pipelines(id) on delete restrict,
  add column stage_id         uuid references pipeline_stages(id) on delete restrict,
  add column stage_entered_at timestamptz not null default now(),
  add column score_signals    jsonb not null default '[]'::jsonb;

-- Every existing tenant gets the default pipeline its leads already implied,
-- and each lead lands on the stage its enum named.
do $$
declare
  t record;
  pipeline uuid;
  stage record;
begin
  for t in select id from tenants loop
    insert into pipelines (tenant_id, name, position, is_default)
      values (t.id, 'Sales', 0, true)
      returning id into pipeline;
    for stage in
      select * from (values
        ('New', 0, 'open'), ('Contacted', 1, 'open'), ('Qualified', 2, 'open'),
        ('Appointment', 3, 'open'), ('Negotiation', 4, 'open'),
        ('Won', 5, 'won'), ('Lost', 6, 'lost')
      ) as s(name, position, category)
    loop
      insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
        values (t.id, pipeline, stage.name, stage.position, stage.category);
    end loop;
    update leads l set
      pipeline_id = pipeline,
      stage_id = (select s.id from pipeline_stages s
                   where s.pipeline_id = pipeline and lower(s.name) = l.stage)
    where l.tenant_id = t.id;
  end loop;
end $$;

alter table leads
  alter column pipeline_id set not null,
  alter column stage_id set not null,
  drop column stage,
  drop column next_action_at;

create index on leads (tenant_id, pipeline_id, stage_id);

-- "Qualified" was the third of seven fixed stages; with configurable stages the
-- nearest honest definition is "past the first two columns and not lost". The
-- view belongs to marketing's reporting, which is why it keeps its old shape.
create view v_lead_funnel with (security_invoker = true) as
select
  l.tenant_id,
  date_trunc('day', l.created_at)                                 as day,
  count(*)                                                        as leads,
  count(*) filter (where l.intent_band = 'hot')                   as hot_leads,
  count(*) filter (where s.category <> 'lost' and s.position >= 2) as qualified,
  count(*) filter (where s.category = 'won')                      as won
from leads l
join pipeline_stages s on s.id = l.stage_id
group by 1, 2;

-- =============================================================================
-- VISIBILITY (docs/sales/02-data-model.md § 4)
-- A pipeline is the workspace's shape, so it is tenant-wide. A task is one
-- person's work, so it follows the same owner rule as everything else.
-- =============================================================================
alter table pipelines enable row level security;
alter table pipelines force row level security;
create policy tenant_isolation on pipelines
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

alter table pipeline_stages enable row level security;
alter table pipeline_stages force row level security;
create policy tenant_isolation on pipeline_stages
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

alter table tasks enable row level security;
alter table tasks force row level security;
create policy tenant_visibility on tasks
  using (
    app.has_tenant_access(tenant_id)
    and (
      (select app.visible_owner_ids()) is null
      or assignee_id = any (coalesce((select app.visible_owner_ids()), '{}'))
    )
  )
  with check (app.has_tenant_access(tenant_id));

revoke all on pipelines, pipeline_stages, tasks from anon, authenticated;

-- =============================================================================
-- LIVE UPDATES
-- A lead and a task carry their own owner, so the payload reads the row before
-- it reads the conversation. Same trigger function, two more tables, nothing
-- for a new write path to forget.
-- =============================================================================
create or replace function app.notify_rt()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  row_json jsonb := to_jsonb(new);
  conversation public.conversations%rowtype;
  payload jsonb;
begin
  if coalesce(current_setting('app.suppress_rt', true), '') = 'on' then
    return null;
  end if;

  if tg_table_name = 'messages' then
    select * into conversation from public.conversations c where c.id = new.conversation_id;
  elsif tg_table_name = 'conversations' then
    conversation := new;
  end if;

  payload := jsonb_build_object(
    'tenant_id', row_json->>'tenant_id',
    'type', tg_argv[0],
    'id', row_json->>'id',
    'conversation_id', coalesce(row_json->>'conversation_id', conversation.id::text),
    'owner_id', coalesce(row_json->>'owner_id', conversation.owner_id::text),
    'assigned_to', coalesce(row_json->>'assigned_to', row_json->>'assignee_id',
                            conversation.assigned_to::text),
    'team_id', coalesce(row_json->>'team_id', conversation.team_id::text),
    'user_id', row_json->>'user_id'
  );
  perform pg_notify('rt', payload::text);
  return null;
end $fn$;

revoke all on function app.notify_rt() from public;

create trigger leads_rt after insert or update on leads
  for each row execute function app.notify_rt('lead.updated');
create trigger tasks_rt after insert or update on tasks
  for each row execute function app.notify_rt('task.updated');
```

The payload builder changed shape: it now reads `owner_id`, `assignee_id` and `team_id` off the row
before falling back to the conversation, so one function serves six tables. Check the S2 tests still
pass (`tests/test_realtime.py`) — a conversation's payload must be exactly what it was.

- [ ] **Step 2: Reset the database and see it apply**

```bash
COMPOSE_PROJECT_NAME=dealeraios npm run db:reset && npm run db:seed
```

Expected: `apply 0009_sales_crm.sql ... done`, then the seed's summary line. A failure here means the
backfill left a lead without a stage — fix the migration, not the seed.

- [ ] **Step 3: Write the schema test**

Create `apps/api/tests/test_crm_schema.py`, in the shape of `tests/test_inbox_schema.py`:

```python
"""The shape the CRM reads: pipelines, stages, tasks, and a lead that sits on one."""

from __future__ import annotations

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B, USER_A, USER_B
from dealerai.db.session import tenant_session


async def test_a_pipeline_has_exactly_one_won_stage(db: None, su: asyncpg.Connection) -> None:
    pipeline = await su.fetchval(
        "insert into pipelines (tenant_id, name) values ($1, 'Export') returning id", TENANT_A
    )
    await su.execute(
        """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
           values ($1, $2, 'Won', 0, 'won')""",
        TENANT_A,
        pipeline,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(
            """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
               values ($1, $2, 'Also won', 1, 'won')""",
            TENANT_A,
            pipeline,
        )


async def test_a_task_is_always_somebody_s(db: None, su: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.NotNullViolationError):
        await su.execute(
            """insert into tasks (tenant_id, title, due_at, assignee_id)
               values ($1, 'Call Omar', now(), null)""",
            TENANT_A,
        )


async def test_a_salesperson_sees_their_own_tasks_and_not_a_colleague_s(
    db: None, su: asyncpg.Connection
) -> None:
    for user in (USER_A, USER_B):
        await su.execute(
            """insert into tasks (tenant_id, title, due_at, assignee_id)
               values ($1, 'Call back', now(), $2)""",
            TENANT_A,
            user,
        )
    async with tenant_session(TENANT_A, user_id=USER_A, scope="own") as conn:
        assert await conn.fetchval("select count(*) from tasks") == 1
    async with tenant_session(TENANT_A, scope="all") as conn:
        assert await conn.fetchval("select count(*) from tasks") == 2


async def test_another_tenant_s_pipeline_is_not_there(db: None, su: asyncpg.Connection) -> None:
    await su.execute("insert into pipelines (tenant_id, name) values ($1, 'Theirs')", TENANT_B)
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select count(*) from pipelines where name = 'Theirs'") == 0


async def test_a_lead_move_reaches_the_stream(db: None, su: asyncpg.Connection) -> None:
    """The trigger reads the lead's own owner, because a lead has no conversation."""
    lead_id = await _a_lead(su, owner=USER_A)
    await su.execute("listen rt")
    await su.execute("update leads set score = 80 where id = $1", lead_id)
    payload = await _next_rt(su)
    assert payload["type"] == "lead.updated"
    assert payload["owner_id"] == str(USER_A)
```

`_a_lead` inserts a contact, a pipeline with one open stage and a lead on it; `_next_rt` waits for
one `rt` notification with a timeout — copy it from `tests/test_realtime.py` rather than writing a
second one.

- [ ] **Step 4: Run the tests**

```bash
cd apps/api && uv run pytest tests/test_crm_schema.py tests/test_realtime.py tests/test_sales_schema.py -q
```

Expected: all pass. `test_realtime.py` is in the list because Step 1 rewrote the function it covers.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0009_sales_crm.sql apps/api/tests/test_crm_schema.py
git commit -m "feat(db): pipelines, stages and tasks, and leads that sit on them"
```

---

## Task 2: The two writes that must not half-happen

**Files:**
- Modify: `supabase/migrations/0009_sales_crm.sql` (append — it has not shipped)
- Create: `apps/api/tests/test_contact_moves.py`

Reassigning a customer touches the contact, their open conversations, their open leads and their
open tasks. Merging touches identities, conversations, leads, tasks and activities, and deletes a
row. Half of either is worse than none, and both must hold `conversations.owner_id =
contacts.owner_id`, which is the invariant the inbox's visibility policy depends on.

- [ ] **Step 1: Append the two single writers**

```sql
-- =============================================================================
-- SINGLE WRITERS (docs/sales/02-data-model.md § 4, 05-workflows.md § 9, § 10)
-- SECURITY DEFINER because they must move rows the caller cannot see: a
-- salesperson hands a customer to a colleague whose rows are invisible to them.
-- The route decides who may call; the function decides what moving means.
-- =============================================================================
create or replace function app.reassign_contact(
  p_contact_id uuid, p_new_owner uuid, p_actor uuid
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_tenant uuid;
  v_old_owner uuid;
  v_conversation record;
begin
  select tenant_id, owner_id into v_tenant, v_old_owner
    from contacts where id = p_contact_id for update;
  if v_tenant is null then
    raise exception 'no such contact' using errcode = 'no_data_found';
  end if;

  update contacts set owner_id = p_new_owner where id = p_contact_id;

  -- owner_id and assigned_to move together: a conversation owned by one person
  -- and answered by another is the state the inbox cannot explain.
  for v_conversation in
    select id from conversations
     where contact_id = p_contact_id and status = 'open'
  loop
    update conversations
       set owner_id = p_new_owner, assigned_to = p_new_owner
     where id = v_conversation.id;
    insert into messages (tenant_id, conversation_id, kind, type, direction, sender, origin, event)
      values (v_tenant, v_conversation.id, 'event', 'text', 'out', 'system', 'system',
              jsonb_build_object('type', 'reassigned', 'to', p_new_owner));
  end loop;

  update leads l set owner_id = p_new_owner
    from pipeline_stages s
   where s.id = l.stage_id and l.contact_id = p_contact_id and s.category = 'open';
  update tasks set assignee_id = p_new_owner
   where contact_id = p_contact_id and status = 'open';

  insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type, entity_id,
                         before, after)
    values (v_tenant, 'user', p_actor::text, 'contact.reassigned', 'contact', p_contact_id,
            jsonb_build_object('owner_id', v_old_owner),
            jsonb_build_object('owner_id', p_new_owner));
end $fn$;

create or replace function app.merge_contacts(
  p_keep_id uuid, p_merge_id uuid, p_actor uuid
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_tenant uuid;
  v_keep jsonb;
  v_merged jsonb;
begin
  if p_keep_id = p_merge_id then
    raise exception 'a customer cannot be merged into itself' using errcode = 'check_violation';
  end if;
  select tenant_id into v_tenant from contacts where id = p_keep_id for update;
  select to_jsonb(c) into v_merged from contacts c where c.id = p_merge_id for update;
  if v_tenant is null or v_merged is null then
    raise exception 'no such contact' using errcode = 'no_data_found';
  end if;
  if (v_merged->>'tenant_id')::uuid <> v_tenant then
    raise exception 'customers are in different workspaces' using errcode = 'check_violation';
  end if;
  select to_jsonb(c) into v_keep from contacts c where c.id = p_keep_id;

  -- An identity the kept customer already has is dropped, not moved: the unique
  -- (tenant_id, kind, value) is what makes identity resolution safe.
  delete from contact_identities i
   where i.contact_id = p_merge_id
     and exists (select 1 from contact_identities k
                  where k.contact_id = p_keep_id and k.kind = i.kind and k.value = i.value);
  update contact_identities set contact_id = p_keep_id, is_primary = false
   where contact_id = p_merge_id;

  update conversations set contact_id = p_keep_id where contact_id = p_merge_id;
  update leads set contact_id = p_keep_id where contact_id = p_merge_id;
  update tasks set contact_id = p_keep_id where contact_id = p_merge_id;
  update activities set contact_id = p_keep_id where contact_id = p_merge_id;

  -- What a person set wins over what the AI inferred, on either record; between
  -- two human values the kept customer's wins, because that is the one someone
  -- chose to keep.
  update contacts set profile = (
    select coalesce(jsonb_object_agg(key, value), '{}'::jsonb)
      from (
        select key, value from jsonb_each(coalesce(v_merged->'profile', '{}'::jsonb))
        union all
        select key, value from jsonb_each(coalesce(v_keep->'profile', '{}'::jsonb))
             where value->>'source' = 'ai'
        union all
        select key, value from jsonb_each(coalesce(v_keep->'profile', '{}'::jsonb))
             where value->>'source' = 'human'
      ) merged_fields
  ),
  profile_updated_at = now()
  where id = p_keep_id;

  delete from contacts where id = p_merge_id;

  insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type, entity_id,
                         before, after, meta)
    values (v_tenant, 'user', p_actor::text, 'contact.merged', 'contact', p_merge_id,
            v_merged, v_keep, jsonb_build_object('keep_id', p_keep_id));
end $fn$;

revoke all on function app.reassign_contact(uuid, uuid, uuid) from public;
revoke all on function app.merge_contacts(uuid, uuid, uuid) from public;
grant execute on function app.reassign_contact(uuid, uuid, uuid) to dealerai_app;
grant execute on function app.merge_contacts(uuid, uuid, uuid) to dealerai_app;
```

`jsonb_object_agg` keeps the **last** value for a duplicate key, which is why the union runs
merged → keep's AI → keep's human, in that order. The `audit_log` row is what a manual repair would
start from, and — because it carries `entity_id = p_merge_id` and `meta.keep_id` — it is also how the
old URL explains itself in Task 6.

- [ ] **Step 2: Write the tests**

Create `apps/api/tests/test_contact_moves.py`:

```python
"""Reassign and merge: five tables, one transaction, one invariant."""


async def test_reassigning_moves_the_work_and_says_so_in_the_thread(
    db: None, su: asyncpg.Connection
) -> None:
    contact, conversation, lead, task = await _a_customer_with_everything(su, owner=USER_A)

    async with tenant_session(TENANT_A) as conn:
        await conn.execute("select app.reassign_contact($1, $2, $3)", contact, USER_B, USER_A)

    assert await su.fetchval("select owner_id from contacts where id = $1", contact) == USER_B
    row = await su.fetchrow(
        "select owner_id, assigned_to from conversations where id = $1", conversation
    )
    assert (row["owner_id"], row["assigned_to"]) == (USER_B, USER_B)
    assert await su.fetchval("select owner_id from leads where id = $1", lead) == USER_B
    assert await su.fetchval("select assignee_id from tasks where id = $1", task) == USER_B
    event = await su.fetchrow(
        """select event from messages where conversation_id = $1 and kind = 'event'
           order by created_at desc limit 1""",
        conversation,
    )
    assert event["event"]["type"] == "reassigned"


async def test_a_closed_lead_stays_with_whoever_closed_it(
    db: None, su: asyncpg.Connection
) -> None:
    """Won and lost are history. Moving them would rewrite someone's month."""


async def test_merging_moves_everything_and_leaves_one_customer(
    db: None, su: asyncpg.Connection
) -> None:
    """Identities, conversations, leads, tasks and activities all point at the survivor."""


async def test_a_person_s_answer_survives_a_merge_over_the_ai_s(
    db: None, su: asyncpg.Connection
) -> None:
    """keep human > keep ai > merged, whichever record the value came from."""


async def test_a_shared_identity_is_dropped_rather_than_duplicated(
    db: None, su: asyncpg.Connection
) -> None:
    """Both records knowing the same phone number must not break the unique index."""


async def test_customers_in_two_workspaces_cannot_be_merged(
    db: None, su: asyncpg.Connection
) -> None:
    with pytest.raises(asyncpg.PostgresError):
        async with tenant_session(TENANT_A) as conn:
            await conn.execute("select app.merge_contacts($1, $2, $3)", keep, theirs, USER_A)


async def test_the_owner_of_a_conversation_is_always_the_owner_of_its_customer(
    db: None, su: asyncpg.Connection
) -> None:
    """The invariant the inbox's visibility policy is built on, after both writes."""
    ...
    mismatched = await su.fetchval(
        """select count(*) from conversations c join contacts k on k.id = c.contact_id
            where c.status = 'open' and c.owner_id is distinct from k.owner_id"""
    )
    assert mismatched == 0
```

`_a_customer_with_everything(su, *, owner)` is the local helper the first test uses: a contact, one
open conversation with a message, one open lead on an open stage, one closed lead on the won stage,
and one open task — returned as a tuple of ids. Fill each remaining body with the same shape as the
first: build the rows with `su`, call the function through `tenant_session`, assert on `su`. The
docstrings are the specification — write the assertions that make them true.

- [ ] **Step 3: Run them**

```bash
COMPOSE_PROJECT_NAME=dealeraios npm run db:reset
cd apps/api && uv run pytest tests/test_contact_moves.py -q
```

Expected: 7 passed.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/0009_sales_crm.sql apps/api/tests/test_contact_moves.py
git commit -m "feat(db): reassigning and merging a customer, in one transaction each"
```

---
## Task 3: What we know about a customer, and who said so

**Files:**
- Create: `apps/api/src/dealerai/sales/profile.py`
- Create: `apps/api/tests/test_customer_profile.py`

Every value in `contacts.profile` carries where it came from. A salesperson has to be able to see
that the AI guessed the budget, click through to the message it guessed from, and correct it — and
once they do, no AI run may quietly overwrite it. That rule is one function, here, so no write path
can implement it differently.

- [ ] **Step 1: Write the module**

```python
"""What we know about a customer, and who said so.

Every field is `{value, source, evidence_message_id, updated_at}`. `source` is
`human` or `ai`, and that one word decides the rest: a person's answer is never
overwritten by a later inference, because being corrected and then ignored is
how people stop correcting anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ..core.errors import Unusable

Source = Literal["human", "ai"]

#: The fields the panel shows, in the order it shows them
#: (docs/sales/08-screens.md § 5).
FIELDS: dict[str, str] = {
    "interest": "text",
    "budget": "money",
    "purchase_type": "local_or_export",
    "destination": "country",
    "timeline": "text",
    "payment": "payment",
    "trade_in": "bool",
    "objections": "list",
}

_PURCHASE_TYPES = frozenset({"local", "export"})
_PAYMENTS = frozenset({"cash", "finance"})


def _checked(key: str, value: Any) -> Any:
    """The value as it will be stored, or a 400 naming the field."""
    kind = FIELDS.get(key)
    if kind is None:
        raise Unusable(f"{key} is not something we record about a customer")
    if value is None:
        return None
    if kind == "money":
        if not isinstance(value, dict) or "amount_minor" not in value:
            raise Unusable(f"{key} must be an amount, like 15000000 fils")
        return {"amount_minor": int(value["amount_minor"]),
                "currency": str(value.get("currency") or "AED")[:3].upper()}
    if kind == "local_or_export" and value not in _PURCHASE_TYPES:
        raise Unusable("purchase_type is local or export")
    if kind == "payment" and value not in _PAYMENTS:
        raise Unusable("payment is cash or finance")
    if kind == "country":
        text = str(value).upper()
        if len(text) != 2:
            raise Unusable("destination is a two-letter country code")
        return text
    if kind == "bool":
        return bool(value)
    if kind == "list":
        return [str(item) for item in value][:20]
    return str(value)[:500]


def apply(
    profile: dict[str, Any],
    changes: dict[str, Any],
    *,
    source: Source,
    now: datetime,
    evidence_message_id: UUID | None = None,
) -> dict[str, Any]:
    """Return the profile with `changes` written in, honouring who set what.

    An AI run may fill a field nobody has answered, and may update its own
    earlier guess. It may never touch a field a person set. A person may set
    anything, including back to nothing.
    """
    updated = dict(profile)
    for key, raw in changes.items():
        value = _checked(key, raw)
        held = updated.get(key)
        if source == "ai" and isinstance(held, dict) and held.get("source") == "human":
            continue
        if value is None:
            updated.pop(key, None)
            continue
        updated[key] = {
            "value": value,
            "source": source,
            "evidence_message_id": str(evidence_message_id) if evidence_message_id else None,
            "updated_at": now.isoformat(),
        }
    return updated
```

`Unusable` is the existing 422 in `core/errors.py` — `unusable-input` in the catalogue, "the request
was well-formed and its content was not", which is exactly a budget of "a lot". 400
`invalid-request` is for a malformed body, and Pydantic already answers those.

- [ ] **Step 2: Write the tests**

Create `apps/api/tests/test_customer_profile.py` — pure, no database:

```python
def test_the_ai_may_fill_a_blank_and_correct_itself() -> None:
    first = apply({}, {"budget": {"amount_minor": 15_000_000}}, source="ai", now=NOW)
    second = apply(first, {"budget": {"amount_minor": 14_000_000}}, source="ai", now=NOW)
    assert second["budget"]["value"]["amount_minor"] == 14_000_000
    assert second["budget"]["source"] == "ai"


def test_what_a_person_set_is_not_overwritten_by_a_later_guess() -> None:
    mine = apply({}, {"timeline": "This week"}, source="human", now=NOW)
    later = apply(mine, {"timeline": "Next month"}, source="ai", now=NOW)
    assert later["timeline"]["value"] == "This week"
    assert later["timeline"]["source"] == "human"


def test_editing_an_ai_value_makes_it_a_person_s() -> None:
    guessed = apply({}, {"interest": "Hilux"}, source="ai", now=NOW,
                    evidence_message_id=MESSAGE_ID)
    corrected = apply(guessed, {"interest": "Land Cruiser"}, source="human", now=NOW)
    assert corrected["interest"]["source"] == "human"
    assert corrected["interest"]["evidence_message_id"] is None


def test_a_person_can_clear_a_field() -> None:
    assert apply({"trade_in": {"value": True, "source": "ai"}}, {"trade_in": None},
                 source="human", now=NOW) == {}


def test_a_field_we_do_not_record_is_a_400_that_names_it() -> None:
    with pytest.raises(Unusable, match="shoe_size"):
        apply({}, {"shoe_size": 44}, source="human", now=NOW)


@pytest.mark.parametrize(
    "key,value",
    [("purchase_type", "maybe"), ("payment", "crypto"), ("destination", "Algeria"),
     ("budget", "a lot")],
)
def test_a_value_that_is_not_one_of_the_allowed_ones_is_refused(key: str, value: object) -> None:
    with pytest.raises(Unusable):
        apply({}, {key: value}, source="human", now=NOW)
```

- [ ] **Step 3: Run them**

```bash
cd apps/api && uv run pytest tests/test_customer_profile.py -q
```

Expected: 9 passed (the parametrised case counts four).

- [ ] **Step 4: Commit**

```bash
git add apps/api/src/dealerai/sales/profile.py apps/api/tests/test_customer_profile.py
git commit -m "feat(sales): the customer profile, and who set each value"
```

---

## Task 4: Why this lead is hot

**Files:**
- Create: `apps/api/src/dealerai/sales/scoring.py`
- Create: `apps/api/tests/test_lead_scoring.py`

The score is worthless unless the salesperson can see what it is made of, so the function returns
the reasons it used, each with the message that proves it. S4 adds the AI signals; the arithmetic,
the bands and the two signals code can see for itself are here.

- [ ] **Step 1: Write the module**

```python
"""Signals in, score out — and the reasons, which are the point.

A number nobody can argue with is a number nobody trusts. Every signal that
moved the score comes back with its points and, where the AI found it, the
message it found it in (docs/sales/04-ai-copilot.md § 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any

#: Signal → points. Per-tenant overrides live in sales_settings; there is no UI
#: for them in Phase 1, and an unknown signal is worth nothing rather than an
#: error, so a row written by a newer version cannot break an older reader.
DEFAULT_WEIGHTS: dict[str, int] = {
    "asked_price": 10,
    "asked_availability": 10,
    "asked_export_or_documents": 10,
    "gave_budget_or_timeline_30d": 10,
    "requested_visit_or_test_drive": 15,
    "negotiating_specific_car": 15,
    "shared_id_or_asked_payment_details": 25,
    "responsive": 5,
    "silent": -10,
}

LABELS: dict[str, str] = {
    "asked_price": "Asked the price",
    "asked_availability": "Asked whether it is available",
    "asked_export_or_documents": "Asked about export or documents",
    "gave_budget_or_timeline_30d": "Gave a budget or a date within a month",
    "requested_visit_or_test_drive": "Asked to visit or test drive",
    "negotiating_specific_car": "Negotiating one car",
    "shared_id_or_asked_payment_details": "Sent an ID or asked how to pay",
    "responsive": "Replies quickly",
    "silent": "Has gone quiet",
}

HOT, WARM = 70, 40


@dataclass(frozen=True, slots=True)
class Signal:
    name: str
    #: The message that proves it, when the AI found it in one.
    evidence_message_id: str | None = None
    #: How many times it counts. `silent` counts once per full week.
    times: int = 1


def band(score: int) -> str:
    if score >= HOT:
        return "hot"
    return "warm" if score >= WARM else "cold"


def score(
    signals: list[Signal], weights: dict[str, int] | None = None
) -> tuple[int, str, list[dict[str, Any]]]:
    """Returns `(score, band, reasons)`. The same signals always give the same score."""
    table = {**DEFAULT_WEIGHTS, **(weights or {})}
    reasons: list[dict[str, Any]] = []
    total = 0
    for signal in signals:
        points = table.get(signal.name)
        if points is None:
            continue  # a signal this version does not know is worth nothing
        points *= signal.times
        total += points
        reasons.append(
            {
                "signal": signal.name,
                "label": LABELS.get(signal.name, signal.name.replace("_", " ").capitalize()),
                "points": points,
                "evidence_message_id": signal.evidence_message_id,
            }
        )
    clamped = max(0, min(100, total))
    return clamped, band(clamped), reasons


def observed_signals(
    inbound_at: list[datetime], reply_latencies: list[timedelta], now: datetime
) -> list[Signal]:
    """The two signals code can see without the AI: pace, and silence."""
    found: list[Signal] = []
    if len(reply_latencies) >= 3 and median(reply_latencies) < timedelta(hours=1):
        found.append(Signal("responsive"))
    if inbound_at:
        weeks = (now - max(inbound_at)) // timedelta(weeks=1)
        if weeks >= 1:
            found.append(Signal("silent", times=int(weeks)))
    return found
```

- [ ] **Step 2: Let a tenant keep its own weights**

`SalesSettings` (in `sales/settings.py`) gains one field, so the route in Task 8 has somewhere to read
them from:

```python
    #: Signal → points, overriding sales/scoring.py's defaults. No UI in Phase 1
    #: (docs/sales/04-ai-copilot.md § 5); a dealership that wants different
    #: arithmetic gets it by hand, and the reasons on screen stay honest either way.
    scoring_weights: dict[str, int] = Field(default_factory=dict)
```

Add one case to `tests/test_sales_hours.py`, where `SalesSettings` is already covered: an unknown key in `scoring_weights` loads without
error, because `extra="ignore"` and the scorer skipping unknown signals have to agree.

- [ ] **Step 3: Write the tests**

Create `apps/api/tests/test_lead_scoring.py` — pure:

```python
def test_a_customer_who_sent_a_passport_is_hot() -> None:
    total, level, reasons = score(
        [Signal("asked_price", "m1"), Signal("requested_visit_or_test_drive", "m2"),
         Signal("shared_id_or_asked_payment_details", "m3"), Signal("responsive")]
    )
    assert (total, level) == (55, "warm")
    assert [r["signal"] for r in reasons][-1] == "responsive"
    assert reasons[0]["evidence_message_id"] == "m1"


@pytest.mark.parametrize("total,expected", [(100, "hot"), (70, "hot"), (69, "warm"),
                                            (40, "warm"), (39, "cold"), (0, "cold")])
def test_the_bands_are_where_the_spec_puts_them(total: int, expected: str) -> None:
    assert band(total) == expected


def test_the_score_cannot_leave_nought_to_a_hundred() -> None:
    assert score([Signal("silent", times=9)])[0] == 0
    assert score([Signal("shared_id_or_asked_payment_details")] * 9)[0] == 100


def test_a_signal_this_version_does_not_know_is_worth_nothing() -> None:
    """An older API reading a row a newer one wrote must not raise."""
    total, _, reasons = score([Signal("asked_price"), Signal("read_their_mind")])
    assert total == 10 and len(reasons) == 1


def test_a_tenant_can_weigh_a_signal_differently() -> None:
    assert score([Signal("asked_price")], {"asked_price": 30})[0] == 30


def test_silence_costs_a_week_at_a_time() -> None:
    signals = observed_signals([NOW - timedelta(days=22)], [], now=NOW)
    assert signals == [Signal("silent", times=3)]


def test_a_customer_who_answers_within_the_hour_is_responsive() -> None:
    quick = [timedelta(minutes=5), timedelta(minutes=40), timedelta(hours=3)]
    assert Signal("responsive") in observed_signals([NOW], quick, now=NOW)


def test_two_quick_replies_are_not_a_pattern() -> None:
    assert observed_signals([NOW], [timedelta(minutes=1), timedelta(minutes=2)], now=NOW) == []
```

Check the first test's arithmetic before you run it: 10 + 15 + 25 + 5 = 55, which is `warm`. If you
change a weight, change the number here — do not make the test compute what the module computes.

- [ ] **Step 4: Run them**

```bash
cd apps/api && uv run pytest tests/test_lead_scoring.py tests/test_sales_hours.py -q
```

Expected: 13 passed in the scoring file, and `test_sales_hours.py` still green.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/sales/scoring.py apps/api/src/dealerai/sales/settings.py \
        apps/api/tests/test_lead_scoring.py apps/api/tests/test_sales_hours.py
git commit -m "feat(sales): the lead score, and the reasons behind it"
```

---

## Task 5: The customer, over HTTP

**Files:**
- Create: `apps/api/src/dealerai/db/queries/crm.py`
- Create: `apps/api/src/dealerai/routes/customers.py`
- Modify: `apps/api/src/dealerai/main.py` (register the router)
- Create: `apps/api/tests/test_customers_api.py`

`GET /v1/customers`, `GET /v1/customers/{id}`, `GET /v1/customers/{id}/timeline`, `PATCH
/v1/customers/{id}` ([06](../06-api-contract.md) §4). Visibility is the policy's job; this task is
the shape of the answer.

- [ ] **Step 1: Write the queries**

`db/queries/crm.py` holds the SQL, the way `db/queries/inbox.py` does. Start with:

```python
#: One customer row for the list. `band` comes from the best open lead, because
#: that is the question the list answers: who is worth calling today.
CUSTOMER_SELECT = """
select c.id, c.full_name, c.locale as language, c.country, c.tags, c.owner_id,
       c.team_id, c.consent, c.last_seen_at, c.profile, c.profile_updated_at,
       p.full_name as owner_name,
       (select value from contact_identities i
         where i.contact_id = c.id and i.kind = 'phone'
         order by i.is_primary desc limit 1) as phone,
       (select value from contact_identities i
         where i.contact_id = c.id and i.kind = 'whatsapp_user_id'
         order by i.is_primary desc limit 1) as whatsapp_user_id,
       (select l.intent_band from leads l
          join pipeline_stages s on s.id = l.stage_id
         where l.contact_id = c.id and s.category = 'open'
         order by l.score desc nulls last limit 1) as band
  from contacts c
  left join profiles p on p.id = c.owner_id
"""

#: Newest first, keyed on (last_seen_at, id) so a cursor cannot skip a row when
#: two customers share a timestamp — the rule from the inbox's cursor.
LIST_SQL = f"""
{CUSTOMER_SELECT}
 where ($1::text is null or c.full_name ilike '%%' || $1 || '%%'
        or exists (select 1 from contact_identities i
                    where i.contact_id = c.id and i.value ilike '%%' || $1 || '%%'))
   and ($2::uuid is null or c.owner_id = $2)
   and ($3::text is null or c.country = $3)
   and ($4::text is null or $4 = any (c.tags))
   and ($5::timestamptz is null
        or (c.last_seen_at, c.id) < ($5::timestamptz, $6::uuid))
 order by c.last_seen_at desc nulls last, c.id desc
 limit $7
"""
```

The `band` filter is applied in Python over the returned page — it is one of five filters and the
only one that needs a join per row. Say so in a comment: `# ponytail: filtered after the page for
now; if band becomes the common filter it belongs in the where clause.`

The timeline is a union of what happened, newest first:

```python
TIMELINE_SQL = """
select 'message' as kind, m.id::text as id, m.created_at as at,
       jsonb_build_object('conversation_id', m.conversation_id, 'direction', m.direction,
                          'kind', m.kind, 'type', m.type, 'origin', m.origin,
                          'body', m.body, 'transcript', m.transcript, 'event', m.event) as data
  from messages m join conversations c on c.id = m.conversation_id
 where c.contact_id = $1
union all
select 'activity', a.id::text, a.occurs_at,
       jsonb_build_object('kind', a.kind, 'body', a.body, 'meta', a.meta)
  from activities a where a.contact_id = $1 or a.lead_id in (select id from leads where contact_id = $1)
 order by at desc, id desc
 limit $3 offset $2
"""
```

Offset paging, not a keyset, and a comment saying why: the timeline merges two tables with different
id types, and a customer with more than a few hundred rows is a customer nobody scrolls. `# ponytail:
offset paging — swap for a keyset if a timeline ever needs page 20.`

- [ ] **Step 2: Write the routes**

`routes/customers.py`, following `routes/inbox.py`'s shape: a Pydantic DTO per response, `Ctx` for
the tenant, `tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope)` for every read,
and `NotFound` — never `Forbidden` — when a row is outside the caller's visibility.

```python
class CustomerSummary(BaseModel):
    id: UUID
    name: str | None
    phone: str | None
    country: str | None
    language: str | None
    tags: list[str]
    owner: Person | None
    band: Literal["hot", "warm", "cold"] | None
    opted_out: bool
    last_seen_at: datetime | None


class CustomerDetail(CustomerSummary):
    identities: list[Identity]
    profile: dict[str, Any]
    profile_updated_at: datetime | None
    open_leads: list[LeadSummary]
    open_tasks: int


class CustomerPatch(BaseModel):
    name: str | None = None
    tags: list[str] | None = None
    profile: dict[str, Any] | None = None


@router.patch("/{customer_id}", response_model=CustomerDetail)
async def edit_customer(ctx: Ctx, customer_id: UUID, body: CustomerPatch) -> dict[str, Any]:
    """Anything a person types here is a person's answer, stamped `human`."""
    async with tenant_session(...) as conn, conn.transaction():
        current = await _customer_or_404(conn, customer_id)
        profile = profile_module.apply(
            dict(current["profile"] or {}), body.profile or {}, source="human",
            now=datetime.now(UTC),
        )
        ...
```

- [ ] **Step 3: Write the tests**

Create `apps/api/tests/test_customers_api.py`. Every endpoint needs a permission test and a
visibility test — the definition of done in [09](../09-implementation-plan.md):

```python
def test_the_list_answers_who_is_worth_calling(client: TestClient) -> None: ...
def test_search_finds_a_customer_by_a_number_they_wrote_from(client: TestClient) -> None: ...
def test_the_cursor_walks_the_list_without_skipping_a_shared_timestamp(client) -> None: ...
def test_a_salesperson_sees_their_own_customers_and_the_pool(client: TestClient) -> None: ...
def test_another_tenant_s_customer_is_404_not_403(client: TestClient) -> None: ...
def test_the_timeline_merges_both_conversations_newest_first(client: TestClient) -> None: ...
def test_editing_the_budget_marks_it_as_a_person_s(client: TestClient) -> None: ...
def test_editing_a_customer_i_cannot_see_is_404(client: TestClient) -> None: ...
```

- [ ] **Step 4: Run the suite and the contract**

```bash
cd apps/api && uv run pytest tests/test_customers_api.py -q
cd ../.. && npm run check:openapi
```

Expected: tests pass; `check:openapi` fails the first time — commit the regenerated
`apps/web/lib/api/openapi.json` and `schema.ts` with this task, which is what keeps the browser's
types honest.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/db/queries/crm.py apps/api/src/dealerai/routes/customers.py \
        apps/api/src/dealerai/main.py apps/api/tests/test_customers_api.py apps/web/lib/api
git commit -m "feat(api): the customers list, the record and its timeline"
```

---

## Task 6: Handing a customer over

**Files:**
- Modify: `apps/api/src/dealerai/routes/customers.py`
- Create: `apps/api/src/dealerai/events/handlers/crm.py`
- Modify: `apps/api/src/dealerai/events/handlers/parked.py`
- Modify: `apps/api/tests/test_customers_api.py`

- [ ] **Step 1: The two routes**

```python
@router.post("/{customer_id}/reassign", response_model=CustomerDetail)
async def reassign_customer(
    customer_id: UUID,
    body: ReassignIn,
    ctx: Annotated[TenantContext, Depends(require_permission("contacts.reassign"))],
) -> dict[str, Any]:
    async with tenant_session(...) as conn, conn.transaction():
        await _customer_or_404(conn, customer_id)  # 404 before the permission bites
        await _member_or_404(conn, body.owner_id)
        await conn.execute(
            "select app.reassign_contact($1, $2, $3)", customer_id, body.owner_id, ctx.user.id
        )
        await emit(conn, "contact.reassigned",
                   {"contact_id": str(customer_id), "owner_id": str(body.owner_id),
                    "actor_id": str(ctx.user.id)},
                   tenant_id=ctx.tenant_id, priority=8)
        return await _detail(conn, customer_id)


@router.post("/merge", response_model=CustomerDetail)
async def merge_customers(
    body: MergeIn,
    ctx: Annotated[TenantContext, Depends(require_permission("contacts.merge"))],
) -> dict[str, Any]:
    """Not undoable. The audit snapshot is what a repair would start from."""
```

A merged customer's old URL has to explain itself ([08](../08-screens.md) §6), so `_customer_or_404`
looks for the tombstone the merge left in `audit_log` before giving up:

```python
MERGED_INTO = """
select meta->>'keep_id' from audit_log
 where tenant_id = $1 and action = 'contact.merged'
   and entity_type = 'contact' and entity_id = $2
 order by created_at desc limit 1
"""
# Served by the existing (tenant_id, entity_type, entity_id) index — no new table
# for a redirect that is read once, by a person following an old link.
```

When it finds one, raise `AlreadyMerged` (409, `already-merged` in the catalogue) with
`{"keep_id": …}` in the problem detail. Extend `core/errors.py` if the class is not there yet.

- [ ] **Step 2: Tell the new owner**

Create `events/handlers/crm.py`, and delete `contact.reassigned` from `parked.py` in the same
commit — `test_every_emitted_event_has_a_handler` is what keeps those two in step:

```python
@handler("contact.reassigned")
async def on_contact_reassigned(event: Event) -> None:
    """The person who just inherited a customer should not find out by accident."""
    ...
    await _notify(conn, tenant_id, owner_id, kind="contact_assigned",
                  title=f"{contact_name} is yours now",
                  body=f"Handed over by {actor_name}",
                  entity={"type": "contact", "id": str(contact_id)},
                  dedupe_key=f"contact-assigned:{contact_id}:{owner_id}")
```

Reuse `_notify` from `events/handlers/inbox.py` rather than writing a second one; if that means
moving it, move it to `events/handlers/notify.py` and import it from both.

- [ ] **Step 3: Tests**

```python
def test_a_salesperson_cannot_hand_a_customer_to_someone_else(client: TestClient) -> None:
    """403 for the permission, but only after 404 for visibility."""

def test_reassigning_tells_the_new_owner(client: TestClient) -> None: ...
def test_a_merged_customer_s_old_link_says_where_they_went(client: TestClient) -> None:
    response = client.get(f"/v1/customers/{merged}", headers=_auth(MANAGER))
    assert response.status_code == 409
    assert response.json()["type"].endswith("already-merged")
    assert response.json()["keep_id"] == str(kept)

def test_merging_needs_the_permission(client: TestClient) -> None: ...
def test_merging_someone_else_s_customer_is_404(client: TestClient) -> None: ...
```

- [ ] **Step 4: Run and commit**

```bash
cd apps/api && uv run pytest tests/test_customers_api.py tests/test_import_contracts.py -q
cd ../.. && npm run check:openapi
git add apps/api apps/web/lib/api
git commit -m "feat(api): reassign and merge a customer"
```

---
## Task 7: The board's shape

**Files:**
- Create: `apps/api/src/dealerai/routes/pipelines.py`
- Modify: `apps/api/src/dealerai/routes/tenants.py`, `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_pipelines_api.py`

`GET /v1/pipelines` and `PUT /v1/pipelines/{id}/stages` ([06](../06-api-contract.md) §5). The PUT
replaces the stage list in one call, because reordering a board one PATCH at a time is how a board
ends up with two stages in position 3.

- [ ] **Step 1: The routes**

```python
class StageIn(BaseModel):
    #: Present for a stage that already exists; absent creates one.
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=60)
    category: Literal["open", "won", "lost"]


class StagesIn(BaseModel):
    stages: list[StageIn] = Field(min_length=2)

    @model_validator(mode="after")
    def _one_won_and_at_least_one_lost(self) -> "StagesIn":
        categories = [stage.category for stage in self.stages]
        if categories.count("won") != 1:
            raise ValueError("a pipeline has exactly one won stage")
        if "lost" not in categories:
            raise ValueError("a pipeline needs somewhere to put a lost lead")
        return self


@router.put("/{pipeline_id}/stages", response_model=Pipeline)
async def replace_stages(
    pipeline_id: UUID,
    body: StagesIn,
    ctx: Annotated[TenantContext, Depends(require_permission("pipeline.edit_stages"))],
) -> dict[str, Any]:
    """Position is the order they arrive in. A stage that still holds leads
    cannot be deleted — the error says how many, because "409" on its own tells
    a manager nothing about what to do next."""
    async with tenant_session(...) as conn, conn.transaction():
        existing = {row["id"]: row for row in await conn.fetch(
            "select id, name from pipeline_stages where pipeline_id = $1 for update", pipeline_id)}
        keeping = {stage.id for stage in body.stages if stage.id}
        for stage_id in set(existing) - keeping:
            held = await conn.fetchval(
                "select count(*) from leads where stage_id = $1", stage_id)
            if held:
                raise StageInUse(
                    f"{existing[stage_id]['name']} still holds {held} "
                    f"{'lead' if held == 1 else 'leads'}. Move them first."
                )
            await conn.execute("delete from pipeline_stages where id = $1", stage_id)
        for position, stage in enumerate(body.stages):
            ...  # update by id, or insert
```

`StageInUse` is a 409 with slug `stage-in-use` — already in the error catalogue
([06](../06-api-contract.md) §11), so add the class to `core/errors.py` next to `ChannelUnavailable`.

- [ ] **Step 2: A new workspace gets a board**

The migration backfilled existing tenants; new ones are created by `routes/tenants.py`, which must
now create the default pipeline in the same transaction. A workspace whose first lead cannot be
created because there is no pipeline is a workspace that looks broken on day one.

```python
DEFAULT_STAGES = (("New", "open"), ("Contacted", "open"), ("Qualified", "open"),
                  ("Appointment", "open"), ("Negotiation", "open"),
                  ("Won", "won"), ("Lost", "lost"))
```

- [ ] **Step 3: Tests**

```python
def test_a_new_workspace_can_create_a_lead_the_minute_it_exists(client: TestClient) -> None: ...
def test_stages_come_back_in_board_order(client: TestClient) -> None: ...
def test_renaming_and_reordering_keeps_the_leads_where_they_are(client: TestClient) -> None: ...
def test_deleting_a_stage_that_still_holds_leads_says_how_many(client: TestClient) -> None:
    assert response.status_code == 409
    assert "2 leads" in response.json()["detail"]
def test_a_pipeline_cannot_end_up_with_two_won_stages(client: TestClient) -> None: ...
def test_a_salesperson_cannot_reshape_the_board(client: TestClient) -> None: ...
def test_another_tenant_s_pipeline_is_404(client: TestClient) -> None: ...
```

- [ ] **Step 4: Run and commit**

```bash
cd apps/api && uv run pytest tests/test_pipelines_api.py tests/test_tenants.py -q
cd ../.. && npm run check:openapi
git add apps/api apps/web/lib/api
git commit -m "feat(api): pipelines and the stages a manager can reshape"
```

---

## Task 8: The lead itself

**Files:**
- Create: `apps/api/src/dealerai/routes/leads.py`
- Modify: `apps/api/src/dealerai/db/queries/crm.py`, `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_leads_api.py`

`GET /v1/leads`, `POST /v1/leads`, `GET /v1/leads/{id}`, `PATCH /v1/leads/{id}`
([06](../06-api-contract.md) §5). A stage move is the write this slice exists for, so it does three
things in one transaction: the lead, its history, and a line in the conversation the customer is
having.

- [ ] **Step 1: The routes**

```python
class LeadPatch(BaseModel):
    stage_id: UUID | None = None
    owner_id: UUID | None = None
    vehicle_id: UUID | None = None
    budget: Money | None = None
    lost_reason: str | None = None


@router.patch("/{lead_id}", response_model=LeadDetail)
async def edit_lead(ctx: Ctx, lead_id: UUID, body: LeadPatch) -> dict[str, Any]:
    async with tenant_session(...) as conn, conn.transaction():
        lead = await _lead_or_404(conn, lead_id)
        if body.stage_id and body.stage_id != lead["stage_id"]:
            stage = await conn.fetchrow(
                "select id, name, category from pipeline_stages where id = $1 and pipeline_id = $2",
                body.stage_id, lead["pipeline_id"],
            )
            if stage is None:
                raise Unusable("that stage belongs to a different pipeline")
            if stage["category"] in ("won", "lost") and not ctx.may("leads.mark_won_lost"):
                raise Forbidden("marking a lead won or lost needs leads.mark_won_lost")
            if stage["category"] == "lost" and not (body.lost_reason or "").strip():
                raise Unusable("a lost lead needs a reason — it is the only way to learn anything")
            await conn.execute(
                """update leads set stage_id = $2, stage_entered_at = now(),
                          lost_reason = case when $3 then $4 else null end
                    where id = $1""",
                lead_id, stage["id"], stage["category"] == "lost", body.lost_reason,
            )
            # Stage history is activities, which already exists and is already
            # visible to whoever can see the lead.
            await conn.execute(
                """insert into activities (tenant_id, lead_id, contact_id, kind, body, meta,
                                           actor_type, actor_id)
                   values ($1, $2, $3, 'stage_change', $4, $5, 'user', $6)""",
                ctx.tenant_id, lead_id, lead["contact_id"],
                f"{lead['stage_name']} → {stage['name']}",
                {"from": str(lead["stage_id"]), "to": str(stage["id"])}, str(ctx.user.id),
            )
            if lead["conversation_id"]:
                await event_line(conn, ctx.tenant_id, lead["conversation_id"], "stage_change",
                                 f"Lead moved to {stage['name']}")
```

`event_line` would be the third copy of the same six-line insert — `routes/inbox.py` writes one
inline when a conversation is closed, and `events/handlers/inbox.py` has a private `_event_line`. Move
it to `apps/api/src/dealerai/sales/timeline.py` first, point both existing callers at it, and check
`tests/test_inbox_thread.py` still passes before adding the third caller. A grey line in a thread is
the same thing whoever writes it.

The lead's stored `score_signals` are dicts, and `scoring.score` takes `Signal` objects — convert at
the edge, ignoring keys the dataclass does not have, so a row written by a later version still
renders:

```python
signals = [
    Signal(name=str(raw["signal"]), evidence_message_id=raw.get("evidence_message_id"),
           times=int(raw.get("times", 1)))
    for raw in (lead["score_signals"] or [])
    if raw.get("signal")
]
total, level, reasons = score(signals, weights=settings.scoring_weights)
```

`POST /v1/leads` takes `{contact_id, pipeline_id?, vehicle_id?, budget?}` and fills in the rest: the
default pipeline when none is named, its first `open` stage by position, `owner_id` from the
customer, `team_id` from the customer, and `source` `whatsapp` when the contact has a WhatsApp
identity, else `manual`. `GET /v1/leads/{id}` adds `score_reasons` (straight from `score_signals`
through `scoring.score`, so the points shown are the points counted), the stage history from
`activities`, the open tasks and the conversation link.

- [ ] **Step 2: Tests**

```python
def test_a_new_lead_starts_on_the_first_open_stage_of_the_default_pipeline(client) -> None: ...
def test_a_lead_belongs_to_whoever_owns_the_customer(client: TestClient) -> None: ...
def test_moving_a_lead_writes_its_history_and_a_line_in_the_conversation(client) -> None: ...
def test_a_lost_lead_needs_a_reason(client: TestClient) -> None: ...
def test_a_stage_from_another_pipeline_is_refused(client: TestClient) -> None: ...
def test_the_reasons_add_up_to_the_score_that_is_shown(client: TestClient) -> None:
    detail = client.get(f"/v1/leads/{lead}", headers=_auth(SALES_1)).json()
    assert sum(r["points"] for r in detail["score_reasons"]) == detail["score"]
def test_a_salesperson_sees_their_own_leads_and_the_pool(client: TestClient) -> None: ...
def test_another_tenant_s_lead_is_404(client: TestClient) -> None: ...
```

The sixth one is the honest version of "the UI explains the score": if the reasons and the number
can disagree, the explanation is decoration.

- [ ] **Step 3: Run and commit**

```bash
cd apps/api && uv run pytest tests/test_leads_api.py -q
cd ../.. && npm run check:openapi
git add apps/api apps/web/lib/api
git commit -m "feat(api): leads, their stages and their history"
```

---

## Task 9: What somebody has to do next

**Files:**
- Create: `apps/api/src/dealerai/routes/tasks.py`
- Modify: `apps/api/src/dealerai/db/queries/crm.py`, `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_tasks_api.py`

`GET /v1/tasks?assignee&bucket`, `POST`, `PATCH` ([06](../06-api-contract.md) §6). The buckets are
overdue, today, upcoming and done, and "today" means today in the dealership's timezone, not the
server's or the browser's.

- [ ] **Step 1: The routes**

```python
BUCKETS = ("overdue", "today", "upcoming", "done")

def _window(bucket: str, timezone: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    """Midnight to midnight where the dealership is. A task due at 21:00 in
    Dubai is due today for the person in Dubai, whatever the server thinks."""
    local = now.astimezone(ZoneInfo(timezone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "overdue":
        return None, now
    if bucket == "today":
        return now, start + timedelta(days=1)
    if bucket == "upcoming":
        return start + timedelta(days=1), None
    return None, None  # done ignores the window
```

`assignee=team` needs a manager scope (`ctx.scope != "own"`); a salesperson asking for it gets their
own tasks rather than an error, because the switch is hidden for them anyway and 403 on a list is
noise. `PATCH` covers completing (`status: done` stamps `completed_at`), snoozing (`due_at`) and
renaming. Completing twice is idempotent.

- [ ] **Step 2: Tests**

```python
def test_a_task_due_this_evening_in_dubai_is_due_today(client: TestClient) -> None:
    """The one that fails if anybody uses the server's clock."""
def test_yesterday_s_unfinished_task_is_overdue(client: TestClient) -> None: ...
def test_completing_a_task_stamps_when(client: TestClient) -> None: ...
def test_completing_it_again_changes_nothing(client: TestClient) -> None: ...
def test_snoozing_moves_it_between_buckets(client: TestClient) -> None: ...
def test_a_salesperson_sees_only_their_own(client: TestClient) -> None: ...
def test_a_manager_can_ask_for_the_team_s(client: TestClient) -> None: ...
def test_a_task_about_another_tenant_s_customer_is_refused(client: TestClient) -> None: ...
```

- [ ] **Step 3: Extend the visibility matrix**

`tasks` is the first owner-bearing table added since the matrix was written, and
[02](../02-data-model.md) §4 says the matrix runs twice: directly under `tenant_session`, and through
every list endpoint. In `apps/api/tests/test_visibility.py`, give each of the six viewers a task and
a lead, and add `/v1/tasks`, `/v1/leads` and `/v1/customers` to the endpoint pass. The row that
matters is S1 looking at S2's conversation they are covering: they see the conversation, and they
still do not see S2's tasks.

- [ ] **Step 4: Run and commit**

```bash
cd apps/api && uv run pytest tests/test_tasks_api.py tests/test_visibility.py -q
cd ../.. && npm run check:openapi
git add apps/api apps/web/lib/api
git commit -m "feat(api): tasks, in the buckets a day is actually lived in"
```

---

## Task 10: My day

**Files:**
- Create: `apps/api/src/dealerai/routes/dashboard.py`
- Modify: `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_my_day.py`

`GET /v1/dashboard/me` ([06](../06-api-contract.md) §7, [08](../08-screens.md) §10). One request,
because it is one screen refreshed together.

- [ ] **Step 1: The route**

```python
class MyDay(BaseModel):
    replied_today: int
    median_first_response_seconds: int | None
    accepting_chats: bool
    waiting_on_you: list[ConversationSummary]
    due_today: list[TaskOut]
    hot_leads: list[LeadSummary]
```

Every number is the caller's own and every list is ordered by what to do first: conversations by
`waiting_since` ascending, tasks by `due_at`, leads by `score` descending. `median_first_response_seconds`
is over conversations whose `first_response_at` landed today — `percentile_cont(0.5)`, and null when
there are none, because a zero would read as instant.

- [ ] **Step 2: Tests**

```python
def test_my_day_counts_only_my_replies(client: TestClient) -> None: ...
def test_the_median_is_null_before_the_first_reply_of_the_day(client: TestClient) -> None: ...
def test_waiting_on_you_is_oldest_first(client: TestClient) -> None: ...
def test_it_is_my_day_not_the_team_s(client: TestClient) -> None:
    """A manager's own page still shows their own work."""
```

- [ ] **Step 3: Run and commit**

```bash
cd apps/api && uv run pytest tests/test_my_day.py -q
cd ../.. && npm run check:openapi
git add apps/api apps/web/lib/api
git commit -m "feat(api): my day"
```

---

## Task 11: The browser's side of the contract

**Files:**
- Modify: `apps/web/lib/api/keys.ts`, `apps/web/lib/api/hooks.ts`, `apps/web/lib/live.tsx`
- Create: `apps/web/lib/filters.ts`, `apps/web/lib/filters.test.ts`
- Modify: `apps/web/messages/{en,ar}.ts`

No screen in this slice may call `fetch`. Everything goes through a hook, and every hook is typed by
the generated `schema.ts` — which is why `check:openapi` has been part of every task above.

- [ ] **Step 1: Keys and hooks**

```ts
customers: (tenantId: string, filters: string) => ["customers", tenantId, filters] as const,
customer: (tenantId: string, id: string) => ["customer", tenantId, id] as const,
timeline: (tenantId: string, id: string) => ["timeline", tenantId, id] as const,
pipelines: (tenantId: string) => ["pipelines", tenantId] as const,
leads: (tenantId: string, filters: string) => ["leads", tenantId, filters] as const,
lead: (tenantId: string, id: string) => ["lead", tenantId, id] as const,
tasks: (tenantId: string, filters: string) => ["tasks", tenantId, filters] as const,
myDay: (tenantId: string) => ["my-day", tenantId] as const,
```

Hooks: `useCustomers`, `useCustomer`, `useCustomerTimeline`, `useEditCustomer`, `useReassign`,
`useMergeCustomers`, `usePipelines`, `useReplaceStages`, `useLeads`, `useLead`, `useCreateLead`,
`useEditLead`, `useTasks`, `useCreateTask`, `useEditTask`, `useMyDay`. Two of them are optimistic,
and only two, because these are the moves a person makes repeatedly and watches:

- `useEditLead` on a stage move — the card must land in the new column before the round trip, with a
  rollback on error, exactly like `useSendMessage` in S2.
- `useEditTask` on completing — the row ticks immediately, and the toast offers Undo.

- [ ] **Step 2: What a lead or task event invalidates**

In `lib/live.tsx`, add to `invalidate()`:

```ts
if (event.type === "lead.updated") {
  queryClient.invalidateQueries({ queryKey: ["leads", tenantId] });
  queryClient.invalidateQueries({ queryKey: keys.lead(tenantId, event.id) });
  queryClient.invalidateQueries({ queryKey: keys.myDay(tenantId) });
}
if (event.type === "task.updated") {
  queryClient.invalidateQueries({ queryKey: ["tasks", tenantId] });
  queryClient.invalidateQueries({ queryKey: keys.myDay(tenantId) });
}
```

`LiveEvent` grows an `id` field. Keep it ids-only: the rule that a missed event costs a refetch and
never shows a wrong screen is what makes the whole live layer safe to ignore when it breaks.

- [ ] **Step 3: Filters that live in the URL**

`lib/filters.ts` — a shared link and a reload must show the same list ([08](../08-screens.md) §7):

```ts
/** Filters in the URL, so a list someone sends you is the list they saw. */
export function useFilters<T extends Record<string, string>>(defaults: T) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const values = { ...defaults } as T;
  for (const key of Object.keys(defaults)) {
    const found = params.get(key);
    if (found !== null) (values as Record<string, string>)[key] = found;
  }
  const set = (changes: Partial<T>) => {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (!value || value === defaults[key]) next.delete(key);
      else next.set(key, String(value));
    }
    router.replace(`${pathname}?${next}`, { scroll: false });
  };
  return [values, set] as const;
}
```

Test the pure part (`lib/filters.test.ts`): a default is absent from the URL, a change is present,
clearing removes it, and an unknown parameter someone else put there survives.

- [ ] **Step 4: Strings**

Add the `customers.*`, `profile.*`, `pipeline.*`, `lead.*`, `task.*` and `today.*` keys to
`messages/en.ts` and `messages/ar.ts` as you build each screen — `ar.ts` `satisfies` the English
keys, so a missing translation is a typecheck failure rather than a blank button in Dubai.

- [ ] **Step 5: Run and commit**

```bash
npm run check:web
git add apps/web
git commit -m "feat(web): the CRM's queries, live invalidation and URL filters"
```

---
## Task 12: The customer on screen

**Files:**
- Create: `apps/web/components/crm/CustomerPanel.tsx`, `ProfileField.tsx`, `ProfileField.test.tsx`,
  `Timeline.tsx`, `ReassignDialog.tsx`, `MergeDialog.tsx`, `CustomerRow.tsx`, `CustomerRow.test.tsx`
- Create: `apps/web/app/[tenant]/customers/[contactId]/page.tsx`
- Modify: `apps/web/app/[tenant]/customers/page.tsx`, `apps/web/components/inbox/Thread.tsx`

Three surfaces over the same record ([08](../08-screens.md) §5–§7): the panel beside the thread, the
full 360, and the list.

- [ ] **Step 1: The profile field**

The smallest piece and the one that carries the idea, so build it first:

```tsx
/**
 * One thing we know about a customer, and who said so.
 *
 * The marker is not decoration: a salesperson has to know at a glance whether
 * the budget is what the customer said or what a model inferred, and be one
 * click from the message it was inferred from. Editing it makes it theirs.
 */
export function ProfileField({ name, field, onSave, onEvidence }: {
  name: string;
  field: { value: unknown; source: "human" | "ai"; evidence_message_id: string | null } | null;
  onSave: (value: unknown) => void;
  onEvidence?: (messageId: string) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  ...
  return (
    <div className="flex items-baseline justify-between gap-2 py-1.5" data-source={field?.source}>
      <span className="text-muted text-xs">{t(`profile.${name}` as MessageKey)}</span>
      {editing ? <input … /> : (
        <button type="button" onClick={() => setEditing(true)} className="text-sm">
          {display ?? t("profile.unknown")}
          {field?.source === "ai" && (
            <span
              onClick={(event) => { event.stopPropagation();
                                    field.evidence_message_id && onEvidence?.(field.evidence_message_id); }}
              className="ms-1 rounded bg-blue-500/15 px-1 text-[10px] uppercase text-blue-700
                         dark:text-blue-300"
            >
              {t("profile.fromAi")}
            </span>
          )}
        </button>
      )}
    </div>
  );
}
```

Tests (`ProfileField.test.tsx`), the four that matter:

```tsx
it("marks a value the AI inferred, and a value a person set", …);
it("jumps to the message a value came from", …);            // onEvidence called with the id
it("saves on Enter and abandons on Escape", …);
it("shows an empty field as a question, not a blank", …);    // "Unknown" is clickable
```

- [ ] **Step 2: The panel, in the thread**

`CustomerPanel` takes a `contactId`, reads `useCustomer`, and renders: header (name, number, country,
owner, tags, an opted-out chip), the profile fields, the open lead or a Create lead button, the open
tasks with a complete tick, and a link to the 360. `Thread.tsx` gains a header button that toggles
it: a third column on `lg`, a sheet over the thread below it.

```tsx
// Thread.tsx
const [panelOpen, setPanelOpen] = useState(false);
…
<div className="flex min-h-0 flex-1">
  <div className="flex min-w-0 flex-1 flex-col">{/* messages + composer, as today */}</div>
  {panelOpen && (
    <aside className="border-border bg-surface fixed inset-y-0 end-0 z-30 w-80 overflow-y-auto
                      border-s lg:static lg:z-auto lg:w-72">
      <CustomerPanel contactId={row.contact.id} onClose={() => setPanelOpen(false)} />
    </aside>
  )}
</div>
```

The evidence link scrolls the thread to `#message-{id}` and flashes it — add `id={`message-${message.id}`}`
to `MessageBubble`'s `<li>` while you are there.

- [ ] **Step 3: The 360 and the list**

`customers/[contactId]/page.tsx`: header with every identity, owner, tags, the opted-out chip, and
tabs — Timeline, Leads, Tasks, Profile. Tab state in the URL (`?tab=`) through `useFilters`, so a
link sent to a colleague opens where the sender was.

Reassign dialog: pick a person, show their open conversation count and whether they are taking
chats, and **list what will move** — "3 open conversations, 1 open lead, 2 tasks" — before the
button. Merge dialog: search the other record, compare identities, owner, leads and last activity
side by side, and say plainly that it cannot be undone.

`customers/page.tsx`: a table on desktop, `CustomerRow` cards on a phone; filters (search, owner,
band, country, tag) through `useFilters`; an empty state that explains customers arrive by
themselves from WhatsApp.

- [ ] **Step 4: Check and commit**

```bash
npm run check:web
git add apps/web
git commit -m "feat(web): the customer panel, the 360 and the customers list"
```

---

## Task 13: The board

**Files:**
- Create: `apps/web/components/crm/BoardColumn.tsx`, `LeadCard.tsx`, `LeadCard.test.tsx`,
  `LeadDrawer.tsx`, `ScoreReasons.tsx`, `LostReasonDialog.tsx`
- Modify: `apps/web/app/[tenant]/pipeline/page.tsx`

- [ ] **Step 1: Moving a lead, twice over**

Dragging is how a board feels right; a menu is how it works for everyone else. Both call the same
mutation, and the menu is built first so the board is never keyboard-only in theory:

```tsx
// LeadCard.tsx — every card carries its own "Move to…" menu.
<select
  aria-label={t("pipeline.moveTo")}
  value={lead.stage.id}
  onChange={(event) => onMove(lead.id, event.target.value)}
  className="min-h-11 rounded-md border border-black/10 text-xs dark:border-white/15"
>
  {stages.map((stage) => <option key={stage.id} value={stage.id}>{stage.name}</option>)}
</select>
```

```tsx
// BoardColumn.tsx — native drag and drop, no library.
<li
  draggable
  onDragStart={(event) => event.dataTransfer.setData("text/plain", lead.id)}
  …
/>
<ol
  onDragOver={(event) => event.preventDefault()}
  onDrop={(event) => onMove(event.dataTransfer.getData("text/plain"), stage.id)}
/>
```

`// ponytail: HTML5 drag and drop — no touch support, which is why the menu exists and why the
phone layout is one column per screen.`

Moving into a `lost` stage opens `LostReasonDialog` first and sends the reason with the patch; the
API refuses a lost lead without one, so the dialog is the UI half of a rule that is enforced
anyway.

- [ ] **Step 2: The columns and the drawer**

Each column shows its stage name, the lead count and the total value of the leads in it (summed in
the browser from the page it already has). Won and Lost are collapsed drop zones at the end. On a
phone, `snap-x snap-mandatory` with `w-[85vw] snap-center` columns, so one column fills the screen
and the next peeks.

`LeadDrawer` opens from `?lead=<id>`: the car, stage, owner, band and score, then `ScoreReasons` —
one row per signal with its points and, where there is one, a link to the message that proves it —
then budget, source, created, the conversation link, the stage history and the tasks.

```tsx
// ScoreReasons.tsx — the points shown are the points counted, and they add up
// on screen, because a score a salesperson cannot check is a score they ignore.
<li className="flex items-baseline justify-between gap-2">
  <span>{reason.label}</span>
  <span className={reason.points < 0 ? "text-red-600" : "text-muted"}>
    {reason.points > 0 ? `+${reason.points}` : reason.points}
  </span>
</li>
```

`LeadCard.test.tsx`: it shows the band, the days in stage, the owner and the next action; a card
with no car says so rather than showing an empty line; the move menu lists every stage of the
lead's own pipeline.

- [ ] **Step 3: Check and commit**

```bash
npm run check:web
git add apps/web
git commit -m "feat(web): the pipeline board and the lead drawer"
```

---

## Task 14: Tasks, and the start of a day

**Files:**
- Create: `apps/web/components/crm/TaskRow.tsx`, `TaskRow.test.tsx`, `TaskComposer.tsx`
- Modify: `apps/web/app/[tenant]/tasks/page.tsx`, `apps/web/app/[tenant]/today/page.tsx`

- [ ] **Step 1: The tasks screen**

Tabs for Overdue (red), Today, Upcoming and Done, with a Mine/Team switch that only appears for a
manager. A row is a complete tick, the title, a kind icon, the customer link, the due time and — in
Team view — the assignee. Snooze offers an hour, tomorrow morning and next week, each a `due_at`
patch.

Completing is optimistic and offers Undo for five seconds:

```tsx
const complete = (task: Task) => {
  edit.mutate({ id: task.id, status: "done" });
  setUndo({ id: task.id, until: Date.now() + 5000 });
};
// Undo sends status: "open" — the API treats completing twice, or un-completing,
// as ordinary edits, so the toast needs no special endpoint.
```

The AI follow-up card is **not** built here ([04](../04-ai-copilot.md) §6 — it arrives with S4);
a task with `source: "ai"` shows an "AI" badge and nothing else changes.

- [ ] **Step 2: My day**

A greeting with the person's first name, three numbers (replied today, median first response, the
Taking chats switch — reuse `AvailabilitySwitch`), then Waiting on you, Due today and Hot leads, each
row a link to the thread, task or lead behind it. One column on a phone, two on desktop. It is
already live: `lead.updated` and `task.updated` invalidate `my-day`, and S2's conversation events
already do.

`TaskRow.test.tsx`: an overdue task reads as overdue to a screen reader as well as in red; completing
calls the mutation once; a task with no customer renders without an empty link.

- [ ] **Step 3: Check and commit**

```bash
npm run check:web
git add apps/web
git commit -m "feat(web): the tasks screen and my day"
```

---

## Task 15: Prove it, then write it down

**Files:**
- Modify: `apps/api/src/dealerai/scripts/seed_sales.py`, `apps/api/tests/test_seed_sales.py`
- Modify: `docs/sales/README.md`, `docs/sales/plans/s3-crm.md`

S2's lesson, applied: the suite passing is not the exit criterion. **A lead goes from new to won,
with tasks, in the browser** is the exit criterion.

- [ ] **Step 1: Give the seed a board worth looking at**

Extend `_seed`: Pollux's two pipelines (*Local sale* and *Export*), a lead for Omar in Negotiation
with a real score and signals, one for Karim in Qualified on the Export board, one won last week and
one lost with a reason, a profile on two customers with a mix of `ai` and `human` fields, a task
overdue by a day, one due this afternoon and one next week, and a second "Omar Al Mazrouei" record
with one phone identity so the merge dialog has something real to merge.

Extend the shape test in `test_seed_sales.py` the same way S2 did: assert the board has a lead in
more than one stage, that one lead is won and one lost with a reason, that the tasks land in three
different buckets, and that one customer has both a human-set and an AI-set profile field.

- [ ] **Step 2: Run everything**

```bash
COMPOSE_PROJECT_NAME=dealeraios npm run db:reset && npm run db:seed
# stop the worker first — it claims the suite's events
set -o pipefail; npm run check && npm run check:openapi
```

Expected: ruff, mypy, pytest, the 100%-branch guard suite, web typecheck, `check:rtl`, eslint,
Vitest, and no generated-type drift.

- [ ] **Step 3: Run the exit path in a browser**

Three terminals: `npm run api`, `npm run worker`, `npm run web`.

1. Sign in at `/dev-login` as **Ahmed Nasser**, open Omar's conversation and the customer panel.
   Correct the budget the AI guessed: the marker changes from AI to a person's, and the evidence
   link on a field the AI still owns jumps to the message it came from.
2. Create a lead from the panel. It appears on **Local sale**, first open stage, owned by Ahmed.
3. On `/pipeline`, move it through the stages — once by dragging, once from the Move to… menu. Each
   move survives a reload, shows in the stage history in the drawer, and writes a line in the
   conversation.
4. Open the drawer: the score's reasons add up to the score shown, and a reason with evidence opens
   the message it came from.
5. Add a task from the lead, due today. It appears on `/tasks` under Today and on `/today` under Due
   today. Complete it from `/today`; Undo puts it back.
6. Move the lead to **Won**. It leaves the board's open columns, the conversation says so, and
   `/today` drops it from Hot leads.
7. As **Sara Mansour** (manager), reassign Omar to **Mohamed Riad**: the dialog lists what will move,
   and afterwards the conversation, the lead and the open task are Mohamed's — and Ahmed's inbox no
   longer shows the conversation. The notification reaches Mohamed's bell without a refresh.
8. Merge the duplicate Omar record into the real one. The identities end up on one customer, the old
   URL explains where it went, and the timeline still has both sides of the history.
9. Switch to Arabic: the board mirrors, the drawer opens from the correct side, and the numbers stay
   Latin. At 360 px the board is one column per screen and the 360's tabs scroll rather than wrap.

Anything that does not happen is a bug in this slice, not a note for later.

- [ ] **Step 4: Record it**

In `docs/sales/README.md`, replace the Code row:

```markdown
| Code | **S3 CRM complete** on `sales/phase-1`: customers with a profile that says who set each value, the 360 and its timeline, reassign and merge, configurable pipelines, leads with stage history and an explainable score, tasks, and My day. Next: S4, the AI copilot |
```

Add a `## Review` section to this file the way [s2-inbox.md](s2-inbox.md) has one: what the exit run
showed, what was deliberately left, and everything found while running it — including anything the
suite was green through.

- [ ] **Step 5: Commit**

```bash
git add docs/sales apps/api/src/dealerai/scripts/seed_sales.py apps/api/tests/test_seed_sales.py
git commit -m "docs(sales): S3 CRM complete, with the exit run recorded"
```

---

## Review — 2026-09-22

Fifteen tasks, each ending green, and then the exit path run in a browser:
Ahmed Nasser signing in at `/dev-login`, correcting what the AI had guessed, winning a lead on the
board, and Sara Mansour handing the customer to Mohamed Riad and merging his duplicate record away.
Everything below was invisible to a suite that was passing at the time.

| Found | Why it mattered | Fixed in |
|---|---|---|
| The board a new workspace starts with was written three times — the migration's backfill, `app.create_tenant_with_owner`, and the test fixtures — and the fixtures had already drifted to five stages nobody has | A test failed on its own setup. Worse, the fixtures were proving a board no real workspace would ever have. One `app.seed_default_pipeline`, four callers | `d3d5733` |
| The merge's "drop an identity the keeper already has" guard could never fire | `unique (tenant_id, kind, value)` means two customers in one workspace cannot hold the same number, so the branch was dead code defending an impossible state — and its test failed on its own insert | `940d973` |
| `contact_assigned` was not among the notification kinds | The handover notification crashed on a check constraint. The kinds are a constraint rather than a lookup table on purpose, so adding one is a migration a reviewer can read | `06c6cf4` |
| A board's three rules answered with `400 {"field": "", "code": "value_error"}` | They were Pydantic validators. The person reshaping a board needs to read *which* rule they broke, so the rules moved into the route as 422s with sentences | `d3d5733` |
| Cutting the old event-line copy out of the inbox handler took the `@handler` decorator above the next function with it | `conversation.assign_requested` had no handler at all, and every assignment test still passed — they call the function directly. Only `test_every_emitted_event_has_a_handler` noticed | `df6ea9f` |
| Half the task tests created tasks due "now" | Which the product correctly calls overdue by the time the list is asked. The fixture now asks the same window function the route uses | `46356e4` |
| `TaskOut` collided with the marketing agent's `TaskOut`, and the CRM had grown two `Money` models | FastAPI namespaced them into `dealerai__routes__tasks__TaskOut` in the browser's generated types. The sales one is `SalesTask`; customers now uses the `Money` in leads | `5909caa` |
| A lead moved a second ago read **"-1 days here"** | The card's clock ticks once a minute, so it lags the move, and `Math.floor` turns a tiny negative into minus one | `51344cf` |
| `"—"` shipped as both the English and the Arabic string | The catalogue guard reads an identical translation as an untranslated one, and it is right: a dash is punctuation, so it left the catalogue | `ca625bd` |
| A budget was handed to the salesperson as "AED 235,000" to type over | Which is how you get "AED 235,000228000" — it happened the first time a human edited one. Money edits as a plain number now | `716a9ce` |
| A deal already won stayed on My day under **Hot leads** | It is not something to chase this morning. That list asks for open leads only | `716a9ce` |

Sound as built, and left alone: the migration and its backfill, the two single-writer functions and
the ownership invariant, the profile's human-beats-AI rule, the scoring arithmetic, the customers
cursor, the visibility matrix, and the invalidate-only live updates from S2.

Known and deliberately not changed in S3:

- **PDPL export and erasure** (`GET /v1/customers/{id}/export`, `DELETE /v1/customers/{id}`) are not
  built. They need the retention job in [02](../02-data-model.md) § 7 and belong with S6 — but they
  have to land before the pilot puts real customer data in S7.
- AI-written profile values, AI signals in the score, automatic leads and the follow-up card are
  S4's. The panel already marks and explains AI values; there is simply nothing writing them yet.
- Bulk reassign from the customers list waits for S6; the single-customer path is here.
- `PUT /v1/pipelines/{id}/stages` has no screen. A dealership reshapes its board by API until S6's
  settings arrive.
- Stage names are the dealership's own words, so they stay as typed in both languages. The Arabic UI
  mirrors around them.
- The merge keeps the surviving record's values where it has any, per
  [05](../05-workflows.md) § 10 — which means a guess on the keeper beats a person's answer on the
  duplicate. The dialog shows both sides first and the audit row keeps what lost, but it is worth
  revisiting before the pilot.

**Verified end to end on 2026-09-22**, with the API, the worker and the web app running against a
freshly seeded workspace:

1. **My day** as Ahmed: replied today 1, median first reply 6m, Omar "Missed 22m" and Mona
   "Due soon 3m" waiting, one task due, one hot lead.
2. **The panel beside the thread**: the budget the AI had guessed was corrected to AED 228,000 and
   its marker changed from AI to a person's; the marker still on "Interested in" scrolled the thread
   to the message it was inferred from and flashed it.
3. **The board**: two pipelines, a lead in most columns of Local sale, and Omar's Land Cruiser moved
   Negotiation → Won from the card's menu. The conversation said "Lead moved to Won" and the lead's
   history said "Negotiation → Won".
4. **My day again**: the won deal was gone from Hot leads — after the fix above.
5. **Handing over** as Sara: the dialog listed what moves (0 open leads, 1 open task) and who is
   taking chats, and afterwards the 360 said Mohamed Riad. The customer's timeline carried
   "Reassigned to Mohamed Riad", and Mohamed's own tab read **"(1) DealerAI OS"** with
   *"Omar Al Mazrouei is yours now — Handed over by Sara Mansour"* in the bell.
6. **Merging** the duplicate: the dialog showed both records side by side, and afterwards one
   customer held all three identities while the duplicate's URL answered
   *"This customer was merged into another record."* with a link to the survivor.
7. **Arabic**: the board, the filters and the cards mirror, with no horizontal scroll; at 360 px one
   column fills the screen and the 360's tabs fit without wrapping.

One thing about running it, unchanged from S2 and worth repeating: the suite shares the development
database, so `npm run check` wipes the seeded workspace — it did it twice during this run. Re-seed
before demonstrating anything.

---

## Spec coverage

| Requirement | Where |
|---|---|
| `pipelines`, `pipeline_stages`, `tasks`, the `leads` changes ([02](../02-data-model.md) §2–§3) | 1 |
| Policies for the new tables, live-update triggers, the indexes ([02](../02-data-model.md) §4–§6) | 1 |
| `app.reassign_contact`, `app.merge_contacts` and the ownership invariant ([02](../02-data-model.md) §4, [05](../05-workflows.md) §9–§10) | 2 |
| Profile fields with `source`, evidence and human precedence ([04](../04-ai-copilot.md) §4, [06](../06-api-contract.md) §4) | 3 |
| `sales/scoring.py`, weights, bands, reasons ([04](../04-ai-copilot.md) §5) | 4 |
| `GET /v1/customers`, `/{id}`, `/timeline`, `PATCH` ([06](../06-api-contract.md) §4) | 5 |
| `POST /v1/customers/{id}/reassign`, `POST /v1/customers/merge`, `contact.reassigned` | 6 |
| `GET /v1/pipelines`, `PUT /v1/pipelines/{id}/stages`, `stage-in-use` | 7 |
| `GET/POST /v1/leads`, `GET/PATCH /v1/leads/{id}`, stage history, won and lost | 8 |
| `GET/POST /v1/tasks`, `PATCH /v1/tasks/{id}`, the buckets | 9 |
| `GET /v1/dashboard/me` ([06](../06-api-contract.md) §7) | 10 |
| Generated types, hooks, live invalidation, URL filters ([07](../07-frontend.md) §3) | 11 |
| Customer panel, Customer 360, customers list ([08](../08-screens.md) §5–§7) | 12 |
| Pipeline board and lead drawer ([08](../08-screens.md) §8) | 13 |
| Tasks and My day ([08](../08-screens.md) §9–§10) | 14 |
| "A lead goes from new to won, with tasks, in the UI" ([09](../09-implementation-plan.md)) | 15 |

## Execution

Task by task on `sales/phase-1`, with `superpowers:subagent-driven-development` or
`superpowers:executing-plans`. Suggested checkpoints: after 4 (the database and the two pure
modules), after 10 (the API complete, provable with curl), after 15 (the slice). Every task ends
with a green suite and one commit — and Task 15 ends with a browser, not a test run.
