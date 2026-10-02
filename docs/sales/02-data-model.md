# Sales — Data model

**Status:** Draft · **Depends on:** DealerAI OS [03](../03-database-schema.md) (tenancy rules), [01](01-architecture.md)

This is the specification for the Sales migrations. There is one per slice, because an applied
migration is never edited — the runner refuses a changed checksum: `0006_sales_core.sql` (S0: teams,
identities, ownership, visibility), then the inbox, CRM and copilot migrations as those slices start.
Once a migration exists, **the SQL is the source of truth** and this document explains it — the
DealerAI OS rule, for the same reason: a schema described in two places drifts in one of them.

Every rule in DealerAI OS 03 still applies: `tenant_id` on every row, RLS enabled and forced, the
policy generated in a loop, money as `*_minor bigint` + `currency`, `text` + `CHECK` instead of enums,
no soft deletes, views with `security_invoker = true`.

---

## 1. Map

```
tenants ~ ──┬── memberships ~ ── team_members + ── teams +
            ├── channels ~ ── message_templates +
            ├── contacts ~ ──┬── contact_identities +
            │                ├── conversations ~ ──┬── messages ~
            │                │                     ├── ai_suggestions +
            │                │                     └── conversation_reads +
            │                ├── leads ~ ── activities
            │                └── tasks +
            ├── pipelines + ── pipeline_stages +
            ├── quick_replies +
            ├── notifications + · push_subscriptions +
            └── documents · doc_chunks            (existing; populated from Phase 1)

+ new   ~ changed
```

---

## 2. New tables

### `teams`, `team_members`

| Column | Notes |
|---|---|
| `teams.id, tenant_id, name, created_at, updated_at` | `unique (tenant_id, name)` |
| `team_members.team_id, user_id, tenant_id, created_at` | `primary key (team_id, user_id)`; index `(tenant_id, user_id)` |

A manager manages every team they are a member of. There is no `is_manager` flag: the role decides,
and two sources for one fact drift.

### `contact_identities`

| Column | Notes |
|---|---|
| `id, tenant_id, contact_id` | `contact_id` cascades |
| `kind` | `whatsapp_user_id` · `phone` · `instagram_id` · `messenger_psid` · `email` |
| `value` | `phone` must match `^\+[1-9][0-9]{6,14}$` (E.164); `email` stored lowercased |
| `is_primary` | partial unique `(contact_id, kind) where is_primary` |
| `created_at` | |

`unique (tenant_id, kind, value)` is what makes identity resolution safe under concurrency: two
webhooks from a new customer race to insert the same BSUID, one wins, the other re-selects. A jsonb
of platform ids (the old `contacts.external_refs`) cannot enforce that. Resolution order:
[03](03-whatsapp.md) §5.

### `pipelines`, `pipeline_stages`

| Column | Notes |
|---|---|
| `pipelines.id, tenant_id, name, position, is_default, created_at, updated_at` | `unique (tenant_id, name)`; partial unique `(tenant_id) where is_default` |
| `pipeline_stages.id, tenant_id, pipeline_id, name, position, category, created_at` | `category`: `open` · `won` · `lost`; `unique (pipeline_id, name)`; partial unique `(pipeline_id) where category = 'won'` |

"At least one lost stage" and "a stage with leads cannot be deleted" are checked in the API
(409 with the count). A deferred constraint trigger for a rule that only one endpoint can break is
not worth its weight.

Seeded for every new tenant: one default pipeline *Sales*. Pollux gets *Local sale* and *Export*
(stages in [00](00-prd.md) and the seed).

### `tasks`

| Column | Notes |
|---|---|
| `id, tenant_id, title, kind` | `kind`: `follow_up` · `call` · `meeting` · `todo` |
| `due_at` | not null |
| `status` | `open` · `done` · `cancelled`; `completed_at`, `cancel_reason` |
| `assignee_id` | not null — **the visibility column** for tasks |
| `created_by` | null means the system |
| `contact_id, lead_id, conversation_id` | all `on delete set null` |
| `source` | `human` · `ai` · `rule` |
| `ai_draft` | jsonb `{reason, text, template_id, variables, suggestion_id}` or null |
| `created_at, updated_at` | |

Indexes: `(tenant_id, assignee_id, status, due_at)`; `(tenant_id, due_at) where status = 'open'`.

A lead's "next action" is its earliest open task — computed, not stored. `leads.next_action_at` is
dropped (see §3).

### `ai_suggestions`

