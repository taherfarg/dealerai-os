# DealerAI OS — Product Documentation

> **An autonomous AI marketing and sales department for automotive businesses.**
> Not an AI social media tool. The difference is the whole product.

---

## What this is

DealerAI OS runs the full commercial loop for a car dealer or exporter:

```
Inventory → Market Research → Strategy → Content → Creative → Publishing
    → Engagement → Leads → Sales → Ads → Analytics → Learning → next cycle
```

A **Growth Director** orchestrator decomposes business goals into work for specialist
agents. Every tenant gets its own brain: brand identity, inventory, customers, content
history, and a playbook that improves with use.

---

## Reading order

| # | Document | Read it for |
|---|----------|-------------|
| 00 | [PRD](00-prd.md) | What we're building, for whom, why it wins, what we refuse to build |
| 01 | [System Architecture](01-system-architecture.md) | Components, runtime topology, connectors, model gateway, media pipeline |
| 02 | [Agent Architecture](02-agent-architecture.md) | Agent contract, orchestrator loop, tools, guardrails, autonomy modes, registry |
| 03 | [Database Schema](03-database-schema.md) | Tenancy model, RLS, table design decisions |
| 04 | [Memory Architecture](04-memory-architecture.md) | The eight brains, what is RAG vs. what is a SQL join, the learning loop |
| 05 | [Workflows](05-workflows.md) | Event catalog + every end-to-end flow with failure handling |
| 06 | [MVP Scope](06-mvp-scope.md) | Phase 1 in/out, acceptance criteria, deliberate deferrals |
| 07 | [API Design](07-api-design.md) | Routes, auth, SSE, webhooks, errors, idempotency |
| 08 | [Folder Structure](08-folder-structure.md) | Monorepo layout, what lives where |
| 09 | [Implementation Plan](09-implementation-plan.md) | Milestones → tasks → acceptance tests. Build from this. |

Runnable schema: [`supabase/migrations/0001_init.sql`](../supabase/migrations/0001_init.sql) (MVP)
and [`0002_growth.sql`](../supabase/migrations/0002_growth.sql) (ads + market intelligence).
**The SQL is the source of truth for the data model.** Doc 03 explains it; it does not
duplicate it.

---

## Locked decisions

These are settled. Changing one invalidates several documents — say so explicitly if you do.

| Decision | Choice | Why |
|---|---|---|
| Agent runtime | **Python 3.12 + FastAPI** service | Long-running jobs, best AI/vision/eval ecosystem, clean worker story |
| UI | **Next.js 16 (App Router) + TypeScript** | Dashboard-heavy product; Next is the right tool. Scaffolds at 16.3.4 — note the middleware file convention is deprecated, so the auth gate is `proxy.ts`. |
| Datastore | **Supabase** — Postgres 17 + pgvector + Auth + Storage | RLS on `tenant_id` from line one; auth and storage solved |
| Tenant isolation | **Row Level Security, always on, no exceptions** | Tenant leakage is the one bug that kills the company |
| Model provider | **Google Gemini** (`google-genai`) | Single provider. `ai.gateway.complete()` is the only seam, so swapping again is 2 files. |
| Reasoning model | `gemini-2.5-pro` | Orchestrator, strategy, ads decisions. **GA only** - `gemini-3-pro-preview` was shut down while still the newest Pro. |
| Workhorse model | `gemini-2.5-flash` | Copy, analysis, sales replies |
| Cheap model | `gemini-2.5-flash-lite` | Intent classification, spam, routing. Thinking disabled. |
| Job system | **Postgres `events` outbox + Python worker** (`SKIP LOCKED`) | Redis deferred until throughput demands it — see 01 |
| Creative rendering | **Deterministic compositor, not text-to-image** | Generative models hallucinate badges, grilles, and proportions. Dealers sell *this* car. See 01. |
| Doc language | English | Product surfaces are trilingual (AR/EN/FR); engineering docs are not |

**Tenant zero:** Pollux Motors (UAE dealer/exporter, trilingual catalog) is the design
partner. Every MVP feature must be usable by them in week one, or it is not MVP.

---

## Local development

```bash
cp .env.example .env
npm run db:up        # Postgres 15 + pgvector on :54332
npm run db:migrate
npm run check        # lint + typecheck + tests
npm run api          # http://localhost:8000/internal/health
```

