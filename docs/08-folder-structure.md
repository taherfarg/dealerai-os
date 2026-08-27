# Folder Structure

**Status:** Approved · Depends on: [01-system-architecture.md](01-system-architecture.md)

One repository. Two deployables (`web`, `api`) plus a worker that shares the `api` image.

```
dealerai-os/
├── apps/
│   ├── web/                  Next.js 15 dashboard
│   └── api/                  FastAPI + worker (one Python package)
├── packages/
│   └── api-client/           TypeScript client generated from the OpenAPI schema
├── supabase/
│   ├── migrations/           0001_init.sql, 0002_growth.sql — source of truth
│   ├── seed/                 dev fixtures: 2 tenants, 20 vehicles, sample threads
│   └── config.toml
├── templates/                creative templates (HTML/CSS) — see § 4
├── docs/                     this documentation set
├── scripts/                  one-off ops scripts
├── .github/workflows/
├── docker-compose.yml        local: postgres+pgvector, minio, playwright
└── package.json               task runner (npm scripts) + web workspace
```

---

## 1. `apps/api` — the Python service

```
apps/api/
├── pyproject.toml            uv-managed; ruff + mypy configured here
├── Dockerfile                one image, two entrypoints
└── src/dealerai/
    ├── main.py               FastAPI app factory
    ├── worker.py             worker entrypoint
    ├── config.py             pydantic-settings, all env in one place
    ├── deps.py               current_user, tenant_ctx
    │
    ├── db/
    │   ├── session.py        tenant_session() — the ONLY place a connection is acquired
    │   ├── models.py         Pydantic row models
    │   └── queries/          plain SQL per domain: vehicles.py, content.py, inbox.py, …
    │
    ├── routes/
    │   ├── brand.py vehicles.py content.py channels.py inbox.py crm.py
    │   ├── runs.py approvals.py analytics.py documents.py ads.py tenants.py
    │   ├── internal.py
    │   └── webhooks/
    │       ├── meta.py whatsapp.py tiktok.py
    │       └── verify.py     signature verification, shared
    │
    ├── orchestrator/
    │   ├── planner.py        goal → task DAG (the Director's plan call)
    │   ├── executor.py       dispatch ready tasks, resolve from_task, commit results
    │   └── gate.py           autonomy check per task
    │
    ├── agents/
    │   ├── base.py           Agent protocol, AgentContext, AgentResult
    │   ├── registry.py       name → agent, with its tools and model tier
    │   ├── director.py
    │   ├── content/          brand_ingest · enrichment · strategist ·
    │   │                     creative_director · copywriter · image · video ·
    │   │                     publisher · community
    │   ├── sales/            sales · intent · lead_intel · followup
    │   └── growth/           ads · market · competitor · inventory_intel ·
    │                         analytics · learning
    │
    ├── tools/
    │   ├── registry.py       @tool decorator, schema generation, tracing
    │   ├── inventory.py brand.py memory.py content.py publish.py
    │   └── message.py crm.py ads.py analytics.py research.py
    │
    ├── guards/               pure functions, heavily unit-tested
    │   └── inventory.py price.py brand.py budget.py pii.py rate.py
    │
    ├── connectors/
    │   ├── base.py           SocialConnector / AdsConnector protocols + DTOs
    │   ├── mock.py           ships first; every other connector is tested against its suite
    │   ├── meta.py whatsapp.py tiktok.py google.py
    │   ├── crypto.py         envelope encryption for stored tokens
    │   └── registry.py       platform → connector, health checks
    │
    ├── ai/
    │   ├── gateway.py        model routing, cache breakpoints, cost, trace writes
    │   ├── embeddings.py
    │   ├── retrieval.py      hybrid vector + FTS with RRF
    │   ├── schemas.py        structured-output Pydantic models
    │   └── prompts/          one .md per agent, layered for cache stability
    │       ├── _rules.md     the hard rules injected into every agent
    │       ├── director.md sales.md copywriter.md creative_director.md …
    │
    ├── media/
    │   ├── compositor.py     Playwright HTML → PNG at each aspect ratio
    │   ├── video.py          FFmpeg reel assembly
    │   ├── vision.py         photo QA, angle detection, ranking
    │   ├── matting.py        rembg background removal
    │   └── storage.py        Supabase Storage paths and signed URLs
    │
    ├── events/
    │   ├── bus.py            emit() — transactional with the caller
    │   ├── worker.py         claim loop (SKIP LOCKED), retries, reaper
    │   ├── scheduler.py      APScheduler crons — only ever emits events
    │   └── handlers/         inventory.py content.py inbox.py crm.py ads.py system.py
    │
    └── core/
        ├── errors.py         problem+json exception handlers
        ├── logging.py        structlog with tenant_id / run_id / trace_id
        ├── security.py       JWT verify, HMAC, constant-time compare
        ├── idempotency.py
        ├── money.py          minor units — no float ever touches a price
        └── locale.py         AR/EN/FR, RTL helpers
```

### Rules that keep this from rotting