What the AI proposed, kept separate from what was sent. It is the acceptance metric, the eval
dataset, and the Phase 2 autopilot trigger, so it must not be overwritten by editing a message.

| Column | Notes |
|---|---|
| `id, tenant_id, conversation_id, for_message_id, run_id` | `run_id` links to `agent_runs` for "why did it say that" |
| `status` | `generating` · `ready` · `blocked` · `superseded` |
| `text, template, language, intent, confidence` | `template` jsonb `{template_id, variables}`; `confidence`: `high` · `medium` · `low` |
| `sources, actions` | jsonb, shapes in [06](06-api-contract.md) |
| `needs_human, blocked_reason` | text |
| `outcome` | null · `sent` · `edited` · `discarded`; `outcome_at`, `outcome_by`, `final_message_id`, `edit_ratio numeric(4,3)`, `discard_reason` |
| `created_at` | |

Partial unique `(conversation_id) where status in ('generating','ready')`: at most one live draft per
conversation. A newer customer message supersedes the old draft in the same transaction that
creates the new one.

### `message_templates`

| Column | Notes |
|---|---|
| `id, tenant_id, channel_id` | |
| `external_id, name, language` | `unique (channel_id, name, language)` |
| `category` | `marketing` · `utility` · `authentication` |
| `status` | `approved` · `pending` · `rejected` · `paused` · `disabled` |
| `components` | jsonb, Meta's shape, kept verbatim for sending |
| `body, variables` | rendered body with `{{n}}`, and human labels for each variable |
| `rejected_reason, synced_at` | |

Synced from the WABA on connect, daily, and on the template status webhook.

### `quick_replies`

`id, tenant_id, shortcut, title, body jsonb {ar, en, fr}, created_by, created_at, updated_at`.
`shortcut ~ '^/[a-z0-9-]{1,30}$'`, `unique (tenant_id, shortcut)`.

### `conversation_reads`

`tenant_id, conversation_id, user_id, last_read_at` — `primary key (conversation_id, user_id)`.
Unread count = inbound customer messages newer than `last_read_at`. One row per person per
conversation, not a flag per message.

### `notifications`, `push_subscriptions`

| Table | Columns |
|---|---|
| `notifications` | `id, tenant_id, user_id, kind, title, body, href, entity jsonb {type, id}, read_at, created_at`; index `(tenant_id, user_id, created_at desc)`, partial `where read_at is null` |
| `push_subscriptions` | `id, tenant_id, user_id, endpoint (unique), p256dh, auth, user_agent, failure_count, last_success_at, created_at` — deleted when the push service answers 404 or 410. Written through `app.remember_push_subscription()`: a device belongs to whoever subscribed it last |

A notification of a kind worth a push (assigned, waiting, task due, hot lead) queues
`notification.push_requested` in the transaction that writes it. A task books its own
`task.due_check` at its due time, through the `tasks_book_due` trigger, because tasks are written
from several places and all of them pass through the table.

---

## 3. Changed tables

| Table | Change | Why |
|---|---|---|
| `tenants` | + `sales_settings jsonb not null default '{}'` | Business hours, response target, pool visibility, routing rules, default team, AI preferences. Read whole, never filtered — the jsonb rule. Validated by the `SalesSettings` Pydantic model |
| `memberships` | `role` check adds `manager`; + `languages text[]`, `accepting_chats boolean default true`, `last_assigned_at timestamptz`, `max_open_conversations int` | Routing needs languages and availability; round-robin needs `last_assigned_at` |
| `channels` | + `mode` (`cloud_api` · `coexistence`), `account_id text` (WABA id), `sync_state jsonb`, `quality_rating text`; global `unique (platform, external_id)` and index `(platform, account_id)` | Webhooks route by `phone_number_id`, but `account_update` arrives per WABA. One number can never belong to two tenants |
| `contacts` | + `owner_id`, `team_id`, `profile jsonb`, `profile_updated_at`; **− `phone`, `email`, `external_refs`** and their indexes | Identities move to `contact_identities`; the migration copies any existing values before dropping. The existing `locale` column is what the API returns as `language` |
| `conversations` | + `owner_id` (denormalised customer owner), `team_id`, `waiting_since`, `sla_due_at`, `first_response_at`, `summary jsonb` | Visibility on one row; response targets; the rolling summary |
| `messages` | `status` check adds `sending` ([03](03-whatsapp.md) §7); + `kind` (`message` · `note` · `event`), `type`, `origin` (`customer` · `inbox` · `phone_app` · `history` · `system` · `ai`), `author_user_id`, `transcript jsonb`, `location jsonb`, `template jsonb`, `reply_to_id`, `reactions jsonb`, `referral jsonb`, `pricing jsonb`, `event jsonb`, `delivered_at`, `read_at`. Unique external id becomes `(tenant_id, external_id)` | WhatsApp message ids are globally unique; history import and a live webhook can deliver the same id |
| `leads` | **− `stage`, `next_action_at`** and the index on them; + `pipeline_id`, `stage_id` (not null), `stage_entered_at`, `team_id`, `score_signals jsonb` | Configurable pipelines. Stage history is `activities` with `kind = 'stage_change'` |
| `v_lead_funnel` | Rewritten over `pipeline_stages.category` | It depended on the dropped `stage` column |