Requires Docker, Node 22+, and [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned in
`apps/api/.python-version`; uv fetches it.

Three things about the local setup that are not obvious:

- **Port 54332, not 54322.** The Supabase CLI default is often already taken by another
  project's stack on the same machine.
- **Postgres 17 locally, matching the Supabase project.** Testing on a different major
  version than production is how you find out about a behaviour change at the worst
  possible moment.
- **`0000_local_shim.sql` runs only when `ENV=local`.** It creates `auth.users`,
  `auth.uid()`, and the `anon` / `authenticated` / `service_role` roles that Supabase
  provides for real. The migrate script skips it in every other environment.
- **npm scripts, not a Makefile.** `make` is not present on a stock Windows box, and the
  repo already needs Node and uv. Adding a third task runner to save typing is not worth
  an install step.

## Deploying the schema to Supabase

Environment variables override `.env`, and the migrate script skips
`0000_local_shim.sql` whenever `ENV` is not `local`, so deploying is one command
with two overrides:

```bash
cp .env.staging.example .env.staging   # fill in the pooler DSN, then:
npm run db:migrate:staging
```

`.env.staging` is gitignored. The credential lives in a file, never in a shell
command, a chat message, or a commit — anywhere it lands in a scrollback is
somewhere it can be read later. If one has been exposed, rotate it in
**Settings → Database → Reset database password** before doing anything else.

Note there is no `DATABASE_URL` in `.env.staging`, only
`MIGRATION_DATABASE_URL`. Only the migration runner should reach staging from a
laptop; the application connects as `dealerai_app` from its own deployment with
its own secret.

Then the one ops step per environment, which is the only thing not in version
control because it carries a secret:

```sql
alter role dealerai_app login password '<from your secret manager>';
```

Deliberately **not** using `supabase db push`: the CLI expects timestamped
migration filenames, and our own runner already tracks applied migrations with
checksums and refuses to re-run an edited one. Two migration systems over one
directory is how a schema drifts.

**Never point `DATABASE_URL` or `MIGRATION_DATABASE_URL` in `.env` at a real
project.** The test suite issues `delete from tenants`, which cascades to every
row a dealership owns. `tests/conftest.py` refuses to run unless both DSNs are
localhost, but the discipline is the real protection.

## Status

| Area | State |
|---|---|
| Documentation | Complete — this set |
| Schema | Applied locally **and to Supabase** (`fqajkmjrwbthmpendojj`, ap-northeast-1, PG 17.6). RLS forced on all 35 tenant tables, all 3 views `security_invoker`, security linter clean except one documented warning. |
| **M0 Foundation** | **complete** — T0.1–T0.8 |
| **M1 Tenancy** | **complete** — T1.1–T1.5. Shell, auth gate, RTL, workspace switcher, approvals queue. |
| Known gap | **A real sign-in has never been exercised.** Supabase email confirmation is ON and the built-in SMTP rate-limits immediately, so no test user could be created. The gate, redirect and session plumbing are verified; the credential round trip is not. Confirm a user (or disable confirmation on the dev project) and log in once. |
| M2 Inventory | API side complete — T2.1 CRUD, T2.3 photo QA, T2.4 CSV import, T2.5 enrichment, T2.6 stock report · T2.2 upload needs a Storage bucket · inventory screens need a working sign-in |
| Tests | 301 passing, 8 skipped · live evals green (`npm run eval:gateway`, `npm run eval:vision` — deselected by default, they spend money) |
| Supabase | Schema live. **Outstanding:** `alter role dealerai_app login password '…'` before the app can connect. |
| Meta / WhatsApp / TikTok app review | Not started — **long lead time, start now** |

---

## Glossary

- **Tenant** — one dealership or exporter workspace. `tenant_id` is on every row.
- **Company Brain** — the union of a tenant's brand, inventory, customer, content, and learning memory.
- **Playbook** — a tenant's versioned, human-readable file of learned rules. The output of the learning loop.
- **Agent run** — one orchestrated unit of work, with a DAG of tasks, a trace, and a cost.
- **Autonomy mode** — Copilot / Assisted / Autopilot. Controls what an agent may do without a human.
- **Connector** — an adapter that hides one external platform's API behind our capability interface.