- **`db/session.py` is the only module that acquires a connection.** A grep-based CI check
  fails the build on `pool.acquire()` anywhere else. This is what makes the
  `SET LOCAL app.tenant_id` guarantee actually hold.
- **`agents/` may not import `connectors/`.** Agents call tools; tools call connectors.
  Enforced by an import-linter contract. Without it, in three months an agent calls the
  Meta API directly and the guard layer is bypassed.
- **`guards/` imports nothing but `db/` and stdlib.** Guards must be trivially testable
  and impossible to accidentally make model-dependent.
- **Prompts are `.md` files, not string literals.** They are reviewed in diffs, and their
  layering is what makes prompt caching work.
- One file per agent, one per tool group, one per connector. Files that change together
  live together.

---

## 2. `apps/web` — the Next.js app

```
apps/web/
├── app/
│   ├── (auth)/               login · signup · accept-invite
│   ├── (app)/[tenant]/
│   │   ├── page.tsx          Command Center — the daily brief and recommendations
│   │   ├── inventory/        list · [id] · import
│   │   ├── content/          calendar · [id] · generate
│   │   ├── inbox/            list · [conversationId]
│   │   ├── leads/            list · [id] (Customer 360)
│   │   ├── analytics/
│   │   ├── approvals/
│   │   ├── brand/
│   │   ├── runs/[id]/        plan, tasks, traces, cost — the "why did it do that" view
│   │   └── settings/         channels · team · autonomy · billing
│   └── api/                  route handlers that attach the JWT and proxy to FastAPI
│
├── components/
│   ├── ui/                   shadcn primitives
│   ├── inventory/ content/ inbox/ leads/
│   └── agent/                RunStream (SSE) · TaskDag · ApprovalCard · CostBadge
│
├── lib/
│   ├── supabase/             client.ts (browser) · server.ts (RSC)
│   ├── api.ts                re-export of packages/api-client
│   ├── format.ts             money, dates in tenant timezone, RTL text direction
│   └── hooks/                useRealtimeInbox, useRunStream, useApprovals
│
└── messages/                 UI i18n: en.json, ar.json
```

**The `[tenant]` segment is in the URL**, not in a cookie. A user in two tenants can have
both open in two tabs, and every link is unambiguous about which workspace it belongs to.

**`packages/api-client` is generated**, never hand-written:

```bash
npm run api-types   # OpenAPI from FastAPI → TypeScript client
```

Hand-written API types drift from the server within one sprint and the drift is silent.

---

## 3. Tests

```
apps/api/tests/
├── conftest.py                    fixtures: two seeded tenants, mock connectors
├── test_tenant_isolation.py       ← blocks merge; see docs/03 § 2
├── test_import_contracts.py       agents↛connectors, session-acquire grep
├── guards/                        one file per guard, every branch
├── tools/                         each tool against seeded data
├── connectors/
│   ├── test_contract.py           the shared suite every connector must pass
│   └── test_meta.py …             recorded HTTP fixtures
├── agents/                        each agent with a stubbed gateway
├── routes/                        happy path + 404-not-403 + idempotency replay
├── media/                         golden-image comparison per template per ratio
└── evals/
    ├── golden_messages.jsonl      200 real inbound messages, AR/EN/FR, labelled
    ├── test_intent.py             accuracy gate
    ├── test_no_hallucinated_facts.py   zero-tolerance price/availability gate
    └── judge.py                   LLM-judge scoring for sales replies
```

`npm test` runs unit and integration. `npm run eval` runs the model-dependent suites — they
cost money and run on PRs that touch `agents/`, `ai/`, or `prompts/`.

---

## 4. `templates/` — creative templates

```
templates/
├── _tokens.css               brand custom properties every template consumes
├── _base.css                 reset, safe areas, RTL logical properties
├── hero/          index.html preview.png manifest.json
├── offer/         …
├── specs_card/    …
├── comparison/    …
├── feature/       …
├── educational/   …
├── story_teaser/  …
└── carousel_spec/ …
```

`manifest.json` declares the slots the compositor must supply and the aspect ratios the
template supports; it is what seeds `creative_templates.slots`. A designer can add a
template without touching Python — that is the whole point of rendering with a browser.

---

## 5. Naming and conventions

| Thing | Convention |
|---|---|
| Python | `snake_case`, `ruff` + `mypy --strict` on `src/` |
| TypeScript | `camelCase` values, `PascalCase` components, `strict: true` |
| SQL | `snake_case`, plural tables, `*_minor` for money, `*_at` for timestamps |
| Events | `noun.verb_past` — `content.published`, `lead.created` |
| Agents | `snake_case` names matching the file: `content_strategist` |
| Tools | `verb_noun` — `search_inventory`, `send_whatsapp` |
| Branches | `m3/content-factory`, `fix/whatsapp-window` |
| Commits | Conventional Commits |

Environment variables are declared once in `config.py` and nowhere else. A `.env.example`
is generated from it, so a missing variable fails at startup with a named error instead of
at 2am with a `KeyError`.
