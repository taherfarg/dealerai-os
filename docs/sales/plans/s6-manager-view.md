# Sales S6 — Manager view Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sara Mansour opens one page at half past eight and runs her morning from it: a line saying
what yesterday was, the customers waiting past their target with Reassign beside each, who on her
teams is slipping, and where the pipeline stands — every number one click from the rows behind it.
Khalid changes opening hours, routing, the pipeline, quick replies, the knowledge documents and the
AI's settings from screens instead of API calls. And a customer who asks what Pollux holds about them
gets it as one file, or is erased from every table that held them — the part the pilot cannot start
without.

**Architecture:** no new process and no new dependency. The dashboard is one request that reads
through the caller's own visibility, so a manager's numbers are her teams' because Postgres shows her
nothing else — not because a query remembered to filter. The two daily jobs (the 08:00 brief, the
03:00 retention pass) run on the existing queue: once an hour the worker asks one `security definer`
function for every tenant's id and timezone — the one cross-tenant read, and it returns nothing else
— and schedules each tenant's next run at that tenant's local hour, deduped on the date, so the pass
is idempotent and a chain an outage broke is back within the hour. The brief is rows the screen
renders in the reader's language plus one model-written headline, which a guard refuses if it holds
any number the facts did not. Erasure is one SQL function, used by the owner's DELETE and by the
retention job alike.

**Tech stack:** Postgres 17 · asyncpg · FastAPI · Pydantic v2 · Gemini through the existing gateway
(`TaskKind.ANALYSIS`) · Next.js 16 · React 19 · TanStack Query · Vitest · pytest.

**Before you start:**

- Docker Desktop running; prefix database commands with `COMPOSE_PROJECT_NAME=dealeraios` in this
  worktree. Branch `sales/phase-1`.
- **Stop the worker before running the suite** — it claims the tests' events. Every DB test run also
  deletes the seeded workspace: run `npm run db:seed` again before looking at anything in a browser.
- Read [../08-screens.md](../08-screens.md) §11 and §13 (the screens),
  [../05-workflows.md](../05-workflows.md) §13–§14 (the brief, retention and erasure),
  [../06-api-contract.md](../06-api-contract.md) §2, §4, §7 and §12, and
  [../02-data-model.md](../02-data-model.md) §7.
- **A green suite is not a working feature** — four slices running. The dashboard's failure mode is
  a plausible wrong number: a median that flatters, a count over rows the manager cannot see. Every
  dashboard test seeds rows and asserts the number *is* those rows.
- **Erasure is the one irreversible thing in this product.** Its test seeds a customer into every
  table that can hold them — including the three that do not cascade from a contact (conversations,
  tasks, notifications) and the snapshot a merge leaves in the audit log — and asserts each is empty
  afterwards, and that the customer next to them is untouched.
- As in S3 and S4: backend modules are given whole; screen tasks give the parts that carry a decision,
  and tests as their names and assertions, with `…` where a fixture repeats one written above.

**Found while reading the code for this plan** — fixed in the tasks named:

| Found | Why it matters | Task |
|---|---|---|
| A missed response target is only a notification | A notification is somebody's, is deleted after 90 days, and goes with its reader. The dashboard counts misses per day and per salesperson; there was nothing to count | 4 |
| My day's median first response is measured from the customer's *last* message before the answer | A customer who wrote at 10:00 and again at 10:30 had waited half an hour at 10:31, not a minute. The number flatters exactly the slow replies | 4 |
| …and in wall-clock time, while the target is in business hours | Answering a 23:30 message at 09:02 is on time and was counted as nine and a half hours late — the pilot's S2 criterion reads this number | 4 |
| The contract gives a viewer the manager dashboard; `permissions.py` gives a viewer nothing | [06](../06-api-contract.md) §12 is the specification | 5 |
| `conversations.contact_id` is `on delete set null` | Deleting a contact would orphan their whole message history rather than erase it | 1 |

---

## What this slice does not build

| Item | Arrives with |
|---|---|
| Connect WhatsApp (Embedded Signup), the history-sync progress bar, "Assign imported customers" | S5. The Channels section here lists the channel and its templates, and says where Connect will be |
| Settings → Notifications, `POST/DELETE /v1/push-subscriptions`, web push | S7, with the installable app |
| Invitations on the Team screen, `accept-invite`, a real sign-in ([08](../08-screens.md) §14) | S7. `POST /v1/tenants/{id}/invites` exists; the page that accepts one does not, and an invitation nobody can accept is worse than none |
| `GET /v1/brief/today` | Not built: [06](../06-api-contract.md) §7 has the dashboard return the brief in its one request, and nothing else reads it |
| Aggregating `ai_suggestions` older than 12 months into daily rows ([02](../02-data-model.md) §7) | Before the first row turns 12 months old (2027-09). Until then a suggestion is erased with its conversation, and retention bounds that |
| Per-vehicle Arabic aliases for the inventory guard | S7's Arabic pass. The S4 review pointed at "S6's inventory settings"; [08](../08-screens.md) §13 has no inventory section — Inventory is DealerAI OS's screen |
| A retention setting on screen | `retention_months` is writable over the API by owners and admins; Pollux keeps the 24-month default |
| Date filters on the inbox and pipeline lists | Later. A tile opens the list it counts from; those lists have no date filter yet |

