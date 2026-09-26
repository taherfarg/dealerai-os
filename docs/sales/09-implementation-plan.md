# Sales — Implementation plan

> **For agentic workers:** implement **slice by slice**. Each slice has its own plan file under
> [`plans/`](plans/), written at pickup so it reflects the code as it actually is by then, and
> executed with `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
> Steps in those files use checkbox syntax for tracking.

**Goal:** ship Phase 1 of [00-prd.md](00-prd.md) — every conversation on Pollux's WhatsApp number in
one inbox and one customer record, an AI copilot that drafts inventory-true replies for a person to
send, and a manager who can see who is waiting.

**Architecture:** new routes, handlers and agents inside the existing DealerAI OS services; all app
data through FastAPI under database-enforced visibility; live updates over Postgres NOTIFY to SSE;
WhatsApp through the Cloud API with coexistence ([01-architecture.md](01-architecture.md)).

**Tech stack:** Python 3.12 · FastAPI · asyncpg · Pydantic v2 · APScheduler · pytest ·
Postgres 17 + pgvector · Gemini through the existing gateway · Next.js 16 · React 19 · TypeScript ·
Tailwind v4 · shadcn/ui · TanStack Query · Playwright · uv · ruff · mypy.

---

## Slices

Each one ends in something demonstrable. Weeks are calendar estimates from a week-1 start.

| # | Slice | Weeks | Scope | Exit criterion | Plan |
|---|---|---|---|---|---|
| **S0** | Foundation | 1 | Migration `0006_sales_core`, teams and the manager role, visibility in the session and RLS, `/v1/me`, members and teams routes, generated frontend types, app shell with React Query and the message catalogue, seed script, CI additions | The visibility matrix test is green; `npm run db:seed` then the shell opens as any seeded user; `npm run api-types` produces no diff | [`plans/s0-foundation.md`](plans/s0-foundation.md) |
| **S1** | WhatsApp channel | 2–3 | Connector, webhook route and signature, identity resolution, ingest, media download, transcription, statuses, template sync, send with the window rule, the local simulator | A simulated inbound voice note lands as a message with a transcript; a send goes out through the mock and through Meta's test number | written at pickup |
| **S2** | Inbox | 3–5 | Inbox endpoints, thread, composer, internal notes, assignment engine, business hours and response targets, SSE stream, notifications | A salesperson answers a customer end to end in the UI while the manager watches the timer | written at pickup |
| **S3** | CRM | 5–7 | Customers list and 360, profile editing, reassign, merge, pipelines and stages, leads with scoring input, tasks, My day | A lead goes from new to won, with tasks, in the UI | written at pickup |
| **S4** | AI copilot | 7–9 | Intent, knowledge upload and retrieval, drafts with guards, outcomes, profile and scoring, summaries, follow-ups, eval harness | The gates in [04](04-ai-copilot.md) §9 pass on the synthetic set and drafts appear in the composer | written at pickup |
| **S5** | Coexistence | 8–10 | Embedded Signup, echoes, history import, contacts sync, imported-customer assignment | Pollux's real number is connected and 180 days of history are in the inbox | written at pickup |
| **S6** | Manager view | 10–11 | Dashboard, daily brief, settings screens | A manager runs a morning entirely from the dashboard | written at pickup |
| **S7** | Pilot readiness | 12–14 | Installable app and push, accessibility and Arabic pass, Playwright suite, staging, pilot with two reps | The eight success criteria in [00](00-prd.md) §7 are measured on Pollux | written at pickup |

**Only S5 depends on Meta.** Everything before it runs on the simulator, the mock connector and
Meta's test number.

---

## The parallel track: Meta (founder, not code)

| Week | Step |
|---|---|
| 1 | Business verification of the Pollux Motors portfolio; create the developer app; test number with up to five recipients |
| 2–3 | Record the two app-review videos against the test number; request advanced access to both WhatsApp permissions; submit |
| On approval | Tech Provider enrolment; Embedded Signup configuration with app onboarding; payment method; three utility templates in AR/EN/FR |

Details and the operating rules for the sales team: [03-whatsapp.md](03-whatsapp.md) §2.

---

## Critical path

```
S0 ─► S1 ─► S2 ─► S3 ─► S4 ─────────► S6 ─► S7
                   │                          ▲
Meta verification ─┴─► app review ─► S5 ──────┘
   (week 1, external, weeks long)
```

---

## Definition of done, every task

1. Tests pass: `npm run test`, and `npm run test:guards` stays at 100% branch coverage.
2. `npm run lint` and `npm run typecheck` clean (ruff, mypy --strict).
3. `npm run check:web` clean (tsc, `check:rtl`, eslint).
4. The cross-tenant isolation test **and** the visibility matrix test are green.
5. Every new endpoint has a permission test and a visibility test.
6. The task's acceptance check reproduces on a fresh checkout.
7. Conventional commit, one per task.

---

## Working agreements

- **Branch:** `sales/phase-1`, in this worktree. Do not commit to `main`.
- **Database:** Docker Desktop must be running before `npm run db:up`; Postgres is on port 54332.
  The test suite refuses any DSN that is not localhost — never point it at Supabase.
- **New tables** follow the checklist in [02](02-data-model.md) §9 (visibility class, live-update
  trigger, retention, export).
- **Models** are named only in `ai/models.py`; prompts are `.md` files under `ai/prompts/`.
- **Imports:** `agents` may not import `connectors`; only `db/session.py` acquires a connection;
  `guards` import nothing but `db/` and the standard library. CI enforces all three.
- **Frontend:** no `fetch` in components, no Supabase table access, every string in the catalogue,
  every type from the generated schema.
- **Secrets:** never in a commit, a log line or a chat message. `.env` files stay gitignored.