Nothing reads the dropped columns yet — the inbox and CRM code does not exist — which is what makes
this the cheap moment to change them.

---

## 4. Visibility

### Session settings

`db/session.py` gains two parameters: `tenant_session(tenant_id, *, user_id=None, scope="all")`
issues `set_config('app.user_id', …, true)` and `set_config('app.scope', …, true)` next to the
existing `app.tenant_id`. Transaction-local, so a pooled connection cannot carry a user into the
next request. `tenant_ctx` derives `scope` from the membership role; the worker keeps the default.

### Functions (all `stable`, `search_path` pinned; the last three `security definer`)

| Function | Returns |
|---|---|
| `app.current_user_id()` | `nullif(current_setting('app.user_id', true), '')::uuid` |
| `app.visible_owner_ids()` | `null` for scope `all`; `{me}` for `own`; `{me} ∪ members of my teams` for `team` |
| `app.my_team_ids()` | Team ids the current user belongs to |
| `app.pool_visible()` | `true` for scope `all`; otherwise `sales_settings.unassigned_visible_to_sales` (default true) |

Every policy wraps them as `(select app.fn())`, which Postgres evaluates once per statement as an
InitPlan instead of once per row. Policies read `memberships`, `teams` and `team_members` only through
these SECURITY DEFINER functions — the recursion rule from DealerAI OS migration 0004.

### Policies

| Table | Visible when (in addition to `app.has_tenant_access(tenant_id)`) |
|---|---|
| `contacts` | owner in visible owners · or unassigned in my team's pool · or I am assigned one of its conversations |
| `conversations` | `owner_id` in visible owners · or `assigned_to = me` · or unassigned in my team's pool |
| `leads` | `owner_id` in visible owners · or unassigned in my team's pool |
| `tasks` | `assignee_id` in visible owners |
| `messages`, `ai_suggestions`, `conversation_reads` | the parent conversation is visible (`exists` over `conversations`, itself filtered) |
| `contact_identities` | the parent contact is visible |
| `activities` | the parent lead or contact is visible |
| `notifications`, `push_subscriptions` | `user_id = app.current_user_id()` |
| everything else | tenant only (unchanged) |

Example, `conversations`:

```sql
create policy tenant_visibility on conversations
  using (
    app.has_tenant_access(tenant_id)
    and (
      (select app.visible_owner_ids()) is null
      or owner_id = any ((select app.visible_owner_ids()))
      or assigned_to = (select app.current_user_id())
      or (owner_id is null and assigned_to is null
          and team_id = any ((select app.my_team_ids()))
          and (select app.pool_visible()))
    )
  )
  with check (app.has_tenant_access(tenant_id));
```

`WITH CHECK` stays tenant-only on purpose. Reassigning a conversation to a colleague makes it
invisible to a salesperson; a visibility check on the new row would make that update fail.
*Who may reassign* is a permission, enforced in the route; *who may see* is RLS.

### Single writers

| Function (`security definer`, granted to `dealerai_app` only) | Does, in one transaction |
|---|---|
| `app.route_whatsapp(phone_number_id, account_id)` | Webhook routing before any tenant context exists → `(tenant_id, channel_id)` |
| `app.reassign_contact(contact_id, new_owner, actor)` | Contact owner, open conversations (`owner_id`, `assigned_to`), open leads, open tasks; event messages; `audit_log` |
| `app.merge_contacts(keep_id, merge_id, actor)` | Moves identities, conversations, leads, tasks, activities; deletes the merged contact; `audit_log` |

An invariant test asserts `conversations.owner_id = contacts.owner_id` after every write path.

### Browser roles

```sql
revoke all on all tables in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
revoke execute on function app.tenants_for_user(uuid) from authenticated;
```