---

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0011_sales_manager.sql` | **Create.** `sla_misses`, `sales_briefs`, `quick_replies`, `v_suggestion_acceptance`, `app.tenant_clocks()`, `app.erase_contact()`, the `brief_ready` kind |
| `apps/api/src/dealerai/media/storage.py` | **Modify.** `remove()` |
| `apps/api/src/dealerai/events/handlers/privacy.py` | **Create.** `media.delete`, `sales.retention_due` |
| `apps/api/src/dealerai/sales/clock.py` | **Create.** Every tenant's next 08:00 and 03:00, scheduled |
| `apps/api/src/dealerai/worker.py` | **Modify.** The hourly clock pass |
| `apps/api/src/dealerai/sales/hours.py` | **Modify.** `open_seconds()` — a wait, in business hours |
| `apps/api/src/dealerai/sales/settings.py` | **Modify.** `retention_months`, `arabic_register` |
| `apps/api/src/dealerai/db/queries/dashboard.py` | **Create.** Every number the dashboard and the brief show |
| `apps/api/src/dealerai/sales/dashboard.py` | **Create.** Windows, waits, medians, the ranked list, the brief's facts |
| `apps/api/src/dealerai/guards/facts.py` | **Create.** Every number in a headline is one of the facts |
| `apps/api/src/dealerai/ai/prompts/brief.md` | **Create.** The headline |
| `apps/api/src/dealerai/agents/sales/brief.py` | **Create.** The brief's one model call |
| `apps/api/src/dealerai/events/handlers/manager.py` | **Create.** `sales.brief_due` |
| `apps/api/src/dealerai/events/handlers/inbox.py` | **Modify.** A missed target writes its row |
| `apps/api/src/dealerai/events/handlers/notify.py` | **Modify.** Where a brief notification goes |
| `apps/api/src/dealerai/routes/dashboard.py` | **Modify.** `GET /v1/dashboard/manager`; My day's median through the shared definition |
| `apps/api/src/dealerai/routes/customers.py` | **Modify.** Export and erasure |
| `apps/api/src/dealerai/routes/settings.py` | **Create.** `GET/PATCH /v1/settings/sales`, acceptance |
| `apps/api/src/dealerai/routes/quick_replies.py` | **Create.** The shortcuts |
| `apps/api/src/dealerai/routes/team.py` | **Modify.** Rename and delete a team |
| `apps/api/src/dealerai/core/permissions.py` | **Modify.** A viewer reads the dashboard |
| `apps/api/src/dealerai/agents/sales/copilot.py` | **Modify.** The Arabic register setting reaches the prompt |
| `apps/api/src/dealerai/scripts/seed_sales.py` | **Modify.** A yesterday worth a brief; quick replies |
| `apps/web/app/[tenant]/dashboard/page.tsx` | **Modify.** The dashboard |
| `apps/web/components/manager/*` | **Create.** `StatTile`, `BriefCard`, `WaitingList`, `RepTable` |
| `apps/web/app/[tenant]/settings/**` | **Create.** The layout and seven sections |
| `apps/web/components/settings/*` | **Create.** `HoursEditor`, `RuleEditor`, `describeRule`, `StageEditor`, `QuickReplyForm` |
| `apps/web/components/inbox/QuickReplyMenu.tsx`, `Composer.tsx` | **Create / Modify.** `/` in the composer |
| `apps/web/components/crm/EraseDialog.tsx`, the customer pages | **Create / Modify.** Export, erasure, handing many customers over |
| `apps/web/app/[tenant]/tasks/page.tsx` | **Modify.** A manager can pick one person's tasks, so a dashboard link can land there |
| `apps/web/lib/api/{keys,hooks}.ts`, `lib/live.tsx`, `lib/i18n-client.tsx` | **Modify.** The new queries, what invalidates them, `useLocale` |
| `apps/web/messages/{en,ar}.ts` | **Modify.** Every string this slice shows |

---

## Task 1: The rows a morning is counted from

**Files:**
- Create: `supabase/migrations/0011_sales_manager.sql`
- Create: `apps/api/tests/test_manager_schema.py`

Everything S6 stores, in one migration. Two decisions carry the slice. A missed target becomes a row
of its own, because the only record of one today is a notification. And erasure is a function in the
database, because a contact's conversations do not cascade (`on delete set null` since 0001) and an
erasure spread over Python calls is an erasure a crash can leave half done.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_manager_schema.py`:

```python
"""What 0011_sales_manager.sql must be true about."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, TENANT_B, USER_A, jwt_session
from dealerai.db.session import system_session, tenant_session

NOW = datetime.now(UTC)


async def _conversation_of(su: asyncpg.Connection, name: str) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        """select cv.id from conversations cv join contacts ct on ct.id = cv.contact_id
            where ct.full_name = $1""",
        name,
    )


async def _miss(su: asyncpg.Connection, conversation_id: uuid.UUID, rep: uuid.UUID | None) -> None:
    await su.execute(
        """insert into sla_misses (tenant_id, conversation_id, assigned_to, waiting_since, due_at)
           values ($1, $2, $3, $4, $5)""",
        TENANT_A,
        conversation_id,
        rep,
        NOW - timedelta(minutes=9),
        NOW - timedelta(minutes=4),
    )


async def test_a_miss_is_seen_exactly_when_its_conversation_is(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    mine = await _conversation_of(su, "s1 customer")
    await _miss(su, mine, SALES_1)
    await _miss(su, await _conversation_of(su, "s2 customer"), None)
    async with tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        seen = [row["conversation_id"] for row in await conn.fetch("select * from sla_misses")]
    assert seen == [mine]


async def test_one_wait_is_missed_once(su: asyncpg.Connection, seeded: None) -> None:
    """The check that writes a miss can run twice; the miss cannot exist twice."""
    conversation_id = await su.fetchval(
        "select id from conversations where tenant_id = $1", TENANT_A
    )
    await _miss(su, conversation_id, None)
    with pytest.raises(asyncpg.UniqueViolationError):
        await _miss(su, conversation_id, None)


async def test_a_brief_is_its_readers_alone(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    for reader in (OWNER, MANAGER):
        await su.execute(
            """insert into sales_briefs (tenant_id, user_id, brief_date, facts)
               values ($1, $2, current_date, '{}')""",
            TENANT_A,
            reader,
        )
    async with tenant_session(TENANT_A, user_id=MANAGER, scope="team") as conn:
        assert await conn.fetchval("select array_agg(user_id) from sales_briefs") == [MANAGER]
    async with tenant_session(TENANT_A) as conn:  # the worker writes everybody's
        assert await conn.fetchval("select count(*) from sales_briefs") == 2


@pytest.mark.parametrize("shortcut", ["price", "/Price", "/two words", "/" + "x" * 31, "/"])
async def test_a_shortcut_is_a_slash_and_a_word(
    su: asyncpg.Connection, seeded: None, shortcut: str
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await su.execute(
            """insert into quick_replies (tenant_id, shortcut, title, body)
               values ($1, $2, 'Price', '{"en": "It is"}')""",
            TENANT_A,
            shortcut,
        )


async def test_two_quick_replies_cannot_share_a_shortcut(
    su: asyncpg.Connection, seeded: None
) -> None:
    insert = """insert into quick_replies (tenant_id, shortcut, title, body)
                values ($1, '/price', 'Price', '{"en": "It is"}')"""
    await su.execute(insert, TENANT_A)
    await su.execute(insert, TENANT_B)  # another dealership's /price is theirs
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(insert, TENANT_A)


async def test_a_quick_reply_says_something_in_some_language(
    su: asyncpg.Connection, seeded: None
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await su.execute(
            """insert into quick_replies (tenant_id, shortcut, title, body)
               values ($1, '/empty', 'Empty', '{"de": "Hallo"}')""",
            TENANT_A,
        )


async def _suggestion(
    su: asyncpg.Connection,
    conversation_id: uuid.UUID,
    outcome: str | None,
    ratio: float | None = None,
) -> None:
    await su.execute(
        """insert into ai_suggestions (tenant_id, conversation_id, status, text, intent,
                                       outcome, edit_ratio)
           values ($1, $2, 'superseded', 'Hello', 'price', $3, $4)""",
        TENANT_A,
        conversation_id,
        outcome,
        ratio,
    )


async def test_acceptance_counts_a_light_edit_as_accepted(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    conversation_id = await su.fetchval(
        "select id from conversations where tenant_id = $1", TENANT_A
    )
    for outcome, ratio in (("sent", 0.0), ("edited", 0.1), ("edited", 0.5), ("discarded", None)):
        await _suggestion(su, conversation_id, outcome, ratio)
    await _suggestion(su, conversation_id, None)  # never decided: not in the metric
    async with tenant_session(TENANT_A) as conn:
        row = await conn.fetchrow(
            """select sum(decided) as decided, sum(sent) as sent,
                      sum(lightly_edited) as lightly, sum(rewritten) as rewritten,
                      sum(discarded) as discarded
                 from v_suggestion_acceptance where intent = 'price'"""
        )
    assert dict(row) == {"decided": 4, "sent": 1, "lightly": 1, "rewritten": 1, "discarded": 1}


async def test_acceptance_reads_through_the_callers_visibility(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    await _suggestion(su, await _conversation_of(su, "s1 customer"), "sent")
    await _suggestion(su, await _conversation_of(su, "s2 customer"), "sent")
    async with tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        assert await conn.fetchval("select sum(decided) from v_suggestion_acceptance") == 1


async def test_the_clock_lists_every_active_tenant_and_nothing_more(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await su.execute("update tenants set status = 'paused' where id = $1", TENANT_B)
    async with system_session() as conn:  # no tenant: RLS would otherwise show none
        rows = await conn.fetch("select * from app.tenant_clocks()")
    assert [(row["id"], row["timezone"]) for row in rows] == [(TENANT_A, "Asia/Dubai")]
    assert list(rows[0].keys()) == ["id", "timezone"]


async def test_a_browser_cannot_ask_for_the_clocks(su: asyncpg.Connection, seeded: None) -> None:
    async with jwt_session(su, USER_A) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("select * from app.tenant_clocks()")


async def test_a_brief_is_a_kind_of_notification(su: asyncpg.Connection, seeded: None) -> None:
    await su.execute(
        """insert into notifications (tenant_id, user_id, kind, title, entity)
           values ($1, $2, 'brief_ready', 'Your morning brief', $3::jsonb)""",
        TENANT_A,
        USER_A,
        json.dumps({"type": "brief", "id": str(uuid.uuid4())}),
    )
```

`app.erase_contact` is tested through the route that calls it, in Task 2.

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/api && uv run pytest tests/test_manager_schema.py -q`
Expected: FAIL — `relation "sla_misses" does not exist`.

- [ ] **Step 3: Write the migration**

`supabase/migrations/0011_sales_manager.sql`:

```sql
-- =============================================================================
-- 0011_sales_manager — Sales S6: the manager's morning, the settings screens,
-- and a customer's right to their data. See docs/sales/02-data-model.md § 2
-- and § 7, and docs/sales/05-workflows.md § 13–14.
-- =============================================================================

-- =============================================================================
-- A MISSED TARGET IS A FACT
-- Until now a miss was a notification and nothing else, and a notification is
-- somebody's, is deleted after 90 days, and goes when its reader does. The
-- dashboard counts misses per day and per salesperson, so a miss is a row. A
-- child of its conversation: visible exactly when the conversation is, erased
-- with it. One per wait — the check that writes it can run twice.
-- =============================================================================
create table sla_misses (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  -- Whoever had the customer when the target passed: the miss counts against them.
  assigned_to     uuid references auth.users(id) on delete set null,
  waiting_since   timestamptz not null,
  due_at          timestamptz not null,
  created_at      timestamptz not null default now(),
  unique (conversation_id, waiting_since)
);
create index on sla_misses (tenant_id, due_at);

alter table sla_misses enable row level security;
alter table sla_misses force row level security;
create policy tenant_visibility on sla_misses
  using (
    app.has_tenant_access(tenant_id)
    and exists (select 1 from public.conversations c where c.id = sla_misses.conversation_id)
  )
  with check (app.has_tenant_access(tenant_id));
revoke all on sla_misses from anon, authenticated;
grant select, insert, update, delete on sla_misses to dealerai_app;

-- =============================================================================
-- THE MORNING BRIEF — docs/sales/05-workflows.md § 13
-- One row per reader per day: a manager's brief is written from what that
-- manager may see, so two managers with different teams read different
-- numbers and neither learns anything from the other's. A headline in both UI
-- languages and the numbers it was written from — never a customer's name:
-- the model is not shown one (sales/dashboard.render_facts), so nothing here
-- outlives a customer's erasure.
-- =============================================================================
create table sales_briefs (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  brief_date  date not null,
  -- {"en": "...", "ar": "..."}; null when there was nothing to say, no budget,
  -- or a line the facts guard refused.
  headline    jsonb,
  facts       jsonb not null,
  created_at  timestamptz not null default now(),
  unique (tenant_id, user_id, brief_date)
);

alter table sales_briefs enable row level security;
alter table sales_briefs force row level security;
create policy own_rows on sales_briefs
  using (app.has_tenant_access(tenant_id)
         and (user_id = (select app.current_user_id())
              or (select app.current_user_id()) is null))
  with check (app.has_tenant_access(tenant_id));
revoke all on sales_briefs from anon, authenticated;
grant select, insert, update, delete on sales_briefs to dealerai_app;

-- =============================================================================
-- QUICK REPLIES — docs/sales/02-data-model.md § 2
-- Tenant-wide: every salesperson types the same shortcuts, and a manager edits
-- them for everybody. At least one of the three languages.
-- =============================================================================
create table quick_replies (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  shortcut    text not null check (shortcut ~ '^/[a-z0-9-]{1,30}$'),
  title       text not null check (length(title) between 1 and 80),
  body        jsonb not null check (jsonb_typeof(body) = 'object'
                                    and body ?| array['ar', 'en', 'fr']),
  created_by  uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, shortcut)
);

alter table quick_replies enable row level security;
alter table quick_replies force row level security;
create policy tenant_isolation on quick_replies
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));
revoke all on quick_replies from anon, authenticated;
grant select, insert, update, delete on quick_replies to dealerai_app;
create trigger quick_replies_touch before update on quick_replies
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- ACCEPTANCE, BY INTENT — docs/sales/04-ai-copilot.md § 3 and § 9
-- The pilot's S5 metric: (sent + edited with edit_ratio ≤ 0.2) / decided.
-- security_invoker, so it reads through the caller's visibility rather than
-- its owner's; tests/test_tenant_isolation.py requires that of every view.
-- =============================================================================
create view v_suggestion_acceptance with (security_invoker = true) as
select tenant_id,
       (created_at at time zone 'UTC')::date                             as day,
       intent,
       count(*) filter (where outcome is not null)                       as decided,
       count(*) filter (where outcome = 'sent')                          as sent,
       count(*) filter (where outcome = 'edited' and edit_ratio <= 0.2)  as lightly_edited,
       count(*) filter (where outcome = 'edited' and edit_ratio > 0.2)   as rewritten,
       count(*) filter (where outcome = 'discarded')                     as discarded
  from ai_suggestions
 group by tenant_id, (created_at at time zone 'UTC')::date, intent;

revoke all on v_suggestion_acceptance from anon, authenticated;
grant select on v_suggestion_acceptance to dealerai_app;

-- =============================================================================
-- A CLOCK FOR EVERY DEALERSHIP
-- The brief is at 08:00 and retention at 03:00 in each tenant's own timezone,
-- and the worker cannot list tenants: under RLS a session with no tenant sees
-- none (db/session.py). This one read is the exception, as tenants_for_user
-- is: ids and timezones and nothing else, to the app role only.
-- =============================================================================
create or replace function app.tenant_clocks()
returns table (id uuid, timezone text)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select t.id, t.timezone from tenants t where t.status = 'active' order by t.id;
$$;

revoke all on function app.tenant_clocks() from public;
grant execute on function app.tenant_clocks() to dealerai_app;

-- =============================================================================
-- ERASURE — docs/sales/05-workflows.md § 14, the UAE PDPL
-- One function for both ways a customer leaves: an owner's DELETE, and the
-- nightly retention pass. Three things do not cascade from a contact and are
-- deleted by hand here: conversations (0001: on delete set null — deleting
-- the contact alone would orphan every message), tasks (set null), and
-- notifications (they name the customer in a title). A merge left a snapshot
-- of both records in audit_log (0009); the who and when stay, the what goes.
-- Returns the media paths, which only the worker can delete: Storage is not SQL.
--
-- Invoker's rights, so it runs under RLS: the caller's session must see the
-- whole customer. The route and the retention job both call it in a session
-- with no user, the one that reaches every colleague's notifications.
-- =============================================================================
create or replace function app.erase_contact(p_contact uuid, p_actor uuid, p_reason text)
returns text[]
language plpgsql
set search_path = public, pg_temp
as $fn$
declare
  v_tenant        uuid;
  v_conversations uuid[];
  v_leads         uuid[];
  v_tasks         uuid[];
  v_ids           text[];
  v_paths         text[];
begin
  select tenant_id into v_tenant from contacts where id = p_contact for update;
  if v_tenant is null then
    return null;
  end if;

  select coalesce(array_agg(id), '{}') into v_conversations
    from conversations where contact_id = p_contact;
  select coalesce(array_agg(id), '{}') into v_leads
    from leads where contact_id = p_contact;
  select coalesce(array_agg(id), '{}') into v_tasks
    from tasks
   where contact_id = p_contact
      or lead_id = any (v_leads)
      or conversation_id = any (v_conversations);
  v_ids := (v_conversations || v_leads || v_tasks || p_contact)::text[];

  select coalesce(array_agg(distinct asset->>'storage_path'), '{}') into v_paths
    from messages m
    cross join lateral jsonb_array_elements(m.media) asset
   where m.conversation_id = any (v_conversations)
     and asset->>'storage_path' is not null;

  -- What the models were shown about them: the runs, and their traces with them.
  delete from agent_runs
   where tenant_id = v_tenant
     and (goal_input->>'conversation_id' = any (v_ids)
          or goal_input->>'lead_id' = any (v_ids));
  -- Work still queued about them would run against rows that are gone.
  delete from events
   where tenant_id = v_tenant and status = 'pending'
     and (payload->>'conversation_id' = any (v_ids)
          or payload->>'lead_id' = any (v_ids)
          or payload->>'contact_id' = any (v_ids));
  delete from notifications where entity->>'id' = any (v_ids);
  delete from tasks where id = any (v_tasks);
  -- Messages, reads, drafts and misses go with their conversations.
  delete from conversations where id = any (v_conversations);
  update audit_log set before = null, after = null
   where entity_type = 'contact'
     and (entity_id = p_contact or meta->>'keep_id' = p_contact::text);
  -- Identities, leads and activities go with the contact.
  delete from contacts where id = p_contact;

  insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type, entity_id, meta)
  values (v_tenant,
          case when p_actor is null then 'system' else 'user' end,
          p_actor::text,
          'contact.erased', 'contact', p_contact,
          jsonb_build_object('reason', p_reason));
  return v_paths;
end $fn$;

revoke all on function app.erase_contact(uuid, uuid, text) from public;
grant execute on function app.erase_contact(uuid, uuid, text) to dealerai_app;

-- =============================================================================
-- ONE MORE THING WORTH INTERRUPTING SOMEBODY FOR
-- =============================================================================
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready'));
```

- [ ] **Step 4: Migrate and run the tests**

Run: `COMPOSE_PROJECT_NAME=dealeraios npm run db:migrate && cd apps/api && uv run pytest tests/test_manager_schema.py tests/test_tenant_isolation.py -q`
Expected: PASS — including `test_every_tenant_table_has_forced_rls` and
`test_every_view_is_security_invoker` over the new table and view.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0011_sales_manager.sql apps/api/tests/test_manager_schema.py
git commit -m "feat(sales): the rows a manager's morning is counted from"
```

---

## Task 2: A customer's copy, and a customer's erasure

**Files:**
- Modify: `apps/api/src/dealerai/media/storage.py`
- Create: `apps/api/src/dealerai/events/handlers/privacy.py`
- Modify: `apps/api/src/dealerai/events/handlers/__init__.py`
- Modify: `apps/api/src/dealerai/db/queries/crm.py`
- Modify: `apps/api/src/dealerai/routes/customers.py`
- Create: `apps/api/tests/test_customer_privacy.py`

The two PDPL routes from [06](../06-api-contract.md) §4. Export first, because the erasure dialog
offers it first.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_customer_privacy.py` — the fixture puts one customer in every table that can
hold them, beside a bystander who must survive:

```python
"""A customer's copy of their data, and their erasure — UAE PDPL."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import (
    MANAGER, OWNER, SALES_1, TEAM_LOCAL, TENANT_A, TENANT_B, reseed_with_people,
)
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.events.bus import Event
from dealerai.events.handlers.privacy import on_media_delete
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
PASSPORT = f"{TENANT_A}/messages/2026/09/passport.jpg"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


async def _everywhere() -> dict[str, uuid.UUID]:
    """Omar in every table that can hold him; Mona beside him."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        omar = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id)
               values ($1, 'Omar Haddad', $2, $3) returning id""",
            TENANT_A, SALES_1, TEAM_LOCAL,
        )
        await conn.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'phone', '+971500000001', true)""",
            TENANT_A, omar,
        )
        conversation = await conn.fetchval(
            """insert into conversations (tenant_id, contact_id, surface, owner_id, team_id,
                                          assigned_to)
               values ($1, $2, 'whatsapp', $3, $4, $3) returning id""",
            TENANT_A, omar, SALES_1, TEAM_LOCAL,
        )
        message = await conn.fetchval(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                     body, media)
               values ($1, $2, 'in', 'customer', 'customer', 'my passport', $3::jsonb)
               returning id""",
            TENANT_A, conversation,
            json.dumps([{"status": "ready", "storage_path": PASSPORT, "mime": "image/jpeg"}]),
        )
        await conn.execute(
            """insert into ai_suggestions (tenant_id, conversation_id, for_message_id, status,
                                           text)
               values ($1, $2, $3, 'ready', 'Thank you Omar')""",
            TENANT_A, conversation, message,
        )
        await conn.execute(
            """insert into sla_misses (tenant_id, conversation_id, assigned_to, waiting_since,
                                       due_at)
               values ($1, $2, $3, now() - interval '9 minutes', now() - interval '4 minutes')""",
            TENANT_A, conversation, SALES_1,
        )
        await conn.execute(
            """insert into conversation_reads (tenant_id, conversation_id, user_id, last_read_at)
               values ($1, $2, $3, now())""",
            TENANT_A, conversation, SALES_1,
        )
        stage = await conn.fetchrow(
            """select pipeline_id, id from pipeline_stages
                where tenant_id = $1 and category = 'open' order by position limit 1""",
            TENANT_A,
        )
        lead = await conn.fetchval(
            """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                                  owner_id, team_id)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""",
            TENANT_A, omar, conversation, stage["pipeline_id"], stage["id"], SALES_1, TEAM_LOCAL,
        )
        task = await conn.fetchval(
            """insert into tasks (tenant_id, title, due_at, assignee_id, lead_id)
               values ($1, 'Call Omar about the Patrol', now(), $2, $3) returning id""",
            TENANT_A, SALES_1, lead,
        )
        # Somebody else's notification about him: only a session without a user reaches it.
        await conn.execute(
            """insert into notifications (tenant_id, user_id, kind, title, entity)
               values ($1, $2, 'lead_hot', 'Omar Haddad is now a hot lead', $3::jsonb)""",
            TENANT_A, MANAGER, json.dumps({"type": "lead", "id": str(lead)}),
        )
        run = await conn.fetchval(
            """insert into agent_runs (tenant_id, trigger_type, autonomy, goal, goal_input)
               values ($1, 'event', 'copilot', 'draft', $2::jsonb) returning id""",
            TENANT_A, json.dumps({"conversation_id": str(conversation)}),
        )
        await conn.execute(
            """insert into agent_traces (tenant_id, run_id, kind, name, status, payload)
               values ($1, $2, 'tool', 'search_knowledge', 'ok', $3::jsonb)""",
            TENANT_A, run, json.dumps({"arguments": {"query": "Omar's passport"}}),
        )
        await conn.execute(
            """insert into events (tenant_id, event_type, payload, run_after)
               values ($1, 'conversation.idle', $2::jsonb, now() + interval '1 hour')""",
            TENANT_A, json.dumps({"conversation_id": str(conversation)}),
        )
        # The snapshot a merge left: both records, whole.
        await conn.execute(
            """insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type,
                                      entity_id, before, after, meta)
               values ($1, 'user', $2, 'contact.merged', 'contact', gen_random_uuid(),
                       '{"full_name": "Omar H"}', '{"full_name": "Omar Haddad"}', $3::jsonb)""",
            TENANT_A, str(OWNER), json.dumps({"keep_id": str(omar)}),
        )
        mona = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id)
               values ($1, 'Mona Fathy', $2, $3) returning id""",
            TENANT_A, SALES_1, TEAM_LOCAL,
        )
        return {"omar": omar, "conversation": conversation, "lead": lead, "task": task,
                "run": run, "mona": mona}
    finally:
        await conn.close()


async def _count(sql: str, *args: object) -> int:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return int(await conn.fetchval(sql, *args))
    finally:
        await conn.close()
```

The tests (`client = TestClient(app)`, `ids = asyncio.run(_everywhere())` at the top of each):

```python
def test_erasure_leaves_nothing_of_them() -> None:
    …
    response = client.delete(f"/v1/customers/{ids['omar']}", headers=_auth(OWNER))
    assert response.status_code == 204
    for sql, value in (
        ("select count(*) from contacts where id = $1", ids["omar"]),
        ("select count(*) from contact_identities where contact_id = $1", ids["omar"]),
        ("select count(*) from conversations where id = $1", ids["conversation"]),
        ("select count(*) from messages where conversation_id = $1", ids["conversation"]),
        ("select count(*) from ai_suggestions where conversation_id = $1", ids["conversation"]),
        ("select count(*) from sla_misses where conversation_id = $1", ids["conversation"]),
        ("select count(*) from conversation_reads where conversation_id = $1", ids["conversation"]),
        ("select count(*) from leads where id = $1", ids["lead"]),
        ("select count(*) from tasks where id = $1", ids["task"]),
        ("select count(*) from notifications where entity->>'id' = $1", str(ids["lead"])),
        ("select count(*) from agent_runs where id = $1", ids["run"]),
        ("select count(*) from agent_traces where run_id = $1", ids["run"]),
        ("select count(*) from events where event_type = 'conversation.idle'"
         " and payload->>'conversation_id' = $1", str(ids["conversation"])),
        ("select count(*) from audit_log where action = 'contact.merged' and before is not null"
         " and meta->>'keep_id' = $1", str(ids["omar"])),
    ):
        assert asyncio.run(_count(sql, value)) == 0, sql


def test_the_audit_says_who_and_when_and_never_what() -> None:
    # One 'contact.erased' row, actor_type 'user', actor_id str(OWNER), meta {"reason": "request"},
    # before and after null. The merge row is still there, its keep_id kept, its snapshots gone.


def test_their_files_are_queued_for_deletion() -> None:
    # One pending 'media.delete' event for TENANT_A whose payload paths == [PASSPORT].


def test_the_customer_beside_them_is_untouched() -> None:
    # Mona's contact row survives Omar's erasure.


def test_a_manager_may_not_erase_anyone() -> None:
    # MANAGER → 403, and Omar is still there. SALES_1 → 403.


def test_erasing_somebody_you_cannot_see_is_a_404() -> None:
    # A TENANT_B contact's id with TENANT_A's header → 404, and the row survives.


def test_erasing_twice_is_a_404_the_second_time() -> None:


def test_an_export_holds_everything_the_erasure_would_remove() -> None:
    # OWNER → 200, Content-Disposition 'attachment; filename="customer-<id>.json"'.
    # The body has customer.name 'Omar Haddad', the phone identity, the message body
    # 'my passport' with one media url ending in a signed /v1/media/ token, the lead,
    # and the task 'Call Omar about the Patrol'.


def test_an_export_is_itself_audited() -> None:
    # One 'contact.exported' row, actor_id str(OWNER), nothing in before or after.


def test_only_owners_and_admins_export() -> None:
    # MANAGER → 403 (settings.team), SALES_1 → 403.
```

And the worker's half, on a local storage directory:

```python
async def test_media_delete_removes_the_files_and_forgives_the_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    kept = tmp_path / PASSPORT
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"jpeg")
    event = Event(1, TENANT_A, "media.delete",
                  {"paths": [PASSPORT, f"{TENANT_A}/messages/gone.jpg"]}, 1, None)
    await on_media_delete(event)  # a retry after a partial run must not fail
    assert not kept.exists()


async def test_media_delete_refuses_another_tenants_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file under f"{TENANT_B}/…" named in TENANT_A's event is still there afterwards.
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/api && uv run pytest tests/test_customer_privacy.py -q`
Expected: FAIL — `ModuleNotFoundError: dealerai.events.handlers.privacy`.

- [ ] **Step 3: Teach storage to delete**

Append to `apps/api/src/dealerai/media/storage.py`:

```python
def _unlink_all(root: Path, storage_paths: list[str]) -> None:
    for storage_path in storage_paths:
        _local_path(root, storage_path).unlink(missing_ok=True)


async def remove(storage_paths: list[str]) -> None:
    """Delete objects. One that is already gone is not an error: an erasure is
    retried, and the second attempt must not fail on what the first finished.

    Anon key with RLS-backed storage policies, like upload and download — the
    bucket's policy has to allow delete for the app, which is a staging
    checklist item (S7), not something to work around with the service role.
    """
    if not storage_paths:
        return
    root = _local_root()
    if root is not None:
        await asyncio.to_thread(_unlink_all, root, storage_paths)
        return

    settings = get_settings()
    if not settings.supabase_anon_key:
        raise StorageUnavailable("SUPABASE_ANON_KEY is not set")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            "DELETE",
            f"{_base_url()}/storage/v1/object/{BUCKET}",
            json={"prefixes": [path.lstrip("/") for path in storage_paths]},
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {settings.supabase_anon_key}",
            },
        )
    if response.status_code >= 400:
        raise StorageUnavailable(f"delete failed ({response.status_code}): {response.text[:300]}")
```

- [ ] **Step 4: The worker's half**

`apps/api/src/dealerai/events/handlers/privacy.py`:

```python
"""A customer's right to be forgotten, and data that forgets itself.

`media.delete` removes the objects an erased row pointed at: SQL cannot reach
Storage, so `app.erase_contact` returns the paths and this finishes the job.
`sales.retention_due` is the nightly pass that makes the retention periods in
docs/sales/02-data-model.md § 7 true rather than written down.
"""

from __future__ import annotations

import structlog

from ...media import storage
from ..bus import Event, handler

log = structlog.get_logger()


@handler("media.delete")
async def on_media_delete(event: Event) -> None:
    """Only this tenant's objects. Every path starts with the tenant id
    (storage.object_path), so a path that does not is refused and logged,
    whatever wrote the event."""
    if event.tenant_id is None:
        raise ValueError("media.delete requires a tenant")
    prefix = f"{event.tenant_id}/"
    paths = [str(path) for path in event.payload.get("paths") or []]
    foreign = [path for path in paths if not path.startswith(prefix)]
    if foreign:
        log.error("media_delete_refused", tenant_id=str(event.tenant_id), count=len(foreign))
    await storage.remove([path for path in paths if path.startswith(prefix)])
```

Add `privacy` to the imports and `__all__` in `events/handlers/__init__.py`.

- [ ] **Step 5: The export's queries**

Append to `apps/api/src/dealerai/db/queries/crm.py`:

```python
#: A customer's file (routes/customers.export_customer). Notes are included:
#: what we wrote about somebody is data about them.
EXPORT_CONVERSATIONS = """
select id, surface, status, created_at, last_message_at
  from conversations where contact_id = $1 order by created_at
"""

EXPORT_MESSAGES = """
select m.conversation_id, m.created_at, m.direction, m.kind, m.type, m.origin, m.body,
       m.transcript->>'text' as transcript, m.location, m.media
  from messages m
  join conversations cv on cv.id = m.conversation_id
 where cv.contact_id = $1
 order by m.created_at, m.id
"""

EXPORT_TASKS = """
select title, kind, status, due_at, completed_at, created_at
  from tasks
 where contact_id = $1 or lead_id in (select id from leads where contact_id = $1)
 order by created_at
"""
```

- [ ] **Step 6: The routes**

In `apps/api/src/dealerai/routes/customers.py` — imports first:

```python
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..db.queries.crm import (
    EXPORT_CONVERSATIONS, EXPORT_MESSAGES, EXPORT_TASKS, IDENTITIES, MERGED_INTO,
    ONE_CUSTOMER, OPEN_LEADS, OPEN_TASK_COUNT, TIMELINE, list_sql,
)
from ..deps import Ctx, TenantContext, require_permission, require_role
from ..media import links
```

Then, after `reassign_customer`:

```python
#: Long enough to hand the file over and for the customer to open it. A link
#: that expires overnight is an export of nothing.
EXPORT_LINKS_LAST = timedelta(days=7)


def _exported(request: Request, media: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Absolute links: the file is read outside the app, by the customer."""
    base = str(request.base_url).rstrip("/")
    return [
        {
            "mime": asset.get("mime"),
            "filename": asset.get("filename"),
            "url": base
            + "/v1/media/"
            + links.sign(str(asset["storage_path"]), expires_in=EXPORT_LINKS_LAST),
        }
        for asset in media
        if asset.get("status") == "ready" and asset.get("storage_path")
    ]


@router.get("/{customer_id}/export")
async def export_customer(
    customer_id: UUID,
    request: Request,
    ctx: Annotated[TenantContext, Depends(require_permission("settings.team"))],
) -> JSONResponse:
    """Everything held about one customer, as one file — the PDPL right of
    access. Owners and admins (docs/sales/06-api-contract.md § 4), and audited:
    who took a copy, and when."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        row = await _row_or_404(conn, ctx.tenant_id, customer_id)
        identities = await conn.fetch(IDENTITIES, customer_id)
        conversations = await conn.fetch(EXPORT_CONVERSATIONS, customer_id)
        messages = await conn.fetch(EXPORT_MESSAGES, customer_id)
        leads = await conn.fetch(OPEN_LEADS, customer_id, False)
        tasks = await conn.fetch(EXPORT_TASKS, customer_id)
        await conn.execute(
            """insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type,
                                      entity_id)
               values ($1, 'user', $2, 'contact.exported', 'contact', $3)""",
            ctx.tenant_id,
            str(ctx.user.id),
            customer_id,
        )
    document = {
        "exported_at": datetime.now(UTC),
        "customer": {
            "id": row["id"],
            "name": row["full_name"],
            "language": row["language"],
            "country": row["country"],
            "tags": list(row["tags"] or []),
            "consent": dict(row["consent"] or {}),
            "profile": dict(row["profile"] or {}),
            "last_seen_at": row["last_seen_at"],
        },
        "identities": [{"kind": i["kind"], "value": i["value"]} for i in identities],
        "conversations": [dict(conversation) for conversation in conversations],
        "messages": [
            {
                **{key: message[key] for key in message.keys() if key != "media"},
                "media": _exported(request, list(message["media"] or [])),
            }
            for message in messages
        ],
        "leads": [lead_out(lead) for lead in leads],
        "tasks": [dict(task) for task in tasks],
    }
    return JSONResponse(
        jsonable_encoder(document),
        headers={"Content-Disposition": f'attachment; filename="customer-{customer_id}.json"'},
    )


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def erase_customer(
    customer_id: UUID,
    ctx: Annotated[TenantContext, Depends(require_role("admin"))],
) -> None:
    """Gone from every table that held them — the PDPL right to erasure.

    Looked up in the caller's session first, so a customer they cannot see is a
    404 like any other; erased in a session without a user, the only one that
    reaches every colleague's notifications about them. What remains is one
    audit row: who, when, and why — never what (docs/sales/05-workflows.md § 14).
    """
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await _row_or_404(conn, ctx.tenant_id, customer_id)
    async with tenant_session(ctx.tenant_id) as conn:
        paths = await conn.fetchval(
            "select app.erase_contact($1, $2, 'request')", customer_id, ctx.user.id
        )
        if paths:
            await emit(conn, "media.delete", {"paths": list(paths)}, tenant_id=ctx.tenant_id)
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_customer_privacy.py tests/test_customers_api.py tests/test_import_contracts.py -q`
Expected: PASS. `test_every_emitted_event_has_a_handler` now sees `media.delete` and its handler.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/dealerai/media/storage.py apps/api/src/dealerai/events/handlers/privacy.py \
        apps/api/src/dealerai/events/handlers/__init__.py apps/api/src/dealerai/db/queries/crm.py \
        apps/api/src/dealerai/routes/customers.py apps/api/tests/test_customer_privacy.py
git commit -m "feat(sales): a customer's copy of their data, and their erasure"
```

---
## Task 3: A clock for every dealership, and retention that happens

**Files:**
- Create: `apps/api/src/dealerai/sales/clock.py`
- Modify: `apps/api/src/dealerai/worker.py`
- Modify: `apps/api/src/dealerai/events/handlers/privacy.py`
- Modify: `apps/api/src/dealerai/sales/settings.py`
- Create: `apps/api/tests/test_clock.py`, `apps/api/tests/test_retention.py`

S2 and S4 both named the brief as the moment "APScheduler earns its keep". It does not: a scheduler
process would need to list tenants, which RLS forbids a session without one, and would add a second
process to deploy and monitor. What the brief needs is 08:00 *in each tenant's timezone*, and a
per-tenant event with `run_after` at that instant is exactly that. The hourly pass only makes sure
the next one exists.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_clock.py`:

```python
"""Every dealership's own 08:00 and 03:00."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B
from dealerai import worker
from dealerai.sales import clock
from dealerai.sales.clock import BRIEF_AT, RETENTION_AT, next_at, schedule_everyone, zone

DUBAI = ZoneInfo("Asia/Dubai")


def test_the_brief_is_at_eight_where_the_showroom_is() -> None:
    seven_in_dubai = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
    assert next_at(BRIEF_AT, DUBAI, seven_in_dubai) == datetime(2026, 9, 24, 4, 0, tzinfo=UTC)


def test_after_eight_it_is_tomorrows() -> None:
    nine_in_dubai = datetime(2026, 9, 24, 5, 0, tzinfo=UTC)
    assert next_at(BRIEF_AT, DUBAI, nine_in_dubai) == datetime(2026, 9, 25, 4, 0, tzinfo=UTC)


def test_retention_runs_at_three_in_the_morning() -> None:
    midnight_in_dubai = datetime(2026, 9, 23, 20, 0, tzinfo=UTC)
    assert next_at(RETENTION_AT, DUBAI, midnight_in_dubai) == datetime(2026, 9, 23, 23, 0, tzinfo=UTC)


def test_a_timezone_nobody_knows_is_utc_rather_than_a_stopped_clock() -> None:
    assert zone("Mars/Olympus") == ZoneInfo("UTC")


async def _scheduled(su: asyncpg.Connection) -> list[asyncpg.Record]:
    return await su.fetch(
        """select tenant_id, event_type, payload->>'date' as day, run_after from events
            where event_type in ('sales.brief_due', 'sales.retention_due')
              and status = 'pending'
            order by tenant_id, event_type"""
    )


async def test_a_pass_schedules_each_tenant_once_however_often_it_runs(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    now = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
    assert await schedule_everyone(now) == 2
    await schedule_everyone(now)
    rows = await _scheduled(su)
    assert [(row["tenant_id"], row["event_type"]) for row in rows] == [
        (TENANT_A, "sales.brief_due"),
        (TENANT_A, "sales.retention_due"),
        (TENANT_B, "sales.brief_due"),
        (TENANT_B, "sales.retention_due"),
    ]
    brief = rows[0]
    assert (brief["day"], brief["run_after"]) == ("2026-09-24", datetime(2026, 9, 24, 4, 0, tzinfo=UTC))


async def test_once_a_brief_has_run_the_next_pass_schedules_tomorrows(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await schedule_everyone(datetime(2026, 9, 24, 3, 0, tzinfo=UTC))
    await su.execute("update events set status = 'done' where event_type = 'sales.brief_due'")
    await schedule_everyone(datetime(2026, 9, 24, 4, 5, tzinfo=UTC))
    days = {row["day"] for row in await _scheduled(su) if row["event_type"] == "sales.brief_due"}
    assert days == {"2026-09-25"}


async def test_a_paused_dealership_gets_no_brief(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await su.execute("update tenants set status = 'paused' where id = $1", TENANT_B)
    assert await schedule_everyone(datetime(2026, 9, 24, 3, 0, tzinfo=UTC)) == 1


async def test_the_worker_keeps_the_clocks_through_a_failed_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    calls: list[int] = []

    async def flaky(now: datetime | None = None) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database away")
        stop.set()
        return 0

    monkeypatch.setattr(clock, "schedule_everyone", flaky)
    monkeypatch.setattr(worker, "CLOCK_EVERY_SECONDS", 0)
    await asyncio.wait_for(worker.keep_the_clocks(stop), timeout=5)
    assert len(calls) == 2
```

`apps/api/tests/test_retention.py`, on the `seeded` fixture (`alpha customer` is tenant A's):

```python
async def _run(tenant_id: uuid.UUID = TENANT_A) -> None:
    await on_retention_due(Event(1, tenant_id, "sales.retention_due", {"date": "2026-09-24"}, 1, None))


async def test_a_customer_silent_past_the_retention_period_is_erased(db, su, seeded) -> None:
    # alpha customer: last_seen_at and their conversation's last_message_at 25 months ago.
    # After _run(): the contact is gone, and one audit row reads
    # action 'contact.erased', actor_type 'system', meta {"reason": "retention"}.


async def test_a_customer_who_wrote_last_month_stays(db, su, seeded) -> None:


async def test_one_recent_message_keeps_a_customer_we_last_saw_long_ago(db, su, seeded) -> None:
    # last_seen_at 25 months ago, but a conversation with last_message_at yesterday: kept.


async def test_a_dealership_can_keep_less(db, su, seeded) -> None:
    # sales_settings {"retention_months": 6}; silent for 7 months → erased.


async def test_old_notifications_and_briefs_go_and_recent_ones_stay(db, su, seeded) -> None:
    # A 91-day-old notification and brief are deleted; a 1-day-old of each survives.


async def test_raw_webhook_bodies_go_after_fourteen_days(db, su, seeded) -> None:
    # They hold message text and phone numbers, and an erasure cannot find them:
    # a 15-day-old webhook_deliveries row is deleted, a 1-day-old one stays.


async def test_the_other_dealership_is_untouched(db, su, seeded) -> None:
    # beta customer, silent 25 months, survives tenant A's pass.


async def test_erased_customers_files_are_queued(db, su, seeded) -> None:
    # alpha customer's message carries a ready media path; after _run() one pending
    # media.delete event for TENANT_A names it.
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/api && uv run pytest tests/test_clock.py tests/test_retention.py -q`
Expected: FAIL — `ModuleNotFoundError: dealerai.sales.clock`.

- [ ] **Step 3: The clock**

`apps/api/src/dealerai/sales/clock.py`:

```python
"""Every dealership's own 08:00 and 03:00.

The brief is at eight in the morning where the showroom is and retention at
three at night, so neither can be one global schedule. Each tenant's next run
is an event whose `run_after` is that tenant's local hour. Once an hour the
worker asks app.tenant_clocks() — the one cross-tenant read, ids and timezones
only — and schedules whatever is not already scheduled. The dedupe key is the
local date, so a pass that finds tomorrow's run waiting adds nothing, and a
chain an outage broke is back on time within the hour.

ponytail: an hourly pass in the worker rather than a scheduler process. Upgrade
trigger: a job that needs minute precision with no event to hang it on.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ..db.session import system_session
from ..events.bus import emit

BRIEF_AT = time(8, 0)
RETENTION_AT = time(3, 0)


def zone(name: str | None) -> ZoneInfo:
    """A tenant's timezone, or UTC when the name means nothing: a typo in one
    tenant's settings must not stop the clock (routes/tasks.day_start)."""
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001 - ZoneInfo raises several types for a bad key
        return ZoneInfo("UTC")


def next_at(at: time, tz: ZoneInfo, now: datetime) -> datetime:
    """The next instant the local clock reads `at`: today if still ahead, else tomorrow."""
    local = now.astimezone(tz)
    today = local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if today > local:
        return today.astimezone(UTC)
    tomorrow = (local + timedelta(days=1)).replace(
        hour=at.hour, minute=at.minute, second=0, microsecond=0
    )
    return tomorrow.astimezone(UTC)


async def schedule(conn: Any, tenant_id: UUID, tz: ZoneInfo, now: datetime) -> None:
    """One tenant's next brief and next retention pass, unless already scheduled."""
    brief = next_at(BRIEF_AT, tz, now)
    brief_day = brief.astimezone(tz).date().isoformat()
    await emit(
        conn,
        "sales.brief_due",
        {"date": brief_day},
        tenant_id=tenant_id,
        dedupe_key=f"brief:{brief_day}",
        run_after=brief,
        priority=1,
    )
    sweep = next_at(RETENTION_AT, tz, now)
    sweep_day = sweep.astimezone(tz).date().isoformat()
    await emit(
        conn,
        "sales.retention_due",
        {"date": sweep_day},
        tenant_id=tenant_id,
        dedupe_key=f"retention:{sweep_day}",
        run_after=sweep,
    )


async def schedule_everyone(now: datetime | None = None) -> int:
    """One pass over every active tenant; returns how many it saw.

    `events` has no RLS (it is isolated by GRANT), so a session with no tenant
    may write to it — the claim loop does the same.
    """
    moment = now or datetime.now(UTC)
    async with system_session() as conn:
        tenants = await conn.fetch("select id, timezone from app.tenant_clocks()")
        for tenant in tenants:
            await schedule(conn, tenant["id"], zone(tenant["timezone"]), moment)
    return len(tenants)
```

- [ ] **Step 4: The worker keeps it**

In `apps/api/src/dealerai/worker.py`, import `from .sales import clock` and add:

```python
#: How often every tenant's next brief and retention pass is checked
#: (sales/clock.py). Two inserts per tenant, which the dedupe key almost
#: always turns into nothing.
CLOCK_EVERY_SECONDS = 3600


async def keep_the_clocks(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await clock.schedule_everyone()
        except Exception:
            # The next pass is the retry. A worker that dies here stops
            # answering customers to protect a morning brief.
            log.exception("clock_pass_failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=CLOCK_EVERY_SECONDS)
```

and in `main()` the gather becomes:

```python
        await asyncio.gather(*(w.run_forever(stop) for w in workers), keep_the_clocks(stop))
```

- [ ] **Step 5: How long a dealership keeps a customer**

In `apps/api/src/dealerai/sales/settings.py`, on `SalesSettings`:

```python
    #: Months a customer is kept after their last activity, then erased whole
    #: by the nightly pass (docs/sales/02-data-model.md § 7). Owners and admins
    #: change it (routes/settings.WRITERS); there is no screen for it yet.
    retention_months: int = Field(default=24, ge=1, le=120)
```

- [ ] **Step 6: The nightly pass**

Append to `apps/api/src/dealerai/events/handlers/privacy.py` (and extend its imports with
`datetime`, `timedelta`, `UTC`, `system_session`, `tenant_session`, `emit` and `SalesSettings`):

```python
#: docs/sales/02-data-model.md § 7.
NOTIFICATIONS_KEPT = timedelta(days=90)
BRIEFS_KEPT = timedelta(days=90)
WEBHOOKS_KEPT = timedelta(days=14)
#: ponytail: a backlog clears over several nights. Raise it if a first run
#: ever finds thousands.
ERASED_PER_NIGHT = 500

#: Nothing from them or to them for the retention period: the later of when
#: we last saw them and the last message in any of their conversations.
STALE_CUSTOMERS = """
select ct.id
  from contacts ct
 where greatest(ct.last_seen_at,
                coalesce((select max(cv.last_message_at) from conversations cv
                           where cv.contact_id = ct.id), ct.last_seen_at))
       < now() - make_interval(months => $1)
 order by ct.last_seen_at
 limit $2
"""


@handler("sales.retention_due")
async def on_retention_due(event: Event) -> None:
    """Make the retention periods true.

    Customers go whole, through the same function as an owner's DELETE.
    Notifications and briefs go by age. And raw webhook bodies — which hold
    message text and phone numbers, and are the one copy an erasure cannot
    find — go after fourteen days.
    """
    if event.tenant_id is None:
        raise ValueError("sales.retention_due requires a tenant")
    tenant_id = event.tenant_id
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as conn:
        raw = await conn.fetchval("select sales_settings from tenants where id = $1", tenant_id)
        months = SalesSettings.model_validate(raw or {}).retention_months
        stale = [row["id"] for row in await conn.fetch(STALE_CUSTOMERS, months, ERASED_PER_NIGHT)]

    paths: list[str] = []
    for contact_id in stale:
        # A transaction each: one customer who fails to erase must not keep
        # the rest another night.
        async with tenant_session(tenant_id) as conn:
            erased = await conn.fetchval(
                "select app.erase_contact($1, null, 'retention')", contact_id
            )
            paths.extend(erased or [])

    async with tenant_session(tenant_id) as conn:
        await conn.execute("delete from notifications where created_at < $1", now - NOTIFICATIONS_KEPT)
        await conn.execute("delete from sales_briefs where created_at < $1", now - BRIEFS_KEPT)
        if paths:
            await emit(conn, "media.delete", {"paths": paths}, tenant_id=tenant_id)
    async with system_session() as conn:
        # Written before a tenant is known, so no tenant owns the old ones:
        # every tenant's pass may delete them, and a second delete finds none.
        await conn.execute(
            "delete from webhook_deliveries where received_at < $1", now - WEBHOOKS_KEPT
        )
    log.info("retention_done", tenant_id=str(tenant_id), erased=len(stale))
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_clock.py tests/test_retention.py tests/test_import_contracts.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/dealerai/sales/clock.py apps/api/src/dealerai/worker.py \
        apps/api/src/dealerai/events/handlers/privacy.py apps/api/src/dealerai/sales/settings.py \
        apps/api/tests/test_clock.py apps/api/tests/test_retention.py
git commit -m "feat(sales): every dealership's own clock, and retention that happens"
```

---

## Task 4: A miss that leaves a row, and a wait that starts at the first message

**Files:**
- Modify: `apps/api/src/dealerai/events/handlers/inbox.py`
- Modify: `apps/api/src/dealerai/sales/hours.py`
- Create: `apps/api/src/dealerai/db/queries/dashboard.py`
- Create: `apps/api/src/dealerai/sales/dashboard.py`
- Modify: `apps/api/src/dealerai/routes/dashboard.py`
- Test: `apps/api/tests/test_response_targets.py`, `tests/test_sales_hours.py`, `tests/test_my_day.py`

Three corrections to numbers S2 and S3 produce, before the dashboard shows them to anybody.

- [ ] **Step 1: Write the failing tests**

In `apps/api/tests/test_sales_hours.py`:

```python
DUBAI = ZoneInfo("Asia/Dubai")
#: Monday to Saturday, nine to nine; Sunday closed.
SHOWROOM = SalesSettings.model_validate(
    {"business_hours": {day: {"open": "09:00", "close": "21:00"}
                        for day in ("mon", "tue", "wed", "thu", "fri", "sat")}}
)


def test_a_wait_counts_only_the_minutes_the_team_is_open() -> None:
    asked = datetime(2026, 9, 21, 23, 30, tzinfo=DUBAI)  # Monday night
    answered = datetime(2026, 9, 22, 9, 2, tzinfo=DUBAI)
    assert open_seconds(asked, answered, settings=SHOWROOM, tz=DUBAI) == 120


def test_a_closed_day_counts_nothing() -> None:
    asked = datetime(2026, 9, 26, 20, 0, tzinfo=DUBAI)  # Saturday, an hour before closing
    answered = datetime(2026, 9, 28, 9, 30, tzinfo=DUBAI)  # Monday
    assert open_seconds(asked, answered, settings=SHOWROOM, tz=DUBAI) == 90 * 60


def test_a_team_without_hours_waited_the_whole_time() -> None:
    asked = datetime(2026, 9, 21, 23, 30, tzinfo=DUBAI)
    answered = datetime(2026, 9, 22, 9, 2, tzinfo=DUBAI)
    assert open_seconds(asked, answered, settings=SalesSettings(), tz=DUBAI) == 34_320


def test_an_answer_before_the_question_is_no_wait() -> None:
    moment = datetime(2026, 9, 21, 10, 0, tzinfo=DUBAI)
    assert open_seconds(moment, moment - timedelta(minutes=1), settings=SHOWROOM, tz=DUBAI) == 0
```

In `apps/api/tests/test_response_targets.py`:

```python
async def test_a_missed_target_leaves_one_row_that_outlives_its_notifications(…) -> None:
    # A conversation assigned to SALES_1, waiting past sla_due_at. on_sla_check at
    # level 'missed', twice → exactly one sla_misses row, assigned_to SALES_1 and
    # due_at == sla_due_at. Delete every notification: the row is still there.


async def test_an_answered_customer_leaves_no_miss(…) -> None:
    # waiting_since cleared before the check runs → no sla_misses row.
```

In `apps/api/tests/test_my_day.py`:

```python
def test_my_median_starts_at_the_customers_first_message() -> None:
    # One conversation answered today by SALES_1: inbound messages 31 and 1 minutes
    # before first_response_at. GET /v1/dashboard/me → median_first_response_seconds == 1860.


async def test_a_wait_is_counted_in_the_hours_we_are_open(db, su, seeded) -> None:
    # Fixed instants, so the test does not depend on the hour it runs at: business
    # hours 09:00–21:00 every day, a customer who wrote at 20:59 on 21 September and
    # was answered at 09:01 on the 22nd. numbers.answered() over the 22nd, Dubai time,
    # returns one Wait of 120 seconds, not twelve hours.
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/api && uv run pytest tests/test_sales_hours.py tests/test_response_targets.py tests/test_my_day.py -q`
Expected: FAIL — `open_seconds` cannot be imported; the median test reads 60 instead of 1860.

- [ ] **Step 3: A wait, in business hours**

Append to `apps/api/src/dealerai/sales/hours.py`:

```python
def open_seconds(start: datetime, end: datetime, *, settings: SalesSettings, tz: ZoneInfo) -> int:
    """How much of [start, end) the team was open: the wait a response target
    counts. A customer who wrote at 23:30 and was answered at 09:02 waited two
    minutes of the team's time, not nine and a half hours."""
    if end <= start:
        return 0
    if not settings.business_hours:
        return int((end - start).total_seconds())
    total = timedelta()
    cursor = start.astimezone(tz)
    stop = end.astimezone(tz)
    while cursor < stop:
        hours = _hours_for(cursor, settings)
        if hours is not None:
            opens = cursor.replace(
                hour=hours.open.hour, minute=hours.open.minute, second=0, microsecond=0
            )
            closes = cursor.replace(
                hour=hours.close.hour, minute=hours.close.minute, second=0, microsecond=0
            )
            counted_from, counted_to = max(cursor, opens), min(stop, closes)
            if counted_to > counted_from:
                total += counted_to - counted_from
        cursor = _next_midnight(cursor)
    return int(total.total_seconds())
```

- [ ] **Step 4: A miss writes its row**

In `apps/api/src/dealerai/events/handlers/inbox.py`, inside `on_sla_check`, after the
`started = …` line:

```python
        if level == "missed":
            # A fact of its own, not only somebody's notification: the
            # dashboard counts misses per day and per person, and a
            # notification is deleted after 90 days or with its reader.
            await conn.execute(
                """insert into sla_misses
                     (tenant_id, conversation_id, assigned_to, waiting_since, due_at)
                   values ($1, $2, $3, $4, coalesce($5, now()))
                   on conflict do nothing""",
                tenant_id,
                conversation_id,
                row["assigned_to"],
                row["waiting_since"],
                row["sla_due_at"],
            )
```

- [ ] **Step 5: One definition of a first response**

`apps/api/src/dealerai/db/queries/dashboard.py`:

```python
"""Every number the manager's dashboard and the morning brief show.

No visibility here, on purpose, as in queries/inbox.py: the caller's session
already decided which rows exist, so a manager's counts are her teams' because
Postgres shows her nothing else. A count that filtered by team itself would be
a second definition of "her teams" — the one that drifts.
"""

from __future__ import annotations

#: $1 since, $2 until. Every conversation first answered in the window: who
#: answered, when, and when the customer *first* wrote — somebody who wrote
#: at 10:00 and again at 10:30 had waited half an hour at 10:31, not a minute.
ANSWERED = """
select c.assigned_to, c.first_response_at as answered_at,
       (select min(m.created_at) from messages m
         where m.conversation_id = c.id and m.direction = 'in' and m.kind = 'message'
           and m.created_at <= c.first_response_at) as asked_at
  from conversations c
 where c.first_response_at >= $1 and c.first_response_at < $2
"""
```

`apps/api/src/dealerai/sales/dashboard.py`:

```python
"""The arithmetic behind the manager's dashboard, the morning brief and My day.

In one place because a number shown on two screens is a number that can
disagree with itself: My day's median and the dashboard's are this module's.
SQL counts rows (db/queries/dashboard.py); this turns them into waits, medians,
windows and a ranked list. It has no visibility of its own — the caller's
session already decided which rows exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ..db.queries import dashboard as q
from .hours import open_seconds
from .settings import SalesSettings


@dataclass(frozen=True, slots=True)
class Wait:
    """One first reply: who gave it, and how long the customer had waited, in business hours."""

    assigned_to: UUID | None
    seconds: int


def day_window(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Midnight to midnight where the showroom is."""
    start = datetime.combine(day, time(0), tzinfo=tz)
    return start, datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)


def month_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day.replace(day=1), time(0), tzinfo=tz)


async def answered(
    conn: Any, since: datetime, until: datetime, *, tz: ZoneInfo, settings: SalesSettings
) -> list[Wait]:
    """First replies given in the window, each wait counted in business hours
    because the target is."""
    return [
        Wait(
            row["assigned_to"],
            open_seconds(row["asked_at"], row["answered_at"], settings=settings, tz=tz),
        )
        for row in await conn.fetch(q.ANSWERED, since, until)
        if row["asked_at"] is not None  # we wrote first: nobody was waiting
    ]


def median_of(waits: list[Wait]) -> int | None:
    """Null rather than zero before anything was answered: a zero reads as instant."""
    return int(median(wait.seconds for wait in waits)) if waits else None
```

In `apps/api/src/dealerai/routes/dashboard.py`, delete `MEDIAN_FIRST_RESPONSE` and compute My day's
median through the shared definition:

```python
        tenant = await conn.fetchrow(
            "select timezone, sales_settings from tenants where id = $1", ctx.tenant_id
        )
        timezone = tenant["timezone"] or "UTC"
        midnight = day_start(timezone, now)
        …
        waits = await numbers.answered(
            conn,
            midnight,
            now,
            tz=zone(timezone),
            settings=SalesSettings.model_validate(tenant["sales_settings"] or {}),
        )
        …
            "median_first_response_seconds": numbers.median_of(
                [wait for wait in waits if wait.assigned_to == ctx.user.id]
            ),
```

with `from ..sales import dashboard as numbers`, `from ..sales.clock import zone` and
`from ..sales.settings import SalesSettings`.

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_sales_hours.py tests/test_response_targets.py tests/test_my_day.py -q`
Expected: PASS, the earlier My day tests included — with one inbound message and no business hours
the old and new definitions agree.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/dealerai/events/handlers/inbox.py apps/api/src/dealerai/sales/hours.py \
        apps/api/src/dealerai/db/queries/dashboard.py apps/api/src/dealerai/sales/dashboard.py \
        apps/api/src/dealerai/routes/dashboard.py apps/api/tests/test_sales_hours.py \
        apps/api/tests/test_response_targets.py apps/api/tests/test_my_day.py
git commit -m "fix(sales): a missed target is a row, and a wait starts at the first message, in business hours"
```

---

## Task 5: The numbers a morning is run on

**Files:**
- Modify: `apps/api/src/dealerai/db/queries/dashboard.py`
- Modify: `apps/api/src/dealerai/sales/dashboard.py`
- Modify: `apps/api/src/dealerai/routes/dashboard.py`
- Modify: `apps/api/src/dealerai/core/permissions.py`
- Create: `apps/api/tests/test_manager_dashboard.py`
- Modify: `apps/api/tests/test_permissions.py`

`GET /v1/dashboard/manager`, one request ([06](../06-api-contract.md) §7). The windowed counts are
the day shown (`?date=`, today by default, in the tenant's timezone); waiting, hot and overdue are
now; the brief is always today's.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_manager_dashboard.py` seeds a morning on the visibility people — Sara-like
`MANAGER` leads Local sales (`SALES_1`, `SALES_2`); `SALES_X` is Export:

```python
async def _morning() -> dict[str, uuid.UUID]:
    """Today, in Dubai: three new conversations (two Local, one Export); SALES_1
    answered one after four minutes; SALES_2 missed a target; one Local customer
    and the Export one still waiting past the target; a Local lead won today and
    an Export one lost; a hot Local lead with no task; two of SALES_2's tasks
    overdue; one reply typed on the phone.

    Starts from reseed_with_people() and deletes tenant A's fixture customer
    first, so every row the tiles count is one this test wrote."""
```

```python
def test_the_tiles_are_the_rows_behind_them() -> None:
    # OWNER: new_conversations 3, waiting_now 2, missed_targets 1, won 1, lost 1,
    # hot_leads 1, median_first_response_seconds 240, first_response_target_seconds 300.


def test_a_manager_counts_her_teams_and_nobody_elses() -> None:
    # MANAGER: new_conversations 2, waiting_now 1, lost 0 (the lost lead is Export's),
    # and the team rows are MANAGER, SALES_1 and SALES_2 — never SALES_X.


def test_a_miss_counts_against_whoever_had_the_customer() -> None:
    # The team row for SALES_2 has missed_targets 1; SALES_1's has 0.


def test_waiting_is_the_longest_wait_first() -> None:


def test_the_pipeline_counts_open_leads_per_stage() -> None:


def test_phone_replies_are_counted_apart_from_the_inbox() -> None:
    # phone_share.this_week == {"inbox": 1, "phone": 1}.


def test_a_date_counts_that_day() -> None:
    # ?date=<yesterday> → new_conversations 0; waiting_now is still 2.


def test_a_salesperson_is_refused_and_a_viewer_is_not() -> None:
    # SALES_1 → 403. A viewer membership → 200, the same tiles as OWNER.


def test_the_brief_puts_two_of_each_kind_of_trouble_first() -> None:
    waits = [{"kind": "waiting", "id": n} for n in range(4)]
    hot = [{"kind": "hot_lead", "id": n} for n in range(3)]
    overdue = [{"kind": "overdue_tasks", "id": 0}]
    assert [(i["kind"], i["id"]) for i in rank(waits, hot, overdue)] == [
        ("waiting", 0), ("waiting", 1), ("hot_lead", 0), ("hot_lead", 1), ("overdue_tasks", 0),
    ]


def test_the_brief_lists_what_needs_doing_now() -> None:
    # brief.items for OWNER: the waiting customers past target (kind 'waiting', the
    # customer's name, their assignee), the hot lead with no task (kind 'hot_lead'),
    # and SALES_2 with count 2 (kind 'overdue_tasks'). brief.headline is null: no brief yet.
```

In `apps/api/tests/test_permissions.py`, `test_a_viewer_may_do_nothing` becomes:

```python
def test_a_viewer_reads_the_dashboard_and_changes_nothing() -> None:
    """06 § 12: read-only everything, and the numbers are part of everything."""
    assert permissions_for("viewer") == frozenset({"dashboard.manager"})
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/api && uv run pytest tests/test_manager_dashboard.py tests/test_permissions.py -q`
Expected: FAIL — 404 on `/v1/dashboard/manager`.

- [ ] **Step 3: The queries**

Append to `apps/api/src/dealerai/db/queries/dashboard.py`:

```python
#: $1 since, $2 until (the day shown), $3 now. The windowed counts are that
#: day's; waiting, hot and overdue are the state of things now.
FACTS = """
select
  (select count(*) from conversations
    where created_at >= $1 and created_at < $2)                               as new_conversations,
  (select count(*) from conversations
    where status = 'open' and waiting_since is not null)                      as waiting_now,
  (select count(*) from conversations
    where status = 'open' and waiting_since is not null and sla_due_at < $3)  as waiting_past_target,
  (select count(*) from sla_misses where due_at >= $1 and due_at < $2)        as missed_targets,
  (select count(*) from leads where created_at >= $1 and created_at < $2)     as new_leads,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'open' and l.intent_band = 'hot')                      as hot_leads,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'open' and l.intent_band = 'hot'
      and not exists (select 1 from tasks t
                       where t.lead_id = l.id and t.status = 'open'))        as hot_without_next_step,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'won' and l.stage_entered_at >= $1
      and l.stage_entered_at < $2)                                            as won,
  (select count(*) from leads l join pipeline_stages s on s.id = l.stage_id
    where s.category = 'lost' and l.stage_entered_at >= $1
      and l.stage_entered_at < $2)                                            as lost,
  (select count(*) from tasks where status = 'open' and due_at < $3)          as overdue_tasks,
  (select count(*) from messages
    where direction = 'out' and kind = 'message' and origin in ('inbox', 'ai')
      and created_at >= $1 and created_at < $2)                               as replies_inbox,
  (select count(*) from messages
    where direction = 'out' and kind = 'message' and origin = 'phone_app'
      and created_at >= $1 and created_at < $2)                               as replies_phone
"""

#: $1 tenant, $2 since, $3 until, $4 now, $5 the month's start. The people a
#: manager manages: everyone in sales for an owner, her teams' members for her.
#: Memberships have no owner column, so this is the one query that names the
#: scope — through the same app.my_team_ids() the policies use.
TEAM = """
select m.user_id as id, p.full_name as name,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open')              as open,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open'
           and c.waiting_since is not null)                                   as waiting,
       (select count(*) from sla_misses s
         where s.assigned_to = m.user_id and s.due_at >= $2 and s.due_at < $3) as missed_targets,
       (select count(*) from tasks t
         where t.assignee_id = m.user_id and t.status = 'open' and t.due_at < $4) as overdue_tasks,
       coalesce(bands.hot, 0) as hot, coalesce(bands.warm, 0) as warm,
       coalesce(bands.cold, 0) as cold, coalesce(bands.won_this_month, 0) as won_this_month
  from memberships m
  left join profiles p on p.id = m.user_id
  left join lateral (
    select count(*) filter (where s.category = 'open' and l.intent_band = 'hot')  as hot,
           count(*) filter (where s.category = 'open' and l.intent_band = 'warm') as warm,
           count(*) filter (where s.category = 'open' and l.intent_band = 'cold') as cold,
           count(*) filter (where s.category = 'won' and l.stage_entered_at >= $5) as won_this_month
      from leads l join pipeline_stages s on s.id = l.stage_id
     where l.owner_id = m.user_id
  ) bands on true
 where m.tenant_id = $1 and m.role in ('sales', 'manager')
   and (current_setting('app.scope', true) = 'all'
        or exists (select 1 from team_members tm
                    where tm.user_id = m.user_id
                      and tm.team_id = any (coalesce((select app.my_team_ids()), '{}'))))
 order by p.full_name nulls last
"""

#: Open leads per stage, every board, in board order.
PIPELINE = """
select p.id as pipeline_id, p.name as pipeline_name, s.id as stage_id, s.name as stage_name,
       count(l.id) as leads
  from pipelines p
  join pipeline_stages s on s.pipeline_id = p.id and s.category = 'open'
  left join leads l on l.stage_id = s.id
 group by p.id, p.name, p.is_default, p.position, s.id, s.name, s.position
 order by p.is_default desc, p.position, s.position
"""

#: $1 since: where the last thirty days' leads came from.
SOURCES = """
select coalesce(source, 'unknown') as source, count(*) as leads
  from leads where created_at >= $1
 group by 1 order by 2 desc, 1
"""

#: $1 two weeks ago, $2 one week ago. Replies typed in the inbox against
#: replies typed on the phone (docs/sales/00-prd.md S8: rising week over week).
SHARE = """
select count(*) filter (where origin in ('inbox', 'ai') and created_at >= $2) as inbox_this_week,
       count(*) filter (where origin = 'phone_app' and created_at >= $2)      as phone_this_week,
       count(*) filter (where origin in ('inbox', 'ai') and created_at < $2)  as inbox_last_week,
       count(*) filter (where origin = 'phone_app' and created_at < $2)       as phone_last_week
  from messages
 where direction = 'out' and kind = 'message' and created_at >= $1
"""

#: The three kinds of trouble the brief lists, each shaped the same:
#: id, name, since, owner_id, owner_name, count.
#: $1 now, $2 limit: customers past their target, the longest wait first.
ATTENTION_WAITS = """
select c.id, ct.full_name as name, c.waiting_since as since,
       c.assigned_to as owner_id, p.full_name as owner_name, null::bigint as count
  from conversations c
  join contacts ct on ct.id = c.contact_id
  left join profiles p on p.id = c.assigned_to
 where c.status = 'open' and c.waiting_since is not null and c.sla_due_at < $1
 order by c.waiting_since
 limit $2
"""

#: $1 limit: hot, open, and nobody has anything to do about them.
ATTENTION_HOT = """
select l.id, ct.full_name as name, l.stage_entered_at as since,
       l.owner_id, p.full_name as owner_name, null::bigint as count
  from leads l
  join pipeline_stages s on s.id = l.stage_id and s.category = 'open'
  join contacts ct on ct.id = l.contact_id
  left join profiles p on p.id = l.owner_id
 where l.intent_band = 'hot'
   and not exists (select 1 from tasks t where t.lead_id = l.id and t.status = 'open')
 order by l.score desc nulls last, l.stage_entered_at
 limit $1
"""

#: $1 now, $2 limit: whoever has most tasks past due. Two or more — one late
#: task is a Tuesday.
ATTENTION_OVERDUE = """
select t.assignee_id as id, p.full_name as name, min(t.due_at) as since,
       null::uuid as owner_id, null::text as owner_name, count(*) as count
  from tasks t
  left join profiles p on p.id = t.assignee_id
 where t.status = 'open' and t.due_at < $1
 group by t.assignee_id, p.full_name
having count(*) >= 2
 order by count(*) desc, min(t.due_at)
 limit $2
"""
```

- [ ] **Step 4: The arithmetic**

Append to `apps/api/src/dealerai/sales/dashboard.py` (with `from pydantic import BaseModel`):

```python
#: How many things the brief puts in front of a manager.
BRIEF_ITEMS = 5


class Headline(BaseModel):
    """The brief's one line, in both UI languages. Both required: schema
    decoding guarantees required fields and nothing else."""

    en: str
    ar: str


async def facts(
    conn: Any,
    since: datetime,
    until: datetime,
    now: datetime,
    waits: list[Wait],
    settings: SalesSettings,
) -> dict[str, Any]:
    row = await conn.fetchrow(q.FACTS, since, until, now)
    return {
        **dict(row),
        "median_first_response_seconds": median_of(waits),
        "first_response_target_seconds": settings.first_response_target_min * 60,
    }


async def team(
    conn: Any,
    tenant_id: UUID,
    since: datetime,
    until: datetime,
    now: datetime,
    waits: list[Wait],
    month_from: datetime,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(q.TEAM, tenant_id, since, until, now, month_from)
    return [
        {
            **dict(row),
            "median_first_response_seconds": median_of(
                [wait for wait in waits if wait.assigned_to == row["id"]]
            ),
        }
        for row in rows
    ]


def rank(
    waits: list[dict[str, Any]],
    hot: list[dict[str, Any]],
    overdue: list[dict[str, Any]],
    limit: int = BRIEF_ITEMS,
) -> list[dict[str, Any]]:
    """Two of each kind first, so a busy inbox cannot hide a hot lead nobody is
    working; then the rest, the most urgent kind first."""
    first = [*waits[:2], *hot[:2], *overdue[:1]]
    rest = [*waits[2:], *hot[2:], *overdue[1:]]
    return (first + rest)[:limit]


async def attention(conn: Any, now: datetime) -> list[dict[str, Any]]:
    """What needs somebody now, ranked — the brief's items, live rather than
    stored, so an item somebody already handled is gone when they look."""
    waits = [
        {"kind": "waiting", **dict(row)}
        for row in await conn.fetch(q.ATTENTION_WAITS, now, BRIEF_ITEMS)
    ]
    hot = [{"kind": "hot_lead", **dict(row)} for row in await conn.fetch(q.ATTENTION_HOT, BRIEF_ITEMS)]
    overdue = [
        {"kind": "overdue_tasks", **dict(row)}
        for row in await conn.fetch(q.ATTENTION_OVERDUE, now, BRIEF_ITEMS)
    ]
    return rank(waits, hot, overdue)
```

- [ ] **Step 5: The route**

In `apps/api/src/dealerai/routes/dashboard.py` (imports: `date`, `timedelta`, `Annotated`, `Literal`,
`UUID`, `Depends`, `Query`, `TenantContext`, `require_permission`, `db.queries.dashboard as q`,
`UserRef` from `.inbox`, `Headline` from `..sales.dashboard`):

```python
Manager = Annotated[TenantContext, Depends(require_permission("dashboard.manager"))]

#: Waiting conversations returned: the list shows the first few, and the team
#: table's per-person view filters the same list rather than asking again.
WAITING_READ = 50


class Tiles(BaseModel):
    new_conversations: int
    waiting_now: int
    median_first_response_seconds: int | None
    first_response_target_seconds: int
    missed_targets: int
    new_leads: int
    hot_leads: int
    won: int
    lost: int


class RepRow(BaseModel):
    user: UserRef
    open: int
    waiting: int
    median_first_response_seconds: int | None
    missed_targets: int
    overdue_tasks: int
    hot: int
    warm: int
    cold: int
    won_this_month: int


class StageTotal(BaseModel):
    pipeline_id: UUID
    pipeline_name: str
    stage_id: UUID
    stage_name: str
    leads: int


class SourceCount(BaseModel):
    source: str
    leads: int


class Share(BaseModel):
    inbox: int
    phone: int


class PhoneShare(BaseModel):
    this_week: Share
    last_week: Share


class AttentionItem(BaseModel):
    kind: Literal["waiting", "hot_lead", "overdue_tasks"]
    #: The conversation, the lead, or the salesperson.
    id: UUID
    #: The customer — or, for overdue_tasks, the salesperson.
    name: str | None
    owner: UserRef | None
    since: datetime | None
    count: int | None


class Brief(BaseModel):
    date: date
    headline: Headline | None
    items: list[AttentionItem]


class ManagerDashboard(BaseModel):
    date: date
    tiles: Tiles
    waiting: list[ConversationSummary]
    team: list[RepRow]
    pipeline: list[StageTotal]
    sources: list[SourceCount]
    phone_share: PhoneShare
    brief: Brief


def _person(user_id: UUID | None, name: str | None) -> dict[str, Any] | None:
    return None if user_id is None else {"id": user_id, "name": name}


@router.get("/manager", response_model=ManagerDashboard)
async def manager_dashboard(
    ctx: Manager, day: Annotated[date | None, Query(alias="date")] = None
) -> dict[str, Any]:
    """A manager's morning in one request, because it is one screen refreshed
    together (docs/sales/06-api-contract.md § 7).

    Every number reads through the caller's own visibility — her teams'
    numbers because Postgres shows her nothing else. `date` moves the counted
    day; waiting, hot and overdue are always now; the brief is always today's.
    """
    now = datetime.now(UTC)
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        tenant = await conn.fetchrow(
            "select timezone, sales_settings from tenants where id = $1", ctx.tenant_id
        )
        tz = zone(tenant["timezone"])
        settings = SalesSettings.model_validate(tenant["sales_settings"] or {})
        today = now.astimezone(tz).date()
        shown = day or today
        since, until = numbers.day_window(shown, tz)
        waits = await numbers.answered(conn, since, until, tz=tz, settings=settings)
        facts = await numbers.facts(conn, since, until, now, waits, settings)
        team = await numbers.team(
            conn, ctx.tenant_id, since, until, now, waits, numbers.month_start(shown, tz)
        )
        rows = await conn.fetch(
            list_sql("all" if ctx.scope == "all" else "team", with_cursor=False),
            ctx.user.id,
            "open",
            "",
            "",
            WAITING_READ,
        )
        pipeline = await conn.fetch(q.PIPELINE)
        sources = await conn.fetch(q.SOURCES, now - timedelta(days=30))
        share = await conn.fetchrow(q.SHARE, now - timedelta(days=14), now - timedelta(days=7))
        items = await numbers.attention(conn, now)
        headline = await conn.fetchval(
            "select headline from sales_briefs where user_id = $1 and brief_date = $2",
            ctx.user.id,
            today,
        )
    return {
        "date": shown,
        "tiles": {key: facts[key] for key in Tiles.model_fields},
        "waiting": [summary(row, now) for row in rows if row["waiting_since"] is not None],
        "team": [
            {
                "user": _person(rep["id"], rep["name"]),
                **{key: rep[key] for key in RepRow.model_fields if key != "user"},
            }
            for rep in team
        ],
        "pipeline": [dict(row) for row in pipeline],
        "sources": [dict(row) for row in sources],
        "phone_share": {
            "this_week": {"inbox": share["inbox_this_week"], "phone": share["phone_this_week"]},
            "last_week": {"inbox": share["inbox_last_week"], "phone": share["phone_last_week"]},
        },
        "brief": {
            "date": today,
            "headline": headline,
            "items": [
                {
                    "kind": item["kind"],
                    "id": item["id"],
                    "name": item["name"],
                    "owner": _person(item["owner_id"], item["owner_name"]),
                    "since": item["since"],
                    "count": item["count"],
                }
                for item in items
            ],
        },
    }
```

- [ ] **Step 6: A viewer reads the numbers**

In `apps/api/src/dealerai/core/permissions.py`:

```python
    #: Read-only everything, and the numbers are part of everything
    #: (docs/sales/06-api-contract.md § 12). Every write on the dashboard needs
    #: a permission of its own, so this lets a viewer look and nothing more.
    "viewer": frozenset({"dashboard.manager"}),
```

- [ ] **Step 7: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_manager_dashboard.py tests/test_permissions.py tests/test_my_day.py tests/test_visibility.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/dealerai/db/queries/dashboard.py apps/api/src/dealerai/sales/dashboard.py \
        apps/api/src/dealerai/routes/dashboard.py apps/api/src/dealerai/core/permissions.py \
        apps/api/tests/test_manager_dashboard.py apps/api/tests/test_permissions.py
git commit -m "feat(sales): the manager dashboard, one request over the caller's own rows"
```

---
## Task 6: The morning brief

**Files:**
- Create: `apps/api/src/dealerai/guards/facts.py`, `apps/api/tests/guards/test_facts.py`
- Create: `apps/api/src/dealerai/ai/prompts/brief.md`
- Create: `apps/api/src/dealerai/agents/sales/brief.py`
- Modify: `apps/api/src/dealerai/db/queries/dashboard.py`, `apps/api/src/dealerai/sales/dashboard.py`
- Create: `apps/api/src/dealerai/events/handlers/manager.py`
- Modify: `apps/api/src/dealerai/events/handlers/__init__.py`, `apps/api/src/dealerai/events/handlers/notify.py`
- Create: `apps/api/tests/test_brief.py`, `apps/api/tests/evals/test_brief_live.py`
- Modify: `package.json` (`eval:brief`)

[05](../05-workflows.md) §13 has the brief agent write "the headline and up to five items". This
plan narrows that on purpose. The five items are rows — the SQL already chose and ranked them — and
the screen renders rows in the reader's own language, Arabic or English, with links that cannot point
at the wrong customer. What a model adds is one line of prose over the numbers, so that is all it
writes, in both UI languages, and a guard refuses the line if it contains a number the facts did not.
The model is never shown a customer's name, so no brief row can outlive an erasure.

- [ ] **Step 1: The guard, test first**

`apps/api/tests/guards/test_facts.py` — this directory runs under `npm run test:guards` at 100%
branch coverage:

```python
from dealerai.guards import facts

FACTS = "- new conversations: 23\n- first reply, median: 4 min (the target is 5 min)\n- won: 1,200"


def test_numbers_the_facts_hold_pass() -> None:
    assert facts.check("23 new conversations and a 4 min median", facts=FACTS) == []


def test_a_number_the_facts_do_not_hold_is_named() -> None:
    [finding] = facts.check("37 new conversations yesterday", facts=FACTS)
    assert (finding.guard, finding.detail) == ("facts", "37")


def test_arabic_digits_are_the_numbers_they_are() -> None:
    assert facts.check("٢٣ محادثة جديدة", facts=FACTS) == []


def test_a_thousands_separator_is_not_a_new_number() -> None:
    assert facts.check("1200 won", facts=FACTS) == []


def test_a_line_without_numbers_passes() -> None:
    assert facts.check("A quiet day.", facts=FACTS) == []
```

`apps/api/src/dealerai/guards/facts.py`:

```python
"""Every number in a line written from facts is one of the facts.

The morning brief hands a model a block of numbers and asks for one line about
them. The way that line goes wrong is a number the block does not hold: a
rounded median, a total nobody counted, a percentage worked out in the model's
head. So the rule is the price guard's without the currency — every figure in
the text must appear in the facts, or the line is not shown.
"""

from __future__ import annotations

import re

from ..core.text import ascii_digits
from . import Finding, Findings

GUARD = "facts"

#: 1,200 and 1200 are one number; 4.5 stays 4.5. ascii_digits has already
#: turned ٢٣ into 23 and the Arabic separators into their ASCII selves.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[str]:
    return {match.replace(",", "") for match in _NUMBER.findall(ascii_digits(text))}


def check(text: str, *, facts: str) -> Findings:
    unknown = numbers_in(text) - numbers_in(facts)
    return [
        Finding(guard=GUARD, message="a number that is not in the facts", detail=number)
        for number in sorted(unknown)
    ]
```

Run: `npm run test:guards` — Expected: PASS at 100%.

- [ ] **Step 2: What the model reads**

Append to `apps/api/src/dealerai/db/queries/dashboard.py`:

```python
#: $1 since, $2 until: the cars the copilot's drafts were built on most often —
#: the chips _sources() writes (events/handlers/copilot.py).
MOST_ASKED = """
select source->>'label' as car, count(*) as times
  from ai_suggestions s
  cross join lateral jsonb_array_elements(s.sources) source
 where s.created_at >= $1 and s.created_at < $2 and source->>'kind' = 'vehicle'
 group by 1
 order by 2 desc, 1
 limit 3
"""
```

Append to `apps/api/src/dealerai/sales/dashboard.py`:

```python
async def most_asked(conn: Any, since: datetime, until: datetime) -> list[tuple[str, int]]:
    return [(row["car"], row["times"]) for row in await conn.fetch(q.MOST_ASKED, since, until)]


def render_facts(
    day: date,
    facts: dict[str, Any],
    team: list[dict[str, Any]],
    cars: list[tuple[str, int]],
) -> str:
    """The brief's facts as the headline's model reads them, and as
    guards/facts.py checks the headline against — so every number it may use
    is here in the form it may use it: minutes rather than seconds, a share
    already worked out. Salespeople are named; no customer is."""

    def minutes(seconds: int | None) -> str:
        return "nothing answered" if seconds is None else f"{round(seconds / 60)} min"

    replies = facts["replies_inbox"] + facts["replies_phone"]
    lines = [
        f"## Yesterday, {day:%A} {day.day} {day:%B}",
        f"- new conversations: {facts['new_conversations']}",
        f"- first reply, median: {minutes(facts['median_first_response_seconds'])}"
        f" (the target is {minutes(facts['first_response_target_seconds'])})",
        f"- replies that missed the target: {facts['missed_targets']}",
        f"- new leads: {facts['new_leads']}; won: {facts['won']}; lost: {facts['lost']}",
    ]
    if replies:
        lines.append(
            f"- replies from the inbox: {facts['replies_inbox']} of {replies}"
            f" ({round(100 * facts['replies_inbox'] / replies)}%);"
            f" typed on the phone: {facts['replies_phone']}"
        )
    if cars:
        lines.append(
            "- cars asked about most: " + ", ".join(f"{car} ({times})" for car, times in cars)
        )
    lines += [
        "",
        "## This morning",
        f"- customers waiting: {facts['waiting_now']};"
        f" past the target: {facts['waiting_past_target']}",
        f"- hot leads with no next step: {facts['hot_without_next_step']}",
        f"- open tasks past their due time: {facts['overdue_tasks']}",
    ]
    if team:
        lines += ["", "## By salesperson"]
        lines += [
            f"- {rep['name'] or 'unnamed'}: first reply median"
            f" {minutes(rep['median_first_response_seconds'])}, missed {rep['missed_targets']},"
            f" tasks past due {rep['overdue_tasks']}, won this month {rep['won_this_month']}"
            for rep in team
        ]
    return "\n".join(lines)
```

- [ ] **Step 3: The prompt**

`apps/api/src/dealerai/ai/prompts/brief.md`:

```markdown
<!--
The morning brief's headline (docs/sales/05-workflows.md § 13). Everything
under it is rows the screen shows; this is the one line above them. Checked by
guards/facts.py: a number that is not in the facts stops the line.
-->

## What you are for

You write the first line a sales manager at a car dealership reads in the
morning: one sentence, two at most, saying what yesterday was and what needs
them first today. The customers and tasks themselves are listed under your
line — do not repeat the list; point at what matters in it.

## The rules

- Use only the numbers in the facts, written exactly as they are there. Do not
  add them up, round them, or work out a percentage the facts do not already
  give. A number that is not in the facts stops your line from being shown.
- Name salespeople only as the facts name them; in Arabic you may write a name
  in Arabic letters. There are no customers' names in the facts, and you never
  write one.
- Lead with what needs doing: customers past the target, a hot lead with no
  next step, a salesperson with tasks past due. If nothing does, say what went
  well.
- Plain words. No greeting, no sign-off, no emoji, no markdown.
- At most 160 characters in each language.

## Two languages

Write the same line twice: `en` in English, `ar` in Arabic — Modern Standard
Arabic a Gulf manager reads comfortably, numbers in Western digits exactly as
they appear in the facts.

## Example

Facts (shortened): new conversations: 23 · first reply, median: 4 min (the
target is 5 min) · customers waiting: 3; past the target: 2 · Salem Bousaid:
tasks past due 4.

en: 23 new conversations and a 4 min median yesterday; 2 customers are past the target now, and Salem Bousaid has 4 tasks past due.
ar: 23 محادثة جديدة أمس ومتوسط أول رد 4 دقائق؛ عميلان تجاوزا الهدف الآن، ولدى سالم بوسعيد 4 مهام متأخرة.
```

- [ ] **Step 4: The agent**

`apps/api/src/dealerai/agents/sales/brief.py`:

```python
"""One line for a manager's morning.

The rest of the brief is rows the screen renders in the reader's own language
(sales/dashboard.attention). This writes the only part that is prose — a
headline in both UI languages — from a block of numbers that names no
customer, so it cannot write one into a row that outlives them.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from ...ai.gateway import ModelOutputInvalid, SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...sales.dashboard import Headline

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class Written:
    headline: Headline | None
    cost_usd: float


async def write(*, tenant_id: UUID, run_id: UUID, facts: str) -> Written:
    """No `_rules`: they are the rules for writing to a customer ("never reveal
    internal figures"), and this line is nothing but internal figures, for the
    manager they belong to."""
    try:
        result = await complete(
            TaskKind.ANALYSIS,
            tenant_id=tenant_id,
            system=SystemLayers(role=load("brief")),
            messages=f"{facts}\n\nWrite the headline.",
            output_schema=Headline,
            run_id=run_id,
            trace_name="brief",
        )
    except ModelOutputInvalid:
        # One unusable attempt, as with a draft: the brief goes out without a
        # headline rather than failing the morning.
        log.warning("brief_unparseable")
        return Written(headline=None, cost_usd=0.0)
    headline = result.parsed if isinstance(result.parsed, Headline) else None
    return Written(headline=headline, cost_usd=result.cost_usd)
```

- [ ] **Step 5: Write the handler's tests**

`apps/api/tests/test_brief.py` stubs the agent — the suite never spends money — with a fake that
records the facts it was shown:

```python
class FakeBrief:
    def __init__(self, en: str = "23 new conversations yesterday.",
                 raises: Exception | None = None) -> None:
        self.en, self.raises, self.shown = en, raises, []

    async def write(self, *, tenant_id: UUID, run_id: UUID, facts: str) -> Written:
        self.shown.append(facts)
        if self.raises:
            raise self.raises
        return Written(Headline(en=self.en, ar="٢٣ محادثة جديدة أمس."), 0.001)
```

```python
async def test_every_reader_gets_a_brief_of_their_own(…) -> None:
    # visibility_seed plus yesterday's activity. After on_brief_due: one sales_briefs
    # row each for OWNER and MANAGER, none for SALES_1, SALES_2 or SALES_X.


async def test_a_managers_brief_counts_only_her_teams(…) -> None:
    # MANAGER's stored facts count the Local conversations; OWNER's count every team.


async def test_the_model_is_never_shown_a_customers_name(…) -> None:
    # No seeded customer's name in any of fake.shown; "sales1" (a rep) is in them.


async def test_a_retried_brief_writes_nobody_twice(…) -> None:
    # on_brief_due twice: still one row and one 'brief_ready' notification per reader.


async def test_a_headline_with_a_number_it_was_not_given_is_not_shown(…) -> None:
    # FakeBrief(en="37 new conversations") → the brief row exists, headline null;
    # the notification's body is null.


async def test_a_quiet_day_costs_nothing(…) -> None:
    # No conversations, nobody waiting, nothing overdue: fake.shown is empty and the
    # brief row exists with a null headline.


async def test_no_budget_means_no_headline_rather_than_no_brief(…) -> None:
    # FakeBrief(raises=BudgetExceeded("…")) → rows written, the event does not fail.


async def test_the_dashboard_shows_the_readers_brief(…) -> None:
    # After on_brief_due for today, GET /v1/dashboard/manager as MANAGER →
    # brief.headline == {"en": "23 new conversations yesterday.", "ar": "٢٣ محادثة جديدة أمس."}.


async def test_a_brief_notification_opens_the_dashboard(…) -> None:
    # The 'brief_ready' notification's href is '/dashboard'.
```

Run: `cd apps/api && uv run pytest tests/test_brief.py -q` — Expected: FAIL, no handler.

- [ ] **Step 6: The handler**

`apps/api/src/dealerai/events/handlers/manager.py`:

```python
"""The morning brief (docs/sales/05-workflows.md § 13).

One per reader, each gathered in that reader's own session: a manager's brief
is her teams' numbers because the session shows her nothing else, exactly as
her dashboard is. Idempotent per reader and day, so a retried event writes
nobody's twice.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog

from ...agents.sales import brief as brief_agent
from ...core.errors import BudgetExceeded
from ...core.permissions import permissions_for, scope_for
from ...db.session import tenant_session
from ...guards import facts as facts_guard
from ...sales import dashboard
from ...sales.clock import zone
from ...sales.runs import agent_run
from ...sales.settings import SalesSettings
from ..bus import Event, handler
from .notify import notify

log = structlog.get_logger()


@handler("sales.brief_due")
async def on_brief_due(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("sales.brief_due requires a tenant")
    tenant_id = event.tenant_id
    day = date.fromisoformat(str(event.payload["date"]))
    async with tenant_session(tenant_id) as conn:
        tenant = await conn.fetchrow(
            "select timezone, sales_settings from tenants where id = $1", tenant_id
        )
        members = await conn.fetch(
            "select user_id, role from memberships where tenant_id = $1", tenant_id
        )
    if tenant is None:
        return
    tz = zone(tenant["timezone"])
    settings = SalesSettings.model_validate(tenant["sales_settings"] or {})
    for member in members:
        if "dashboard.manager" in permissions_for(member["role"]):
            await _brief(tenant_id, member["user_id"], scope_for(member["role"]), day, tz, settings)


async def _brief(
    tenant_id: UUID,
    user_id: UUID,
    scope: str,
    day: date,
    tz: ZoneInfo,
    settings: SalesSettings,
) -> None:
    now = datetime.now(UTC)
    yesterday = day - timedelta(days=1)
    since, until = dashboard.day_window(yesterday, tz)
    async with tenant_session(tenant_id, user_id=user_id, scope=scope) as conn:
        if await conn.fetchval(
            "select exists (select 1 from sales_briefs where user_id = $1 and brief_date = $2)",
            user_id,
            day,
        ):
            return
        waits = await dashboard.answered(conn, since, until, tz=tz, settings=settings)
        facts = await dashboard.facts(conn, since, until, now, waits, settings)
        team = await dashboard.team(
            conn, tenant_id, since, until, now, waits, dashboard.month_start(yesterday, tz)
        )
        cars = await dashboard.most_asked(conn, since, until)

    block = dashboard.render_facts(yesterday, facts, team, cars)
    headline = await _headline(tenant_id, user_id, day, facts, block)

    async with tenant_session(tenant_id, user_id=user_id, scope=scope) as conn:
        brief_id = await conn.fetchval(
            """insert into sales_briefs (tenant_id, user_id, brief_date, headline, facts)
               values ($1, $2, $3, $4, $5)
               on conflict do nothing returning id""",
            tenant_id,
            user_id,
            day,
            headline,
            facts,
        )
        if brief_id is not None:
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind="brief_ready",
                title="Your morning brief",
                body=headline["en"] if headline else None,
                entity={"type": "brief", "id": str(brief_id)},
                dedupe_key=f"brief:{day}",
            )


async def _headline(
    tenant_id: UUID, user_id: UUID, day: date, facts: dict[str, Any], block: str
) -> dict[str, str] | None:
    """None when there is nothing to say, no budget left, or a line the guard refused."""
    if not (facts["new_conversations"] or facts["waiting_now"] or facts["overdue_tasks"]):
        return None  # a quiet day is not worth a model call
    try:
        async with agent_run(
            tenant_id, goal="brief", goal_input={"user_id": str(user_id), "date": day.isoformat()}
        ) as run:
            written = await brief_agent.write(tenant_id=tenant_id, run_id=run.id, facts=block)
            run.cost_usd += written.cost_usd
    except BudgetExceeded:
        log.warning("brief_without_headline_budget", tenant_id=str(tenant_id))
        return None
    if written.headline is None:
        return None
    refused = facts_guard.check(f"{written.headline.en}\n{written.headline.ar}", facts=block)
    if refused:
        log.warning("brief_headline_refused", numbers=[finding.detail for finding in refused])
        return None
    return written.headline.model_dump()
```

Add `manager` to `events/handlers/__init__.py`, and in `events/handlers/notify.py` teach `_HREFS`
where a brief goes:

```python
    "brief": "/dashboard",
```

- [ ] **Step 7: The live check**

The suite fakes the model, and a fake always obeys the guard.
`apps/api/tests/evals/test_brief_live.py` (marked `eval`, about $0.002) renders three mornings
through `render_facts` — a busy one, a quiet one, and one where Salem is slipping — and asserts, for
each: a headline came back; both languages are non-empty; the Arabic line contains Arabic letters;
`facts.check(en + ar, facts=block) == []`; and neither line is over 200 characters. Add to the root
`package.json`:

```json
"eval:brief": "cd apps/api && uv run pytest tests/evals/test_brief_live.py -m eval -v -s"
```

- [ ] **Step 8: Run everything this touched**

Run: `cd apps/api && uv run pytest tests/test_brief.py tests/test_manager_dashboard.py tests/test_import_contracts.py -q && cd ../.. && npm run test:guards && npm run eval:brief`
Expected: PASS; the live run prints three headline pairs worth reading, not only passing.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/dealerai/guards/facts.py apps/api/tests/guards/test_facts.py \
        apps/api/src/dealerai/ai/prompts/brief.md apps/api/src/dealerai/agents/sales/brief.py \
        apps/api/src/dealerai/db/queries/dashboard.py apps/api/src/dealerai/sales/dashboard.py \
        apps/api/src/dealerai/events/handlers/manager.py \
        apps/api/src/dealerai/events/handlers/__init__.py \
        apps/api/src/dealerai/events/handlers/notify.py apps/api/tests/test_brief.py \
        apps/api/tests/evals/test_brief_live.py package.json
git commit -m "feat(ai): the morning brief — rows for the screen, one guarded headline"
```

---

## Task 7: Settings over HTTP

**Files:**
- Create: `apps/api/src/dealerai/routes/settings.py`
- Modify: `apps/api/src/dealerai/sales/settings.py`, `apps/api/src/dealerai/agents/sales/copilot.py`
- Modify: `apps/api/src/dealerai/routes/team.py`, `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_settings_api.py`
- Modify: `apps/api/tests/test_me_and_team.py`, `apps/api/tests/test_copilot_agent.py`

One jsonb column, many writers. [06](../06-api-contract.md) §12 splits them: a manager may move
opening hours and routing; only an owner or admin may switch the AI off or change how long customers
are kept. That split is a table in the route, and every write is validated whole by `SalesSettings`,
so nothing can store a shape its readers — including the RLS policy that reads
`unassigned_visible_to_sales` — cannot parse.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_settings_api.py` (route tests on `reseed_with_people`, as in `test_my_day.py`):

```python
def test_everyone_reads_the_settings_with_the_defaults_filled_in() -> None:
    # SALES_1 GET /v1/settings/sales → 200, first_response_target_min 5,
    # drafts_enabled true, arabic_register 'mirror', retention_months 24.


def test_a_manager_moves_the_opening_hours() -> None:
    # MANAGER PATCH {"business_hours": {"mon": {"open": "09:00", "close": "21:00"}}}
    # → 200, and a second GET returns the same hours.


def test_a_manager_may_not_switch_the_ai_off() -> None:
    # MANAGER PATCH {"drafts_enabled": false} → 403 naming settings.ai; unchanged after.


def test_a_salesperson_changes_nothing() -> None:


def test_absent_leaves_the_default_team_and_null_clears_it() -> None:


def test_routing_to_a_team_that_does_not_exist_is_refused() -> None:
    # 422 "routing names a team that does not exist".


def test_hours_that_close_before_they_open_are_refused_by_field() -> None:
    # 400 invalid-request with errors[0].field == "business_hours.mon.close" — the
    # screen checks this before saving; the API is the backstop.


def test_a_key_nobody_may_write_is_refused() -> None:
    # {"scoring_weights": {"visit": 50}} → 400, field "scoring_weights": no screen,
    # set by hand (04 § 5).


def test_a_key_a_newer_version_wrote_survives_a_save() -> None:
    # sales_settings seeded with {"future_key": 1}; after a PATCH it is still there.


def test_acceptance_is_by_intent_and_counts_light_edits() -> None:
    # Suggestions for 'price': sent, edited 0.1, edited 0.5, discarded. OWNER GET
    # /v1/settings/ai/acceptance → by_intent[0] == {intent 'price', decided 4, sent 1,
    # lightly_edited 1, rewritten 1, discarded 1, rate 0.5}; overall the same.


def test_acceptance_is_an_owners_question() -> None:
    # MANAGER → 403.
```

In `apps/api/tests/test_me_and_team.py`:

```python
def test_a_team_can_be_renamed() -> None:


def test_a_team_routing_still_sends_customers_to_cannot_be_deleted() -> None:
    # TEAM_EXPORT named in a routing rule → DELETE 409, with a sentence saying so.


def test_deleting_a_team_keeps_its_people_and_its_customers() -> None:
    # Members stay members; the team's customers keep their owners, team_id null.
```

In `apps/api/tests/test_copilot_agent.py`:

```python
def test_a_dealership_that_wants_gulf_arabic_says_so_in_the_prompt() -> None:
    # _tenant_layer with arabic_register 'gulf' contains "Gulf register"; 'mirror' does not.
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/api && uv run pytest tests/test_settings_api.py tests/test_me_and_team.py tests/test_copilot_agent.py -q`
Expected: FAIL — 404 on `/v1/settings/sales`.

- [ ] **Step 3: The register**

In `apps/api/src/dealerai/sales/settings.py`:

```python
#: docs/sales/00-prd.md Q3. `mirror` answers a Gulf customer in Gulf Arabic and
#: an Egyptian one in Egyptian; `gulf` answers everybody in one polite Gulf
#: register, for a dealership that wants one house voice.
ArabicRegister = Literal["mirror", "gulf"]
```

and on `SalesSettings`:

```python
    arabic_register: ArabicRegister = "mirror"
```

In `agents/sales/copilot.py`, `_tenant_layer`, before the currency line:

```python
    if ground.settings.arabic_register == "gulf":
        lines.append(
            "Write Arabic in a polite Gulf register, whatever dialect the customer writes in."
        )
```

- [ ] **Step 4: The routes**

`apps/api/src/dealerai/routes/settings.py`:

```python
"""The dealership's sales settings, read by everyone, changed by the right person.

One jsonb column (tenants.sales_settings), validated whole by SalesSettings on
every write, so nothing can store a shape its readers cannot parse — and one of
those readers is an RLS policy. Which key needs which permission is the table
below (docs/sales/06-api-contract.md § 12).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.errors import Forbidden, Unusable
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..sales.settings import ArabicRegister, OpenHours, RoutingRule, SalesSettings, Weekday

router = APIRouter(prefix="/v1/settings", tags=["settings"])

AiAdmin = Annotated[TenantContext, Depends(require_permission("settings.ai"))]

#: key → the permission that may change it. A key missing here cannot be
#: written at all: scoring weights have no screen in Phase 1 and are set by
#: hand (docs/sales/04-ai-copilot.md § 5).
WRITERS: dict[str, str] = {
    "first_response_target_min": "settings.routing",
    "unassigned_visible_to_sales": "settings.routing",
    "default_team_id": "settings.routing",
    "business_hours": "settings.routing",
    "routing_rules": "settings.routing",
    "drafts_enabled": "settings.ai",
    "follow_up_cadence_days": "settings.ai",
    "arabic_register": "settings.ai",
    "retention_months": "settings.team",
}


class SalesSettingsPatch(BaseModel):
    """Absent means unchanged; null clears the default team."""

    model_config = ConfigDict(extra="forbid")

    first_response_target_min: int | None = Field(default=None, ge=1, le=24 * 60)
    unassigned_visible_to_sales: bool | None = None
    default_team_id: UUID | None = None
    business_hours: dict[Weekday, OpenHours] | None = None
    routing_rules: list[RoutingRule] | None = Field(default=None, max_length=50)
    drafts_enabled: bool | None = None
    #: At most five follow-ups, each within three months of the one before.
    follow_up_cadence_days: list[Annotated[int, Field(ge=1, le=90)]] | None = Field(
        default=None, max_length=5
    )
    arabic_register: ArabicRegister | None = None
    retention_months: int | None = Field(default=None, ge=1, le=120)


class IntentAcceptance(BaseModel):
    intent: str | None
    decided: int
    sent: int
    lightly_edited: int
    rewritten: int
    discarded: int
    #: (sent + lightly edited) / decided — docs/sales/04-ai-copilot.md § 3.
    #: Null before anything was decided.
    rate: float | None


class Acceptance(BaseModel):
    days: int
    overall: IntentAcceptance
    by_intent: list[IntentAcceptance]


ACCEPTANCE = """
select intent, sum(decided)::int as decided, sum(sent)::int as sent,
       sum(lightly_edited)::int as lightly_edited, sum(rewritten)::int as rewritten,
       sum(discarded)::int as discarded
  from v_suggestion_acceptance
 where day >= $1
 group by intent
 order by sum(decided) desc, intent nulls last
"""


def _with_rate(row: dict[str, Any]) -> dict[str, Any]:
    decided = row["decided"]
    rate = (row["sent"] + row["lightly_edited"]) / decided if decided else None
    return {**row, "rate": rate}


@router.get("/sales", response_model=SalesSettings)
async def read_sales_settings(ctx: Ctx) -> SalesSettings:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        raw = await conn.fetchval("select sales_settings from tenants where id = $1", ctx.tenant_id)
    return SalesSettings.model_validate(raw or {})


@router.patch("/sales", response_model=SalesSettings)
async def change_sales_settings(ctx: Ctx, patch: SalesSettingsPatch) -> SalesSettings:
    changes = patch.model_dump(exclude_unset=True, mode="json")
    refused = sorted({WRITERS[key] for key in changes if not ctx.may(WRITERS[key])})
    if refused:
        raise Forbidden(f"changing these settings requires {' and '.join(refused)}")
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        raw = dict(
            await conn.fetchval(
                "select sales_settings from tenants where id = $1 for update", ctx.tenant_id
            )
            or {}
        )
        current = SalesSettings.model_validate(raw).model_dump(mode="json")
        try:
            merged = SalesSettings.model_validate({**current, **changes})
        except ValidationError as exc:
            raise Unusable(str(exc.errors()[0]["msg"])) from exc
        teams = {merged.default_team_id, *(rule.team_id for rule in merged.routing_rules)} - {None}
        if teams:
            known = await conn.fetchval(
                "select count(*) from teams where id = any($1::uuid[])", list(teams)
            )
            if known != len(teams):
                raise Unusable("routing names a team that does not exist")
        # Onto the raw column, so a key a newer deploy wrote survives an older one's save.
        await conn.execute(
            "update tenants set sales_settings = $2::jsonb where id = $1",
            ctx.tenant_id,
            {**raw, **merged.model_dump(mode="json")},
        )
    return merged


@router.get("/ai/acceptance", response_model=Acceptance)
async def acceptance(
    ctx: AiAdmin, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> dict[str, Any]:
    """How the drafts fared, by intent — the number the pilot's S5 criterion
    and the autopilot trigger are both read from."""
    since = (datetime.now(UTC) - timedelta(days=days)).date()
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = [dict(row) for row in await conn.fetch(ACCEPTANCE, since)]
    keys = ("decided", "sent", "lightly_edited", "rewritten", "discarded")
    overall = {"intent": None, **{key: sum(row[key] for row in rows) for key in keys}}
    return {
        "days": days,
        "overall": _with_rate(overall),
        "by_intent": [_with_rate(row) for row in rows],
    }
```

Register `settings.router` in `main.py`.

- [ ] **Step 5: A team can be renamed, and deleted once nothing routes to it**

In `apps/api/src/dealerai/routes/team.py` (with `status` and `SalesSettings` imported):

```python
@router.patch("/teams/{team_id}", response_model=TeamOut)
async def rename_team(ctx: TeamAdmin, team_id: UUID, body: TeamIn) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        try:
            renamed = await conn.fetchval(
                "update teams set name = $2 where id = $1 returning id", team_id, body.name
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(f"a team called {body.name!r} already exists") from exc
        if renamed is None:
            raise NotFound("no such team")
        members = await conn.fetchval(
            "select coalesce(array_agg(user_id), '{}') from team_members where team_id = $1",
            team_id,
        )
    return {"id": team_id, "name": body.name, "member_ids": members}


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(ctx: TeamAdmin, team_id: UUID) -> None:
    """Refused while routing sends customers to it: a rule pointing at a team
    that is gone routes a customer to nobody. Its people stay; its customers
    keep their owners and lose only the team."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        raw = await conn.fetchval("select sales_settings from tenants where id = $1", ctx.tenant_id)
        settings = SalesSettings.model_validate(raw or {})
        if settings.default_team_id == team_id or any(
            rule.team_id == team_id for rule in settings.routing_rules
        ):
            raise Conflict("routing still sends customers to this team; change the routing first")
        deleted = await conn.fetchval("delete from teams where id = $1 returning id", team_id)
        if deleted is None:
            raise NotFound("no such team")
```

`TeamIn` carries `member_ids` too; a rename ignores them — membership is changed on the member
(`PATCH /v1/members/{id}`), which is the one place it is written.

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_settings_api.py tests/test_me_and_team.py tests/test_copilot_agent.py tests/test_visibility.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/dealerai/routes/settings.py apps/api/src/dealerai/sales/settings.py \
        apps/api/src/dealerai/agents/sales/copilot.py apps/api/src/dealerai/routes/team.py \
        apps/api/src/dealerai/main.py apps/api/tests/test_settings_api.py \
        apps/api/tests/test_me_and_team.py apps/api/tests/test_copilot_agent.py
git commit -m "feat(sales): settings over HTTP, each key behind the permission it needs"
```

---

## Task 8: Quick replies over HTTP

**Files:**
- Create: `apps/api/src/dealerai/routes/quick_replies.py`
- Modify: `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_quick_replies_api.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_everyone_reads_them_in_shortcut_order() -> None:
def test_a_manager_adds_one_and_a_salesperson_cannot() -> None:        # 201 / 403
def test_a_shortcut_is_a_slash_and_a_word() -> None:                   # "price" → 400, field "shortcut"
def test_two_replies_cannot_share_a_shortcut() -> None:                # 409
def test_a_reply_with_no_text_in_any_language_is_refused() -> None:    # 422, in words
def test_saving_replaces_the_whole_reply() -> None:                    # fr removed when not sent
def test_another_dealerships_reply_is_a_404() -> None:                 # PATCH and DELETE
```

Run: `cd apps/api && uv run pytest tests/test_quick_replies_api.py -q` — Expected: FAIL, 404.

- [ ] **Step 2: The routes**

`apps/api/src/dealerai/routes/quick_replies.py`:

```python
"""Quick replies: `/price` in the composer becomes the dealership's own words.

Tenant-wide and read by everyone; written by whoever holds
settings.quick_replies (docs/sales/06-api-contract.md § 8). A save replaces the
whole reply — the form always sends all of it, and a partial update is how a
French body nobody meant to keep survives an edit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from ..core.errors import Conflict, NotFound, Unusable
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission

router = APIRouter(prefix="/v1/quick-replies", tags=["quick-replies"])

Editor = Annotated[TenantContext, Depends(require_permission("settings.quick_replies"))]


class Bodies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: str | None = Field(default=None, max_length=1000)
    en: str | None = Field(default=None, max_length=1000)
    fr: str | None = Field(default=None, max_length=1000)


class QuickReplyIn(BaseModel):
    #: Matches the table's check (0011): a slash and a lowercase word.
    shortcut: str = Field(pattern=r"^/[a-z0-9-]{1,30}$")
    title: str = Field(min_length=1, max_length=80)
    body: Bodies


class QuickReply(QuickReplyIn):
    id: UUID
    updated_at: datetime


_COLUMNS = "id, shortcut, title, body, updated_at"


def _bodies(body: Bodies) -> dict[str, str]:
    kept = {lang: text.strip() for lang, text in body.model_dump().items() if text and text.strip()}
    if not kept:
        raise Unusable("a quick reply needs its text in at least one language")
    return kept


@router.get("", response_model=list[QuickReply])
async def list_quick_replies(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(f"select {_COLUMNS} from quick_replies order by shortcut")
    return [dict(row) for row in rows]


@router.post("", response_model=QuickReply, status_code=status.HTTP_201_CREATED)
async def add_quick_reply(ctx: Editor, body: QuickReplyIn) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        try:
            row = await conn.fetchrow(
                f"""insert into quick_replies (tenant_id, shortcut, title, body, created_by)
                    values ($1, $2, $3, $4, $5) returning {_COLUMNS}""",
                ctx.tenant_id,
                body.shortcut,
                body.title,
                _bodies(body.body),
                ctx.user.id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(f"{body.shortcut} is already a quick reply") from exc
    return dict(row)


@router.patch("/{reply_id}", response_model=QuickReply)
async def save_quick_reply(ctx: Editor, reply_id: UUID, body: QuickReplyIn) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        try:
            row = await conn.fetchrow(
                f"""update quick_replies set shortcut = $2, title = $3, body = $4
                     where id = $1 returning {_COLUMNS}""",
                reply_id,
                body.shortcut,
                body.title,
                _bodies(body.body),
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(f"{body.shortcut} is already a quick reply") from exc
    if row is None:
        raise NotFound("no such quick reply")
    return dict(row)


@router.delete("/{reply_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quick_reply(ctx: Editor, reply_id: UUID) -> None:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        if await conn.fetchval("delete from quick_replies where id = $1 returning id", reply_id) is None:
            raise NotFound("no such quick reply")
```

Register the router in `main.py`.

- [ ] **Step 3: Run the tests, then the whole backend**

Run: `cd apps/api && uv run pytest tests/test_quick_replies_api.py -q && cd ../.. && npm run lint && npm run typecheck && npm run test`
Expected: PASS everywhere. This is the backend's checkpoint: everything after it is the browser.

- [ ] **Step 4: Commit**

```bash
git add apps/api/src/dealerai/routes/quick_replies.py apps/api/src/dealerai/main.py \
        apps/api/tests/test_quick_replies_api.py
git commit -m "feat(sales): quick replies over HTTP"
```

---
## Task 9: The browser's side of the contract

**Files:**
- Modify: `apps/web/lib/api/openapi.json`, `apps/web/lib/api/schema.ts` (generated)
- Modify: `apps/web/lib/api/keys.ts`, `apps/web/lib/api/hooks.ts`, `apps/web/lib/live.tsx`,
  `apps/web/lib/i18n-client.tsx`
- Modify: `apps/web/messages/en.ts`, `apps/web/messages/ar.ts`
- Test: `apps/web/lib/api/hooks.test.ts`

- [ ] **Step 1: Regenerate the types**

Run: `npm run api-types`
Expected: `schema.ts` gains `ManagerDashboard`, `SalesSettings`, `SalesSettingsPatch`, `Acceptance`,
`QuickReply`, `QuickReplyIn`, and the export, erase and team routes.

- [ ] **Step 2: Keys**

In `apps/web/lib/api/keys.ts`:

```ts
  /** One day's dashboard; `dashboardAll` is its prefix, so a live event
   *  refreshes whichever day is open. */
  dashboard: (tenantId: string, date: string) => ["dashboard", tenantId, date] as const,
  dashboardAll: (tenantId: string) => ["dashboard", tenantId] as const,
  salesSettings: (tenantId: string) => ["sales-settings", tenantId] as const,
  acceptance: (tenantId: string, days: number) => ["acceptance", tenantId, days] as const,
  quickReplies: (tenantId: string) => ["quick-replies", tenantId] as const,
  channels: (tenantId: string) => ["channels", tenantId] as const,
  templates: (tenantId: string, channelId: string) => ["templates", tenantId, channelId] as const,
