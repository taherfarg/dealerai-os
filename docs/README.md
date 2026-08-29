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
| UI | **Next.js 15 (App Router) + TypeScript** | Dashboard-heavy product; Next is the right tool |
| Datastore | **Supabase** — Postgres 15 + pgvector + Auth + Storage | RLS on `tenant_id` from line one; auth and storage solved |
| Tenant isolation | **Row Level Security, always on, no exceptions** | Tenant leakage is the one bug that kills the company |
| Reasoning model | `claude-opus-5` | Orchestrator, strategy, ads decisions |
| Workhorse model | `claude-sonnet-5` | Copy, analysis, sales replies |
| Cheap model | `claude-haiku-4-5` | Intent classification, spam, routing |
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
- **`0000_local_shim.sql` runs only when `ENV=local`.** It creates `auth.users`,
  `auth.uid()`, and the `anon` / `authenticated` / `service_role` roles that Supabase
  provides for real. The migrate script skips it in every other environment.
- **npm scripts, not a Makefile.** `make` is not present on a stock Windows box, and the
  repo already needs Node and uv. Adding a third task runner to save typing is not worth
  an install step.

## Status

| Area | State |
|---|---|
| Documentation | Complete — this set |
| Schema | Applied and tested locally (39 tables, RLS verified) |
| M0 Foundation | T0.1–T0.5 and T0.8 (CI) done · T0.6 model gateway, T0.7 connectors next |
| Tests | 53 passing, including the cross-tenant isolation and event-queue suites |
| Meta / WhatsApp / TikTok app review | Not started — **long lead time, start now** |

---

## Glossary

- **Tenant** — one dealership or exporter workspace. `tenant_id` is on every row.
- **Company Brain** — the union of a tenant's brand, inventory, customer, content, and learning memory.
- **Playbook** — a tenant's versioned, human-readable file of learned rules. The output of the learning loop.
- **Agent run** — one orchestrated unit of work, with a DAG of tasks, a trace, and a cost.
- **Autonomy mode** — Copilot / Assisted / Autopilot. Controls what an agent may do without a human.
- **Connector** — an adapter that hides one external platform's API behind our capability interface.
