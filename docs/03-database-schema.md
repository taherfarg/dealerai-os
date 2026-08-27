# Database Schema

**Source of truth:** [`supabase/migrations/0001_init.sql`](../supabase/migrations/0001_init.sql)
and [`0002_growth.sql`](../supabase/migrations/0002_growth.sql).

This document explains the model and the decisions. It deliberately does **not** repeat
column lists — a schema described in two places drifts in one of them.

---

## 1. Map

```
tenants ─┬─ memberships ── auth.users ── profiles
         ├─ brand_profiles ── brand_assets
         ├─ creative_templates
         │
         ├─ vehicles ─┬─ vehicle_media
         │            └─ vehicle_price_history
         │
         ├─ channels  (instagram | facebook | whatsapp | tiktok | meta_ads | ...)
         │
         ├─ content_items ─┬─ content_copy      (one row per locale)
         │                 ├─ content_assets    (one row per aspect ratio)
         │                 └─ publications ── content_metrics
         │
         ├─ contacts ─┬─ conversations ── messages
         │            └─ leads ─┬─ activities
         │                      └─ deals
         │
         ├─ agent_runs ─┬─ agent_tasks ── agent_traces
         │              └─ approvals
         ├─ events                        (queue + outbox + audit of intent)
         ├─ webhook_deliveries            (raw inbound, pre-parse)
         │
         ├─ documents ── doc_chunks       (RAG)
         ├─ memories                      (learned facts)
         ├─ playbooks                     (versioned, human-approved rules)
         │
         └─ [0002] ad_entities ── ad_metrics_daily, ad_changes
                   competitors ── competitor_observations
                   market_signals, experiments
```

---

## 2. Tenancy — the only part that cannot be wrong

Every tenant-owned table carries `tenant_id uuid NOT NULL` and has RLS **enabled and
forced**. `FORCE` matters: without it, the table owner (which is what migrations run as)
silently bypasses its own policies.

### One policy, applied uniformly

```sql
create policy tenant_isolation on <table>
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));
```

It is generated in a loop over a table list rather than written 28 times. A hand-written
per-table policy is how one table ends up with a subtly different predicate, and that one
table is the leak.

### Two access paths, one function

```sql
create function app.has_tenant_access(t uuid) returns boolean as $$
  select
    coalesce(nullif(current_setting('app.tenant_id', true), '')::uuid = t, false)
    or exists (select 1 from memberships m
               where m.tenant_id = t and m.user_id = auth.uid());
$$;
```

| Path | Who | How the tenant is established |
|---|---|---|
| Browser → Supabase | `supabase-js` with the user's JWT | `auth.uid()` → `memberships` |
| FastAPI → Postgres | Role `dealerai_app` | `SET LOCAL app.tenant_id = '<uuid>'` at transaction start |

The two branches never both apply: in the backend path `auth.uid()` is null, in the
browser path the GUC is unset.

### The rule that makes it hold

> **The `service_role` key never appears in a request path.** It exists for migrations.

`service_role` bypasses RLS entirely. One careless query with it is a cross-tenant breach
that no amount of application-layer care prevents. So the backend connects as
`dealerai_app`, a role created with `NOBYPASSRLS` — if the application code forgets to
scope a query, the database returns zero rows instead of another dealer's customers.

`SET LOCAL` (not `SET`) is required: it is transaction-scoped, so a pooled connection
cannot leak a tenant context into the next request. This is enforced by a single session
helper:

```python
@asynccontextmanager
async def tenant_session(pool, tenant_id: UUID):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', $1, true)", str(tenant_id))
        yield conn
```

Nothing else in the codebase opens a connection. Enforced by a lint rule and a
grep-based CI check.

### The two tables with no RLS, and why

`events` and `webhook_deliveries` are deliberately excluded. They are isolated by `GRANT`
instead — no browser role can reach them at all.

The reason is structural, not convenience. The worker claims events **before** it knows
which tenant they belong to; that claim is the one legitimate cross-tenant read in the
system. Under a `tenant_id` policy it would return zero rows and the queue would silently
stop. Likewise, a webhook body is persisted before it has been resolved to a channel, so
`tenant_id` is still null at insert time and any tenant predicate rejects the row.

The discipline this depends on: the worker reads `tenant_id` off the claimed event and does
every subsequent statement inside `tenant_session(tenant_id)`. The claim query is the only
place in the codebase that touches `events` without a tenant context, and it lives in
`events/worker.py`. Everything downstream of it is scoped.

### The CI test that must exist

Seed tenants A and B with a row in every table. Under A's context, assert each table
returns exactly A's rows and zero of B's — once through the JWT path, once through the
`dealerai_app` path. This test blocks merge. It is the single highest-value test in the
repository.