```

- [ ] **Step 3: Hooks**

In `apps/web/lib/api/hooks.ts`, the types this slice reads, then one hook per route. The ones that
carry a decision, in full:

```ts
export type ManagerDashboard = components["schemas"]["ManagerDashboard"];
export type AttentionItem = components["schemas"]["AttentionItem"];
export type RepRow = components["schemas"]["RepRow"];
export type SalesSettings = components["schemas"]["SalesSettings"];
export type SalesSettingsPatch = components["schemas"]["SalesSettingsPatch"];
export type RoutingRule = components["schemas"]["RoutingRule"];
export type Team = components["schemas"]["TeamOut"];
export type QuickReply = components["schemas"]["QuickReply"];
export type QuickReplyIn = components["schemas"]["QuickReplyIn"];
export type KnowledgeDocument = components["schemas"]["Document"];
export type Channel = components["schemas"]["ChannelOut"];
export type Template = components["schemas"]["TemplateOut"];
export type Acceptance = components["schemas"]["Acceptance"];

/** Not fetched at all for somebody who may not read it: a 403 in the console
 *  on every visit is noise, and the page says why instead. */
export function useManagerDashboard(date: string | null, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.dashboard(tenantId, date ?? "today"),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/dashboard/manager", {
          params: { header, query: date ? { date } : {} },
        }),
      ),
  });
}