CI asserts `has_table_privilege('authenticated', t, 'select')` is false for every table in `public`.

### The visibility test matrix

Extends `tests/test_tenant_isolation.py`. Tenant A: owner **O**, manager **M** (team Local),
salespeople **S1** and **S2** (Local) and **X** (Export). Tenant B: one of everything. Rows in every
owner-bearing and child table, including one of S2's conversations assigned to S1 (cover).

| Viewer | S1's | S2's | S2's conv. covered by S1 | X's | Local pool | Export pool | Tenant B |
|---|---|---|---|---|---|---|---|
| O | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| M | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ |
| S1 | ✓ | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ |
| X | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ |
| S1, pool off | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| worker (`all`) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |

Run twice: directly under `tenant_session`, and through every list endpoint of the API. A control
case connects as `service_role` and must see tenant B, proving the test can fail.

---

## 5. Live-update triggers

`after insert or update` triggers on `conversations`, `messages`, `ai_suggestions`, `leads`, `tasks`,
`notifications` and `channels` call `pg_notify('rt', …)` with ids plus `owner_id`, `assigned_to` and
`team_id` for the SSE filter. In a trigger it cannot be forgotten by a new code path.

Bulk work sets `set local app.suppress_rt = 'on'` — the history import writes thousands of messages —
and emits a single `conversation.updated` per conversation when a chunk commits.

---

## 6. Indexes

Only the ones the Phase 1 queries need ([06](06-api-contract.md)):

| Index | Serves |
|---|---|
| `conversations (tenant_id, assigned_to, status, last_message_at desc)` | Inbox "Mine" |
| `conversations (tenant_id, team_id, status, last_message_at desc) where assigned_to is null` | Inbox "Unassigned" |
| `conversations (tenant_id, sla_due_at) where waiting_since is not null` | Response-target sweep |
| `conversations (tenant_id, owner_id)` · `contacts (tenant_id, owner_id)` · `leads (tenant_id, owner_id)` | Visibility and per-rep dashboards |
| `leads (tenant_id, pipeline_id, stage_id)` | Pipeline board |
| `messages (tenant_id, conversation_id, created_at desc)` | Thread, newest first |
| `messages` full-text over `coalesce(body,'') || ' ' || coalesce(transcript->>'text','')`, `simple` config | Inbox search, Arabic included |
| `contact_identities (tenant_id, kind, value)` unique | Identity resolution |
| `tasks (tenant_id, assignee_id, status, due_at)` | My day, Tasks |
| `memberships (tenant_id, last_assigned_at) where accepting_chats` | Round-robin |

`simple`, not a language-specific configuration, because one tenant's messages mix Arabic, English
and French; stemming for one language mangles the other two.

---

## 7. Retention and personal data

| Data | Kept | Then |
|---|---|---|
| Messages, transcripts, identities, contacts | Tenant setting, default 24 months after last activity | Purged nightly (`pg_cron`, existing job) |
| Message media objects | Same as their message | Deleted by a worker job — `pg_cron` cannot call the Storage API |
| `ai_suggestions` | 12 months | Aggregated into daily acceptance rows, detail dropped |
| `notifications` | 90 days | Deleted |
| `webhook_deliveries` | 14 days (existing) | Deleted |
| `events`, finished (`done`, `failed`) | 14 days, as the webhook body they came from | Deleted — a payload can be the raw inbound message |

Per customer: `GET /v1/customers/{id}/export` (admin) returns the record, identities, messages and
media links; `DELETE /v1/customers/{id}` (owner/admin) cascades and writes `audit_log` — the PDPL
export and erasure paths. Erasure also deletes every event and raw webhook body that names the
customer, by our ids or by their identities as the platform writes them (`app.erase_contact`,
migration 0012).

---

## 8. Seed data (local only)

`apps/api/src/dealerai/scripts/seed_sales.py`, run by `npm run db:seed`. A script rather than SQL
because every timestamp is relative to now, so the inbox always looks live. Contents: [01](01-architecture.md) §7.
It refuses to run unless `ENV=local`, like the test suite's DSN check.

---

## 9. Adding a sales table — additions to the DealerAI OS 03 §6 checklist

1. Decide its visibility class: owner-bearing (owner column, visibility policy, a matrix row), child
   (`exists` parent policy), user-private, or tenant-wide.
2. If the inbox or dashboards should react to it, add the live-update trigger.
3. If it holds customer data, add it to the retention job and the customer export.