---

## 3. Design decisions

**Money is `bigint` minor units plus `currency char(3)`.** `price_minor = 6600000` is
AED 66,000.00. No floats anywhere near a price. Every display formats at the edge.

**`vehicles.min_price_minor` is the discount floor and is never sent to a
customer-facing agent.** It is filtered out of the `VehicleSummary` DTO that tools return.
The Sales Agent negotiates against a *limit it is told* ("you may go to X"), never against
a floor it can read and reason its way past.

**`text` + `CHECK` instead of Postgres `enum`.** Adding a value is
`alter table ... drop constraint ... add constraint ...`; removing one is possible.
`ALTER TYPE` cannot remove a value at all, and enum columns are painful in `jsonb`
round-trips and in the ORM layer. The trade is losing a little type safety at the
database edge, which Pydantic recovers at the application edge.

**Constrained sets that change often live in `jsonb`, not columns.** `vehicles.specs`,
`brand_profiles.tone`, `tenants.autonomy_rules`. Anything we filter or aggregate on gets a
real column; anything we only read whole stays in `jsonb`. `specs` gets a GIN index when a
query needs it, not before.

**`content_copy` is one row per locale, not three columns.** Adding French is a row, not
a migration. Same reasoning for `content_assets` per aspect ratio.

**`publications` sits between content and channels** because one content item goes to
Instagram *and* Facebook *and* TikTok with different external IDs, permalinks, and failure
states. Putting `external_id` on `content_items` would have been wrong within a week.

**`events` is one table doing three jobs** — queue, outbox, and audit of intent. It gets a
partial index for claiming (`where status = 'pending'`), a partial unique index for
deduplication, and a partial index for the stuck-job reaper. Three narrow indexes on one
table beat three tables.

**`ad_entities` is self-referencing** rather than `campaigns` / `ad_sets` / `ads`. All
three levels have identical shape and every query walks the tree. See the comment in
`0002_growth.sql`.

**Views use `security_invoker = true`.** Without it a view executes as its owner and
bypasses the RLS of its base tables — a silent, total tenant leak through something that
looks like a convenience. Any new view must set it; the CI cross-tenant test covers views
too.

**No soft deletes.** `status` columns model lifecycle (`archived`, `sold`, `closed`).
A `deleted_at` that every query must remember to filter is a bug generator. Real deletes
cascade; the `audit_log` retains what happened.

---

## 4. Indexing

Present from day one because they cover the actual query shapes:

| Index | Serves |
|---|---|
| `vehicles (tenant_id, status, listed_at)` | Inventory list, stock-age report |
| `content_items (tenant_id, status, scheduled_at)` | Calendar, publish-due sweep |
| `conversations (tenant_id, status, last_message_at desc)` | Inbox |
| `messages (tenant_id, conversation_id, created_at)` | Thread view |
| `leads (tenant_id, next_action_at) where stage not in ('won','lost')` | Follow-up sweep |
| `events (run_after, priority desc, id) where status = 'pending'` | Queue claim |
| `contacts (external_refs) gin` | Webhook → contact resolution by platform ID |
| `doc_chunks / memories hnsw (vector_cosine_ops)` | Retrieval |

Partial indexes carry `WHERE` clauses matching the query, so the queue index stays small
even after a million processed events.

**Add nothing else until `pg_stat_statements` says to.** Every index is a write cost.

---

## 5. Retention

| Data | Kept | Then |
|---|---|---|
| `agent_traces` | 90 days hot | Aggregate to daily cost rows, drop detail |
| `events` (done) | 30 days | Delete |
| `webhook_deliveries` | 14 days | Delete |
| `content_metrics` | Forever at 24h/7d/30d | 1h snapshots dropped after 30 days |
| Customer messages and contacts | Per tenant PDPL setting, default 24 months | Purge on request; export endpoint provided |

Implemented as a nightly `pg_cron` job, not application code.

---

## 6. Adding a table — checklist

1. `tenant_id uuid not null references tenants(id) on delete cascade`
2. `created_at`, and `updated_at` plus the `touch` trigger if it is mutable
3. Add the name to the RLS loop in the migration. The only exception is a table the
   worker must read before a tenant is known — then omit RLS and revoke it from
   `authenticated` and `anon` instead, and say why in a comment
4. Add it to the cross-tenant CI test's table list
5. Money as `*_minor bigint` + `currency`
6. Index on `(tenant_id, <the column you filter by>)`
7. If it holds customer data, add it to the retention job and the export endpoint

New views additionally need `with (security_invoker = true)`.