export function useSaveSalesSettings() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    // Only what the screen changed: a manager's routing save must not carry
    // the AI keys she may not write, or the whole save is refused.
    mutationFn: async (patch: SalesSettingsPatch) =>
      unwrap(await api.PATCH("/v1/settings/sales", { params: { header }, body: patch })),
    onSuccess: (saved) => queryClient.setQueryData(keys.salesSettings(tenantId), saved),
  });
}

export function useUploadDocument() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, kind, title }: { file: File; kind: string; title: string }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      if (title) form.append("title", title);
      return unwrap(
        await api.POST("/v1/documents", {
          params: { header },
          // The typed body describes the fields; the serializer sends the form.
          body: { file: "", kind, title },
          bodySerializer: () => form,
        }),
      );
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.documents(tenantId) }),
  });
}

/** The customer's file, saved by the browser. A fetch rather than a link:
 *  the request needs an Authorization header an <a href> cannot send. */
export function useExportCustomer(customerId: string) {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async () => {
      const blob = unwrap(
        await api.GET("/v1/customers/{customer_id}/export", {
          params: { header, path: { customer_id: customerId } },
          parseAs: "blob",
        }),
      ) as Blob;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `customer-${customerId}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },
  });
}

export function useEraseCustomer(customerId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/v1/customers/{customer_id}", {
          params: { header, path: { customer_id: customerId } },
        }),
      ),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: keys.customer(tenantId, customerId) });
      for (const key of [
        keys.customerList(tenantId),
        keys.conversationList(tenantId),
        keys.leadList(tenantId),
        keys.taskList(tenantId),
        keys.dashboardAll(tenantId),
      ]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}

/** S3 left bulk reassign as "the single-customer call in a loop behind a
 *  confirm" — that, with the names of whoever could not be moved. */
export function useBulkReassign() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ids,
      ownerId,
      onProgress,
    }: {
      ids: string[];
      ownerId: string;
      onProgress?: (done: number) => void;
    }) => {
      const failed: string[] = [];
      for (const [index, id] of ids.entries()) {
        const { response } = await api.POST("/v1/customers/{customer_id}/reassign", {
          params: { header, path: { customer_id: id } },
          body: { owner_id: ownerId },
        });
        if (!response.ok) failed.push(id);
        onProgress?.(index + 1);
      }
      return failed;
    },
    onSettled: () => {
      for (const key of [
        keys.customerList(tenantId),
        keys.conversationList(tenantId),
        keys.leadList(tenantId),
        keys.taskList(tenantId),
        keys.dashboardAll(tenantId),
      ]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
```

And, in the same shape as the hooks already there: `useSalesSettings`, `useAcceptance(days)`,
`useTeams`, `useSaveTeam` (POST without an id, PATCH with one), `useDeleteTeam`, `useEditMember`,
`useQuickReplies`, `useSaveQuickReply` (POST or PATCH), `useDeleteQuickReply`, `useDocuments` (with
`refetchInterval: 3000` while any document is `pending` or `processing`), `useDeleteDocument`,
`useChannels`, `useTemplates(channelId)` and `useSyncTemplates(channelId)`.

- [ ] **Step 4: What refreshes the dashboard**

In `lib/live.tsx`, straight after the `suggestion.ready` early return:

```ts
  // The dashboard counts all of it. Only the open day refetches — TanStack
  // marks the rest stale — so one line covers every event below.
  queryClient.invalidateQueries({ queryKey: keys.dashboardAll(tenantId) });
```

In `lib/i18n-client.tsx`:

```tsx
/** For content that arrives in both UI languages, like the brief's headline. */
export function useLocale(): Locale {
  return useContext(LocaleContext);
}
```

- [ ] **Step 5: Every string this slice shows**

Groups of keys in `messages/en.ts`, each mirrored in `messages/ar.ts` (the `satisfies` check fails
`tsc` on a missing one): `dashboard.*`, `tile.*`, `brief.*` (with `brief.waiting`,
`brief.hot_lead`, `brief.overdue_tasks` matching the item kinds), `teamTable.*`, `source.*`,
`settings.*` (one per section), `routing.*`, `day.mon` … `day.sun`, `language.ar|en|fr`,
`team.*`, `role.*`, `pipelines.*`, `category.open|won|lost`, `channels.*`, `quick.*`,
`knowledge.*`, `doc.<kind>` for the six kinds in `routes/documents.KINDS`, `ai.*`, `erase.*`,
`bulk.*`. The sentences that carry a rule are fixed here, not paraphrased later:

```ts
  "dashboard.phoneLine": "Replies typed on the phone skip AI drafts and response tracking.",
  "dashboard.forManagers": "This page is for managers.",
  "knowledge.pricesLine": "Prices and stock always come from Inventory, never from documents.",
  "ai.never.send": "Send anything by itself — a person presses Send.",
  "ai.never.price": "State a price or availability that is not in Inventory.",
  "ai.never.promise": "Promise a discount, a delivery date, finance approval or a trade-in value.",
  "ai.never.reserved": "Call a reserved car available.",
  "ai.never.optOut": "Write to somebody who asked not to be contacted.",
  "team.sees.owner": "Owners and admins see everything and can change everything.",
  "team.sees.manager": "Managers see their teams' customers, conversations and leads.",
  "team.sees.sales": "Salespeople see their own customers and their team's unassigned queue.",
  "team.sees.viewer": "Viewers see everything and change nothing.",
  "erase.stays": "One line stays in the audit log: who deleted them, and when. Nothing about them.",
  "channels.connectLater": "Connecting Pollux's own WhatsApp number arrives with coexistence.",
  "quick.nameHint": "{name} becomes the customer's first name.",
```

- [ ] **Step 6: Test, then check**

In `apps/web/lib/api/hooks.test.ts`:

```ts
it("refreshes the dashboard on a conversation event and not on a new draft", …);
it("saves only the settings the screen changed", …);   // the PATCH body is exactly the patch
it("reports who could not be handed over", …);          // one 403 among three → [thatId]
```

Run: `npm run check:web && npm run check:openapi`
Expected: PASS; no drift in the generated types.

- [ ] **Step 7: Commit**

```bash
git add apps/web/lib apps/web/messages
git commit -m "feat(web): the manager's and the settings' side of the contract"
```

---

## Task 10: The dashboard

**Files:**
- Create: `apps/web/components/manager/StatTile.tsx`, `BriefCard.tsx`, `WaitingList.tsx`,
  `RepTable.tsx`, and a test beside each of the first, second and fourth
- Modify: `apps/web/app/[tenant]/dashboard/page.tsx`
- Modify: `apps/web/app/[tenant]/tasks/page.tsx`

[08](../08-screens.md) §11, top to bottom: the brief, the tiles, waiting now, the team, the pipeline,
sources and the phone share.

- [ ] **Step 1: A tile, and what colour a median is**

```tsx
// StatTile.tsx
/** Green within the target, amber within twice it, red beyond. */
export function tone(seconds: number | null | undefined, target: number): Tone | null {
  if (seconds == null) return null;
  if (seconds <= target) return "ok";
  return seconds <= 2 * target ? "warn" : "bad";
}

const EDGE: Record<Tone, string> = {
  ok: "border-s-4 border-s-green-500",
  warn: "border-s-4 border-s-amber-500",
  bad: "border-s-4 border-s-red-500",
};

/** A number, its name, and — when there is one — the list it counted. */
export function StatTile({ label, value, href, tone }: {
  label: string; value: string; href?: string; tone?: Tone | null;
}) {
  const body = (
    <div className={`bg-surface border-border rounded-lg border p-3 ${tone ? EDGE[tone] : ""}`}>
      <p className="text-xl font-semibold tabular-nums" dir="ltr">{value}</p>
      <p className="text-muted text-xs">{label}</p>
    </div>
  );
  return href ? <Link href={href} className="block hover:opacity-90">{body}</Link> : body;
}
```

Tests: `tone(299, 300) === "ok"`, `tone(599, 300) === "warn"`, `tone(601, 300) === "bad"`,
`tone(null, 300) === null`; a tile with an `href` is a link to it.

- [ ] **Step 2: The brief**

```tsx
// BriefCard.tsx — every item links to what it is about.
const HREF: Record<AttentionItem["kind"], (tenant: string, item: AttentionItem) => string> = {
  waiting: (tenant, item) => `/${tenant}/inbox/${item.id}`,
  hot_lead: (tenant, item) => `/${tenant}/pipeline?lead=${item.id}`,
  overdue_tasks: (tenant, item) => `/${tenant}/tasks?bucket=overdue&assignee=${item.id}`,
};

export function BriefCard({ brief, tenant }: { brief: ManagerDashboard["brief"]; tenant: string }) {
  const t = useT();
  const locale = useLocale();
  const headline = brief.headline?.[locale];
  return (
    <section aria-label={t("brief.title")} className="bg-surface border-border rounded-lg border p-4">
      {headline && <p className="text-base font-medium" dir="auto">{headline}</p>}
      <h2 className="text-muted mt-2 text-xs font-semibold">{t("brief.thisMorning")}</h2>
      {brief.items.length === 0 ? (
        <p className="text-muted mt-1 text-sm">{t("brief.nothing")}</p>
      ) : (
        <ul className="mt-1 divide-y divide-black/5 dark:divide-white/10">
          {brief.items.map((item) => (
            <li key={`${item.kind}:${item.id}`}>
              <Link href={HREF[item.kind](tenant, item)}
                    className="hover:bg-background flex min-h-11 items-center justify-between gap-2 text-sm">
                <span className="truncate" dir="auto">
                  {item.name ?? t("inbox.unknownCustomer")}
                  <span className="text-muted ms-2 text-xs">
                    {t(`brief.${item.kind}`)}
                    {item.count ? ` · ${item.count}` : ""}
                  </span>
                </span>
                {item.owner && <span className="text-muted shrink-0 text-xs">{item.owner.name}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

Tests: the Arabic UI shows the `ar` headline and the English UI the `en`; with no headline the items
still show under "This morning"; a waiting item links to its conversation, a hot lead to the pipeline
drawer, a person to their overdue tasks.

- [ ] **Step 3: Waiting, with Reassign**

`WaitingList.tsx` shows the first ten of `waiting`, each a row with the customer, their
`WaitingTimer`, the assignee, **Open**, and — for `inbox.assign` — a Reassign select over
`useMembers()` (salespeople and managers who are taking chats first) that calls
`useAssignConversation(conversation.id)` from the row's own component, so each row has its own
mutation state.

- [ ] **Step 4: The team, as a table and as cards**

```tsx
// RepTable.tsx — a table from md up; below it, a card per person (08 §11).
<table className="hidden w-full text-sm md:table">…</table>
<ul className="md:hidden">…</ul>
```

A person opens in place: who is waiting on them (the dashboard's own `waiting`, filtered by
assignee — up to fifty, one request) and a link to
`/${tenant}/tasks?bucket=overdue&assignee=${rep.user.id}`. Medians go through `formatDuration` and
`tone()`; bands show as three small counts.

Test: "opens a person to show who is waiting on them and where their overdue tasks are".

- [ ] **Step 5: The page**

`app/[tenant]/dashboard/page.tsx`: `useMe()`, then `useManagerDashboard(filters.date || null,
allowed)` with `useFilters({ date: "" })` and a native `<input type="date">` for the day. Without
`dashboard.manager` the page is one line — `dashboard.forManagers` — and a link to My day. Then, in
order: `BriefCard`; the tiles (`grid-cols-2 md:grid-cols-4`), where waiting links to the inbox's
team view (`all` for an owner), hot leads to `/customers?band=hot`, and new leads, won and lost to
the pipeline; `WaitingList`; `RepTable`; pipeline totals per board; sources (`source.<value>`,
falling back to the raw value); and this week's and last week's inbox share with
`dashboard.phoneLine` under it.

- [ ] **Step 6: One person's tasks**

In `app/[tenant]/tasks/page.tsx`, a manager's assignee select lists the team as well as "Mine" and
"Team", so the link from the dashboard opens with the right name showing:

```tsx
{me.data?.scope !== "own" &&
  (members.data ?? []).map((member) => (
    <option key={member.id} value={member.id}>{member.name ?? member.email}</option>
  ))}
```

- [ ] **Step 7: Check and commit**

Run: `npm run check:web` — Expected: PASS, including `check:rtl`.

```bash
git add apps/web/components/manager "apps/web/app/[tenant]/dashboard/page.tsx" \
        "apps/web/app/[tenant]/tasks/page.tsx"
git commit -m "feat(web): the manager dashboard"
```

---

## Task 11: Settings — the frame, and routing and targets

**Files:**
- Create: `apps/web/components/settings/sections.ts`, `apps/web/app/[tenant]/settings/layout.tsx`,
  `apps/web/app/[tenant]/settings/page.tsx`, `apps/web/app/[tenant]/settings/routing/page.tsx`
- Create: `apps/web/components/settings/HoursEditor.tsx`, `RuleEditor.tsx`, `describeRule.ts`, and
  `describeRule.test.ts`, `HoursEditor.test.tsx`

- [ ] **Step 1: The sections, hidden when the role lacks them**

```ts
// sections.ts — 08 §13. Quick replies has no permission: a salesperson reads them.
export const SECTIONS: readonly NavItem[] = [
  { href: "/settings/channels", key: "settings.channels", permission: "settings.channels" },
  { href: "/settings/team", key: "settings.team", permission: "settings.team" },
  { href: "/settings/routing", key: "settings.routing", permission: "settings.routing" },
  { href: "/settings/pipelines", key: "settings.pipelines", permission: "pipeline.edit_stages" },
  { href: "/settings/quick-replies", key: "settings.quickReplies" },
  { href: "/settings/knowledge", key: "settings.knowledge", permission: "settings.knowledge" },
  { href: "/settings/ai", key: "settings.ai", permission: "settings.ai" },
];
```

`layout.tsx` puts `<NavLinks slug={tenant} items={SECTIONS} />` beside the section — a column from
md up, a scrolling row below it. `page.tsx` replaces itself with the first section the person may
open, once `useMe()` has answered.

- [ ] **Step 2: A rule, in words**

```ts
// describeRule.ts
/** "Arabic or French · from DZ, MA · from an ad → Export". Every part is
 *  optional; a rule with none of them matches everybody. */
export function describeRule(
  rule: RoutingRule,
  teams: Team[],
  t: (key: MessageKey) => string,
): string {
  const parts: string[] = [];
  if (rule.languages?.length) {
    parts.push(rule.languages.map((code) => t(`language.${code}` as MessageKey)).join(t("routing.or")));
  }
  if (rule.countries?.length) parts.push(`${t("routing.from")} ${rule.countries.join(", ")}`);
  if (rule.from_ad === true) parts.push(t("routing.adOnly"));
  if (rule.from_ad === false) parts.push(t("routing.notAd"));
  const team = teams.find((candidate) => candidate.id === rule.team_id)?.name ?? "?";
  return `${parts.length ? parts.join(" · ") : t("routing.everyone")} → ${team}`;
}
```

Tests: a rule with every part; a rule with none ("Everyone → Local sales"); a team that no longer
exists shows `?` rather than an id.

- [ ] **Step 3: The hours**

`HoursEditor` edits `business_hours`: a switch "We keep opening hours" (off saves `{}`, which the
backend reads as always open), then a row per day — open or closed, and two `<input type="time">`.
A day that closes before it opens is marked on the row and blocks Save; the API refuses it too, but
a 400 naming `business_hours.mon.close` is no way to learn it.

Tests: switching a day off removes it from the value; closing before opening disables Save.

- [ ] **Step 4: The page, and a Save that stays in reach**

`routing/page.tsx` holds a local copy of the routing keys from `useSalesSettings()`, edited by
`HoursEditor`, a number input for the first-response target, the unassigned-queue switch, a
default-team select, and a list of `RuleEditor` rows (languages, countries, from an ad or not, team;
up, down, remove), each with its `describeRule` line under it. When the copy differs from the saved
settings, a bar sticks to the bottom — `bottom-16` above the phone's navigation, `md:bottom-0` —
with Discard and Save. Save sends only the routing keys it changed, through `useSaveSalesSettings`,
and shows the API's `detail` when it is refused.

- [ ] **Step 5: Check and commit**

Run: `npm run check:web` — Expected: PASS.

```bash
git add apps/web/components/settings "apps/web/app/[tenant]/settings"
git commit -m "feat(web): settings, starting with where conversations go and how fast"
```

---

## Task 12: Settings — the team, the pipelines, the channel

**Files:**
- Create: `apps/web/app/[tenant]/settings/team/page.tsx`, `pipelines/page.tsx`, `channels/page.tsx`
- Create: `apps/web/components/settings/StageEditor.tsx`, `StageEditor.test.tsx`

- [ ] **Step 1: The team**

Members as rows: name and email; a role select; team checkboxes; language checkboxes (ar, en, fr);
the taking-chats switch — each change one `useEditMember` call, and a refusal (the last owner)
shown as the API's sentence on that row. Teams below: rename in place, delete (the 409 when routing
still sends customers there is shown as its sentence), and New team. Then **Who sees what**: the four
`team.sees.*` lines, word for word.

- [ ] **Step 2: The pipelines**

```tsx
// StageEditor.tsx — the list as it will be saved, in order; PUT replaces it
// whole (routes/pipelines.py), so there is no half-saved board.
{stages.map((stage, index) => (
  <li key={stage.id ?? `new-${index}`} className="flex items-center gap-2">
    <input value={stage.name} aria-label={t("pipelines.stage")} onChange={…} />
    <select value={stage.category} aria-label={t("pipelines.category")} onChange={…}>
      {(["open", "won", "lost"] as const).map((category) => (
        <option key={category} value={category}>{t(`category.${category}`)}</option>
      ))}
    </select>
    <button type="button" aria-label={t("pipelines.moveUp")} disabled={index === 0} onClick={…}>↑</button>
    <button type="button" aria-label={t("pipelines.moveDown")} disabled={index === stages.length - 1} onClick={…}>↓</button>
    <button type="button" aria-label={t("pipelines.remove")} onClick={…}>×</button>
  </li>
))}
```

Tests: moving a stage up changes the order sent to `useReplaceStages`; removing a stage that still
holds leads shows the server's sentence ("Negotiation still holds 3 leads. Move them first.").

- [ ] **Step 3: The channel**

`useChannels()` as cards — name, mode (`channels.mode.*`), status, and the quality rating as a
coloured dot with its word — then each channel's templates: name, language, category, status, and
the rejection reason when there is one. **Sync templates** for `settings.channels`. Under the cards,
`channels.connectLater`.

- [ ] **Step 4: Check and commit**

Run: `npm run check:web` — Expected: PASS.

```bash
git add "apps/web/app/[tenant]/settings" apps/web/components/settings
git commit -m "feat(web): settings for the team, the pipelines and the channel"
```

---

## Task 13: Settings — quick replies, knowledge, the AI; and `/` in the composer

**Files:**
- Create: `apps/web/app/[tenant]/settings/quick-replies/page.tsx`, `knowledge/page.tsx`, `ai/page.tsx`
- Create: `apps/web/components/settings/QuickReplyForm.tsx`
- Create: `apps/web/components/inbox/QuickReplyMenu.tsx`, `QuickReplyMenu.test.tsx`
- Modify: `apps/web/components/inbox/Composer.tsx`, `Composer.test.tsx`, `Thread.tsx`

- [ ] **Step 1: The three pages**

**Quick replies:** the list by shortcut, and `QuickReplyForm` (shortcut, title, one body per
language, `quick.nameHint` under the bodies) for `settings.quick_replies`; everybody else reads the
list with `quick.readOnly` above it.

**Knowledge:** a file input (`accept=".pdf,.docx,.txt"`), a kind select over the six kinds and a
title, then the documents with their status in words, their passage count, and a failed one's
sentence (`this PDF could not be read: …`); Delete. `knowledge.pricesLine` above the list.

**AI assistant:** drafts on or off; the Arabic register as two radios (`ai.register.mirror`,
`ai.register.gulf`); follow-up timing as up to five day counts; the five `ai.never.*` lines; and
`useAcceptance(30)` as a table by intent — decided, accepted as a percentage, and the four outcomes —
with intents through the `draft.intent.*` keys S4 added. Each save sends only the AI keys.

- [ ] **Step 2: `/` in the composer, test first**

```ts
// QuickReplyMenu.test.tsx
it("lists the replies whose shortcut starts with what was typed", …);   // "/pr" → /price, not /location
it("fills in the customer's language and first name", …);              // ar body, "{name}" → "Omar"
it("falls back to English, then to any language it has", …);
```

```ts
// QuickReplyMenu.tsx
export function matching(replies: QuickReply[], typed: string): QuickReply[] {
  const query = typed.slice(1).toLowerCase();
  return replies.filter((reply) => reply.shortcut.slice(1).startsWith(query)).slice(0, 6);
}

export function filled(reply: QuickReply, language: string | null, name: string | null): string {
  const code = (language ?? "").slice(0, 2) as "ar" | "en" | "fr";
  const body = reply.body[code] ?? reply.body.en ?? reply.body.ar ?? reply.body.fr ?? "";
  const first = (name ?? "").trim().split(/\s+/)[0] ?? "";
  return body.replaceAll("{name}", first);
}
```

The menu opens while the text is a single word starting with `/` and something matches. Arrow keys
move, Enter or a click picks — and then does **not** send — Escape closes it until the text changes.
`Composer` gains `language` and `customerName` props, passed by `Thread` from the conversation's
contact.

Composer tests: "Enter picks a quick reply instead of sending"; "a message that starts with / and
has a space in it is sent as typed".

- [ ] **Step 3: Check and commit**

Run: `npm run check:web` — Expected: PASS.

```bash
git add "apps/web/app/[tenant]/settings" apps/web/components/settings apps/web/components/inbox
git commit -m "feat(web): quick replies, knowledge and the AI's settings, and / in the composer"
```

---

## Task 14: A customer's data, and many customers at once

**Files:**
- Create: `apps/web/components/crm/EraseDialog.tsx`, `EraseDialog.test.tsx`
- Modify: `apps/web/app/[tenant]/customers/[contactId]/page.tsx`
- Modify: `apps/web/app/[tenant]/customers/page.tsx`, `apps/web/components/crm/CustomerRow.tsx`,
  `CustomerRow.test.tsx`

- [ ] **Step 1: Export and delete on the customer**

Two buttons join Reassign and Merge in the 360's header: **Download their data** for `settings.team`
(`useExportCustomer`), and **Delete this customer** for an owner or admin (`me.role`, since erasure
is a role in the contract, not a permission).

`EraseDialog` says what goes — conversations and messages, voice notes and files, leads, tasks and
the AI's drafts — and `erase.stays`; offers **Download a copy first**; and enables **Delete for
good** only once the customer's name is typed (or `delete`, for a customer with none). On success it
replaces the page with the customers list.

Tests: "Delete stays disabled until the name is typed"; "offers the export first"; "a refusal shows
the API's sentence".

- [ ] **Step 2: Many at once**

With `contacts.reassign`, each `CustomerRow` gets a checkbox, the list a "select all shown", and a
bar appears once anything is selected: `N selected · Hand over to [member] · Hand over`. It runs
`useBulkReassign` with progress ("3 of 12") and ends by naming anybody who could not be moved.

Test: "hands two customers over and names the one that failed".

- [ ] **Step 3: Check and commit**

Run: `npm run check:web` — Expected: PASS.

```bash
git add apps/web/components/crm "apps/web/app/[tenant]/customers"
git commit -m "feat(web): export, erasure, and handing many customers over at once"
```

---

## Task 15: A yesterday worth a brief

**Files:**
- Modify: `apps/api/src/dealerai/scripts/seed_sales.py`
- Modify: `apps/api/tests/test_seed_sales.py`

The local workspace opens on an empty dashboard today; the exit run needs a morning to run. Seeded
the way the product writes it, as S4 learned the hard way:

- Three quick replies — `/price`, `/location`, `/documents` — each in Arabic, English and French,
  `{name}` in the greeting.
- Yesterday, in Dubai: four conversations that started and were first answered (the customer's
  first message between two and nine minutes before the answer, so the median is a number worth
  reading), one `sla_misses` row against Salem, a Local lead won yesterday, and two of Mohamed's
  tasks past due.
- A `sales.brief_due` event for today, `run_after` now, deduped on today's date — so a running
  worker writes today's briefs through the real handler rather than the seed writing one.

Test additions in `test_seed_sales.py`: "the workspace has quick replies"; "yesterday has a first
response, a miss and a win"; "today's brief is queued, once, however often the seed runs".

- [ ] **Step 1:** write the three tests; run them and see them fail.
- [ ] **Step 2:** seed it; run `tests/test_seed_sales.py`, then `npm run db:seed` twice and query
  `select count(*) from events where event_type = 'sales.brief_due' and status = 'pending'`
  — Expected: `1` for Pollux.
- [ ] **Step 3: Commit**

```bash
git add apps/api/src/dealerai/scripts/seed_sales.py apps/api/tests/test_seed_sales.py
git commit -m "feat(sales): a seeded yesterday for the dashboard and the brief"
```

---

## Task 16: Prove it, then write it down

**Files:**
- Modify: `docs/sales/plans/s6-manager-view.md` (a Review section), `docs/sales/README.md`

- [ ] **Step 1: The full check**

Run: `npm run check && npm run check:openapi && npm run eval:brief`
Expected: every suite green, the guards at 100%, no drift, three headlines worth reading.

- [ ] **Step 2: The exit path, in a browser**

`npm run db:seed`, then the API, the worker and the web app; the simulator is the customer. Sign in
as the people named, and write down what actually happened at each step:

1. **Sara** (manager) opens the dashboard: today's headline in English, then in Arabic after
   switching language; the items link to a waiting customer, a hot lead and Mohamed's overdue tasks.
2. Every tile matches a `psql` count over the rows it names.
3. A new simulated customer arrives: waiting goes up without a refresh.
4. Reassign a waiting customer from Ahmed to Mohamed: the inbox shows the move.
5. Salem's row shows yesterday's miss; opening him shows who is waiting on him and links to his tasks.
6. **Khalid** (owner) sets the first-response target to 2 minutes: the next customer's timer turns
   amber a minute after they write. A routing rule sends French to Export: the next French-speaking
   customer lands with Salem.
7. Pipelines: rename a stage; deleting one that holds leads says how many.
8. Quick replies: add `/hours`; in Omar's conversation `/ho` then Enter puts in the Arabic text with
   his name, and does not send.
9. Knowledge: a PDF uploaded from the screen reaches ready, and a question is answered from it.
10. AI: drafts off → the next message gets no draft; back on.
11. Export Omar → the file has his messages and a working media link. Delete Omar → gone from the
    inbox, the customers list and the pipeline; `psql` finds him in no table; his files are gone from
    `.storage`.
12. Retention at 1 month and a customer aged 40 days → the retention event erases them and nobody
    else.
13. Arabic at 375 px: tiles two to a row, the team as cards, every settings section usable.
14. A viewer sees the dashboard and no Reassign; a salesperson sees Settings → Quick replies,
    read-only, and nothing else.

- [ ] **Step 3: The review**

Append `## Review — <date>` to this plan, in the shape of S4's: what the exit run found and where it
was fixed, what is sound as built, what is known and deliberately left, and the steps as verified.
Update the Code row in `docs/sales/README.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/sales/plans/s6-manager-view.md docs/sales/README.md
git commit -m "docs(sales): S6 manager view complete, with the exit run recorded"
```

---

## Spec coverage

| Requirement | Task |
|---|---|
| [08](../08-screens.md) §11 — brief, tiles with colour against the target, waiting with Open and Reassign, team table with per-person drill-in, pipeline, sources, phone share and its line, non-managers' line | 5, 6, 10 |
| §11 done-when — numbers traceable to rows; reassigning changes the inbox; two tiles per row and cards on a phone | 5 (tests), 10, 16 (steps 2, 4, 13) |
| [05](../05-workflows.md) §13 — SQL facts, ranked candidates, model headline, price guard on the text, notify owners and managers | 5, 6 (numbers guard in place of the price guard: the brief has no prices, every number is checked) |
| [05](../05-workflows.md) §14 and [02](../02-data-model.md) §7 — nightly retention, media deleted by a worker job, notifications 90 days, webhook bodies 14 days, DELETE with export offered first and an audit of who and when | 1, 2, 3, 14 |
| [06](../06-api-contract.md) §2 — `GET/PATCH /v1/settings/sales`, teams PATCH and DELETE | 7 |
| §4 — `GET /v1/customers/{id}/export`, `DELETE /v1/customers/{id}` | 2 |
| §7 — `GET /v1/dashboard/manager` with the brief in it | 5, 6 |
| §8 — quick replies | 8, 13 |
| §12 — the permission table, including the viewer's dashboard | 5, 7 |
| [08](../08-screens.md) §13 — Channels (without Connect), Team and roles, Routing, Pipelines, Quick replies, Knowledge, AI assistant; sections hidden by permission; a salesperson sees only quick replies, read-only | 11, 12, 13 |
| [04](../04-ai-copilot.md) §9 — acceptance by intent from `v_suggestion_acceptance` | 1, 7, 13 |
| [00](../00-prd.md) Q3 — the Arabic register setting | 7, 13 |
| S3's deferral — bulk reassign from the customers list | 9, 14 |
| [00](../00-prd.md) §7 S2 and S8 — median first response in business hours; inbox against phone | 4, 5 |

---

## Execution

Inline in this session with `superpowers:executing-plans`, as S4 was — no subagents unless asked.
Checkpoints after Task 4 (the corrected numbers), Task 8 (the whole backend), Task 12, and Task 16.
