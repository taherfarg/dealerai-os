# System Architecture

**Status:** Approved · Depends on: [00-prd.md](00-prd.md)

---

## 1. Component map

```
┌──────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                             │
│  Next.js 16 (App Router, TS, Tailwind)                    │
│  Command Center · Calendar · Inbox · Inventory · Leads · Analytics   │
└───────────────┬──────────────────────────────┬───────────────────────┘
                │ supabase-js (RLS via JWT)    │ fetch → /api/*
                │ reads + simple writes        │ anything with a side effect
                ▼                              ▼
     ┌──────────────────────┐        ┌────────────────────────────────┐
     │ SUPABASE             │◄───────┤ FASTAPI  (api.dealerai)        │
     │ Postgres 17          │  asyncpg│ ├── /v1/*   tenant REST       │
     │ + pgvector           │        │ ├── /v1/runs/{id}/stream (SSE) │
     │ + Auth (JWT)         │        │ ├── /webhooks/*  inbound       │
     │ + Storage (media)    │        │ └── /internal/* svc-to-svc     │
     │ + RLS on tenant_id   │        └───────┬────────────────────────┘
     └──────────┬───────────┘                │ enqueue
                │  LISTEN / poll             ▼
                │                   ┌──────────────────────┐
                └──────────────────►│ WORKER (same image)  │
                                    │ events → handlers    │
                                    │ + APScheduler cron   │
                                    └───────┬──────────────┘
                                            ▼
                              ┌───────────────────────────────┐
                              │ AGENT ORCHESTRATOR            │
                              │ Growth Director + specialists │
                              └───────┬───────────────────────┘
                                      ▼
     ┌────────────────────────────────────────────────────────────────┐
     │ TOOL LAYER  (tenant-scoped, audited, typed)                    │
     │  inventory · brand · memory · content · publish · message      │
     │  · ads · analytics · search · media                            │
     └───────────┬─────────────────────────────┬──────────────────────┘
                 ▼                             ▼
     ┌────────────────────────┐     ┌────────────────────────────┐
     │ CONNECTOR LAYER        │     │ MODEL GATEWAY              │
     │ meta · whatsapp        │     │ reasoning / workhorse /    │
     │ tiktok · google        │     │ fast / vision / embed /    │
     │ web · mock             │     │ image / video              │
     └────────────────────────┘     └────────────────────────────┘
                                                 │
                                    ┌────────────┴────────────┐
                                    │ MEDIA PIPELINE          │
                                    │ compositor (Playwright) │
                                    │ + FFmpeg + rembg        │
                                    └─────────────────────────┘
```

**Two services, one image.** `api` and `worker` are the same Python package with
different entrypoints. They share models, tools, connectors, and config. Deploy them as
separate processes so a slow agent run never blocks an HTTP request.

---

## 2. Request paths

There are exactly three, and every feature is one of them.

### A. Synchronous read — browser to Supabase
Dashboards, lists, detail pages. `supabase-js` with the user's JWT; RLS does the
authorization. **No FastAPI hop.** Fewer moving parts, real-time subscriptions for free.

### B. Side-effecting action — browser to FastAPI
Anything that spends money, touches a third party, calls a model, or must be audited.
Next.js route handler attaches the user's JWT, FastAPI verifies it, resolves the tenant,
and either does the work inline (fast, < 2 s) or enqueues an event and returns a
`run_id` that the client streams over SSE.

```
POST /v1/content/generate → 202 {run_id}
GET  /v1/runs/{run_id}/stream → SSE: task.started, task.completed, run.completed
```

### C. Inbound webhook — platform to FastAPI
Meta comments, Instagram DMs, WhatsApp messages, TikTok callbacks. **Verify signature →
persist raw payload → enqueue event → return 200 in under a second.** Never do work in
the webhook handler; platforms retry aggressively and disable slow endpoints.

---

## 3. Event system

**Decision: Postgres is the queue for v1. No Redis.**

The `events` table is the outbox, the audit log, and the work queue at once. A worker
claims batches with `FOR UPDATE SKIP LOCKED`:

```sql
UPDATE events SET status='processing', locked_at=now(), attempts=attempts+1
WHERE id IN (
  SELECT id FROM events
  WHERE status='pending' AND run_after <= now()
  ORDER BY priority DESC, created_at
  LIMIT 20 FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

Why not Redis: it adds an operational component, a second source of truth, and a lost-job
failure mode, to buy throughput we do not have. Postgres gives us replay, inspection in
the same SQL console as everything else, exactly-once-ish semantics, and transactional
enqueue (the event and the row that caused it commit together — no orphan jobs).

> `ponytail:` Postgres-as-queue. Ceiling is roughly 50–100 jobs/sec on a small instance
> and one poll of latency. **Upgrade trigger:** sustained queue depth above 500, or p95
> pickup latency above 5 s. Then move execution to Redis/ARQ and keep `events` as the
> outbox of record. Do not pre-build this.

Scheduled work (publish at 18:00, fetch metrics at T+24h, daily brief at 07:00) is a row
in `events` with `run_after` in the future, written when the content is scheduled.
Recurring cron lives in APScheduler in the worker and only ever *emits* events.

**Retries:** exponential backoff (`run_after = now() + 2^attempts minutes`), max 5
attempts, then `status='failed'` with the error, and a `dead_letter` flag the UI surfaces.
Handlers must be idempotent — key on `(event_type, dedupe_key)`.

Event catalog: [05-workflows.md](05-workflows.md) § 1.

---

## 4. Connector layer

Agents must never know that Instagram needs a two-step container-then-publish call, or
that WhatsApp has a 24-hour window. They call capabilities:

```python
# src/connectors/base.py
class SocialConnector(Protocol):
    platform: str

    async def publish(self, req: PublishRequest) -> PublishResult: ...
    async def fetch_comments(self, since: datetime) -> list[InboundComment]: ...
    async def reply_comment(self, comment_id: str, text: str) -> ReplyResult: ...
    async def send_message(self, req: MessageRequest) -> MessageResult: ...
    async def get_insights(self, ref: MediaRef, window: Window) -> Insights: ...
    async def health(self) -> ConnectorHealth: ...
```

| Connector | Covers | Notes that shape the design |
|---|---|---|
| `meta` | Instagram + Facebook publish, comments, insights | Container-then-publish; carousels are N containers; ~50 posts/24h per IG account |
| `whatsapp` | Cloud API send/receive, templates | 24h service window; template approval takes days — request them in M0 |
| `tiktok` | Direct Post video/photo | Unaudited apps are restricted; audit is a hard gate for production |
| `google` | Google Ads read then write | Phase 2 |
| `web` | Search, Meta Ad Library, RSS | Phase 2, official endpoints only |
| `mock` | Every capability, deterministic | **Ships first.** Every other connector is written against its tests. |

**The mock connector is not a test fixture, it is infrastructure.** It lets the entire
product be built and demoed while app review is pending, which is the single biggest
schedule risk in the PRD.

**Token storage.** OAuth tokens live in `channels.credentials`, encrypted at the
application layer (envelope encryption, key in the secret manager, never the raw token in
Postgres). Refresh is a scheduled job per channel; failure emits `channel.disconnected`
and degrades that connector rather than failing the agent run.

---

## 5. Model gateway

One module, one function, no framework:

```python
# src/ai/gateway.py
async def complete(task: TaskKind, *, tenant_id: UUID, run_id: UUID, ...) -> Completion
```

It picks the model, applies cache breakpoints, records the trace row (model, tokens,
cost, latency, cache hit rate), and enforces the tenant's monthly cost ceiling.

### Routing table

| Task kind | Model | In / Out per MTok | Cached in | Why |
|---|---|---|---|---|
| `orchestrate`, `strategy`, `ads_decision`, `learning` | `gemini-2.5-pro` | $1.25 / $10.00 | $0.125 | Multi-step planning with money attached |
| `copywrite`, `sales_reply`, `analysis`, `creative_direction`, `vision` | `gemini-2.5-flash` | $0.30 / $2.50 | $0.03 | The workhorse. Most calls land here. |
| `classify_intent`, `spam_filter`, `route`, `tag` | `gemini-2.5-flash-lite` | $0.10 / $0.40 | $0.01 | High volume, trivial decisions. Thinking disabled. |
| `embed` | multilingual embedding model, 1024-dim | - | - | **Must be multilingual (AR/EN/FR).** See [04](04-memory-architecture.md) SS 3 |
| `image_edit` | `rembg` locally, hosted matting for hero shots | - | - | Deterministic beats generative here |
| `video` | FFmpeg compositor | - | - | See SS 6 |

**GA models only.** `gemini-3-pro-preview` was deprecated and shut down while it
was still the newest Pro, and `gemini-3.1-pro-preview` is preview today. A model
that disappears mid-quarter is an outage on the path where agents spend a
dealer's ad budget. `test_no_preview_models_are_routed` enforces it. Moving up
when 3.x Pro reaches GA is a one-line change - nothing outside `ai/models.py`
names a model.

Conventions for every call:

- **Thinking is a token budget, not an effort label.** `-1` lets the model
  decide, `0` disables it. Flash-Lite runs with `0`: thinking on a spam check is
  pure latency and cost on the critical path of a customer reply.
- **Structured output** uses `response_mime_type="application/json"` plus
  `response_schema=<pydantic model>`. That is schema-constrained decoding, so the
  model cannot emit anything that fails to parse; the local
  `model_validate_json` is a contract check, not a parser.
- **Check the finish reason before reading content.** A `SAFETY`,
  `PROHIBITED_CONTENT` or `RECITATION` candidate has no text part at all, and
  `response.text` raises from a property access rather than returning empty.
- **Thought parts are filtered out of the answer.** A thought summary must never
  reach a customer.

### Two cost details that are easy to get backwards

**`prompt_token_count` includes `cached_content_token_count`.** The cached
portion is a discount on part of the same total, not a separate bucket added on
top. Adding them - which Anthropic's API shape would require - bills the cached
tokens twice and overstates every invoice.

**Thinking tokens are billed at the output rate and reported separately** from
`candidates_token_count`. Dropping them makes reasoning-heavy calls look far
cheaper than they are.

### Prompt caching is a cost feature, not an optimization

Gemini caches **implicitly**: it finds the common prefix across calls itself and
bills those tokens at roughly a tenth of the input rate. There is no breakpoint
to place, which makes ordering the entire mechanism rather than a hint:

1. Agent role and rules (frozen per deploy)
2. Tool definitions (sorted deterministically)
3. Tenant Brand Brain + playbook (changes maybe weekly)
4. Retrieved context for this request (varies)
5. The actual request

A `datetime.now()`, a request ID, or an unsorted dict anywhere in layers 1-3 does
not merely move a boundary - it destroys the shared prefix and caches **nothing
at all**. Implicit caching also has a minimum prefix length, so short prompts
never cache; real tenant prompts clear it easily.

> **Deliberately not using explicit `CachedContent` objects.** They guarantee the
> discount, but cost storage per hour ($1.00/MTok for Flash, $4.50 for Pro) and
> require a cache lifecycle per tenant plus invalidation whenever the brand brain
> changes. Implicit caching reaches the same cached-input rate with no machinery.
> **Revisit if** measured hit rates are poor - `agent_traces.cache_read_tokens` is
> recorded on every call precisely so that is answerable.

**Automatic function calling is disabled explicitly.** It is ON by default and
would have the SDK execute tool callables inside the `generate_content` call,
bypassing the autonomy gate, every guard, and the trace. The tool loop belongs to
`orchestrator/executor.py`, which owns those. A test locks it off.

`npm run eval:gateway` makes two identical calls and asserts the second reads
from cache. A cache regression is invisible - nothing breaks, the prompt just
costs 10x - so it is the only honest check.

**Measured on `gemini-2.5-flash`**, ~16.8k-token prompt:

| | cached tokens |
|---|---|
| cold call | 0 |
| same prefix, immediately after | 0 |
| same prefix, ~2s later | 16,372 of 16,850 (**97%**) |
| still cached at 60s | 16,372 |

Population is not instantaneous, so the eval waits 5 seconds between the two
calls. At 97% cached and a tenth of the input rate, a repeated tenant prompt
costs roughly an eighth of an uncached one — which is what the PRD's cost
envelope assumes.

---

## 6. Media pipeline

**This is the decision most likely to be gotten wrong, so it is stated first:**

> **We do not generate cars. We composite the dealer's photographs.**

A text-to-image model asked for "MG6 XLINE Trophy 2026 in white" produces a car that does
not exist: wrong badge, wrong grille, invented wheels, fictional proportions. The dealer
is selling *that specific unit in the yard*. Generative imagery of the vehicle is a
product-integrity failure and, for an ad, a legal one.

### What is deterministic vs. what is AI

| Stage | Deterministic | AI |
|---|---|---|
| Photo QA (blur, exposure, clutter) | — | Vision model scores and rejects |
| Angle detection (front 3/4, rear, interior, detail) | — | Vision model labels |
| Ranking best shot per angle | — | Vision model plus rules |
| Background removal / matting | `rembg` (U2Net) | Hosted matting for hero shots only |
| Concept and layout choice | — | Creative Director picks a template plus a variant |
| **Pixel composition** | **Playwright renders an HTML/CSS template** | — |
| Copy, headline, CTA | — | Copywriter agent |
| Legal and brand validation | Rules in code | — |

### The compositor

Templates are HTML + CSS with CSS custom properties bound to the tenant's brand tokens:

```
templates/hero_offer/index.html   → --brand-primary, --brand-font, --logo-url,
                                     --headline, --price, --disclaimer, --dir (ltr|rtl)
```

Playwright renders at each aspect ratio (1:1, 4:5, 9:16, 16:9) and screenshots. This
gives us: pixel-exact brand compliance, free RTL via `dir="rtl"` and logical CSS
properties, versionable and diffable templates, no model cost per render, and designers
who can author templates without touching Python.

> `ponytail:` HTML/CSS + Playwright over Pillow/Skia composition. Ceiling is ~1–2 s and
> ~150 MB RSS per render, and a browser in the worker image. **Upgrade trigger:** more
> than 10k renders/day or render p95 above 4 s — then move the renderer to its own
> service with a warm browser pool. Do not start there.

### Video

Reels are FFmpeg: ranked stills with Ken Burns moves, cut to a beat grid, brand lower
thirds, burned-in captions (RTL-aware), tenant audio bed. Same reasoning as stills — a
video model would hallucinate the car. The Video Agent chooses the shot order, the pacing,
the hook text, and the caption; FFmpeg produces the frames.

Q2 in the PRD asks whether licensed B-roll generation is worth adding for non-vehicle
cutaways. Not in v1.

### Storage

Supabase Storage, one bucket, path `{tenant_id}/{kind}/{yyyy}/{mm}/{ulid}.{ext}`. Private
by default; signed URLs for the UI; public URLs only for assets already published to a
platform. Originals are never overwritten — every render is a new object, so a rollback
is a pointer change.

---

## 7. Multi-tenancy and security

**Layer 1 — Database.** RLS enabled on every tenant table. Two access paths:

| Path | Identity | Policy predicate |
|---|---|---|
| Browser → Supabase | User JWT | membership row for `auth.uid()` |
| FastAPI → Postgres | Role `dealerai_app` (`NOBYPASSRLS`) | `SET LOCAL app.tenant_id` per transaction |

**The `service_role` key never appears in a request path.** It exists for migrations
only. A single accidental service-role query is a cross-tenant data breach, so the
backend connects as a restricted role that cannot bypass RLS even if the code is wrong.
Details and SQL: [03-database-schema.md](03-database-schema.md) § 2.

**Layer 2 — Application.** Every request resolves exactly one `TenantContext`. Tools take
it as their first argument; there is no ambient tenant and no global. A tool that
receives an ID belonging to another tenant gets zero rows from RLS and raises `NotFound`.

**Layer 3 — CI.** A test seeds two tenants and asserts every table returns zero
cross-tenant rows under each access path. It runs on every commit and blocks merge.

**Secrets.** Platform tokens are envelope-encrypted at the application layer. Model API
keys live in the secret manager and are never per-tenant. Webhook signatures (Meta
`X-Hub-Signature-256`, WhatsApp, TikTok) are verified before the body is parsed.

**Prompt injection.** Customer messages, comments, competitor pages, and uploaded
documents are **data, never instructions**. They are wrapped in delimited blocks with an
explicit "this is untrusted content" framing, tools that spend money or publish are never
exposed to an agent whose context contains unfiltered inbound text, and the output guards
in § 8 run regardless of what the model was told.

---

## 8. Guardrails as code

Prompts are not a security boundary. Every one of these is a function that runs on the
output and can block it:

| Guard | Blocks | Failure mode |
|---|---|---|
| **Inventory guard** | Content or replies about a vehicle not `available` | Reject, emit `content.stale_vehicle` |
| **Price guard** | Any currency figure not matching a `vehicles.price` or approved offer row | Reject, escalate to human |
| **Brand guard** | Forbidden words, missing disclaimer, wrong CTA, off-palette render | Reject with reason, retry once, then queue for human |
| **Budget guard** | Ads changes above the tenant's caps | Convert to an approval request |
| **PII guard** | Customer PII leaving in outbound content | Redact and log |
| **Rate guard** | Platform posting/messaging limits | Delay, reschedule |

Guards are pure functions with unit tests. They run in the worker after generation and
before the connector call — never inside the prompt.

---

## 9. Observability

| Signal | Where | Used for |
|---|---|---|
| Agent runs and tasks | `agent_runs`, `agent_tasks` | The UI's "what did the AI do" view |
| Model calls | `agent_traces` — model, tokens, cost, latency, cache hits, prompt hash | Cost per tenant, regression triage |
| Tool calls | `agent_traces` with `kind='tool'` | "Why did it say that" |
| Connector calls | `audit_log` — request, response code, external ID | Platform dispute resolution |
| Approvals and overrides | `approvals` | Autonomy tuning, and training data for the learning loop |
| App logs | structlog JSON with `tenant_id`, `run_id`, `trace_id` | Ops |

Every user-visible AI output links back to its `agent_run`. "Why did it post this?" is a
click, not an investigation. Human edits and rejections are the highest-value training
signal we collect — they feed the learning loop in [04](04-memory-architecture.md) § 6.

---

## 10. Deployment

| Component | Runs on | Scaling |
|---|---|---|
| Next.js | Vercel | Automatic |
| FastAPI `api` | Fly.io / Railway container | 2+ instances behind a health check |
| `worker` | Same image, `worker` entrypoint | Start at 1, scale on queue depth |
| Postgres, Auth, Storage | Supabase managed | Vertical, plus read replica when reporting hurts |

Environments: `local` (Supabase CLI, mock connectors, real models on a dev key),
`staging` (real Supabase, sandbox platform apps), `production`. Migrations are the only
schema mechanism — no console DDL, ever.

**Cost envelope per tenant per month at MVP volume:** models roughly USD 40–90 (with
caching and Haiku routing), media rendering under 5, storage and egress under 10.
Comfortably inside the 70% gross-margin target at the Starter price.

---

## 11. Failure modes and degradation

| Failure | Behavior |
|---|---|
| Platform API down | Publish retries with backoff, content stays `scheduled`, UI shows a degraded channel badge |
| OAuth token expired | `channel.disconnected` event, agent skips that channel, owner is notified |
| Model API 429 or 5xx | Gateway retries with jitter, then downgrades one tier for non-critical tasks, then fails the task with a reason |
| Model refusal (`stop_reason == "refusal"`) | Task fails cleanly with the category logged. Never retry the identical prompt in a loop. |
| Worker crash mid-task | Event stays `processing`; a reaper releases anything locked longer than 15 minutes back to `pending` |
| Guard rejects repeatedly | After 2 attempts, escalate to a human with the generation and the rejection reason attached |
| Cost ceiling hit | Non-critical agents pause; inbound customer replies keep running; owner is alerted |

**The system's degraded state is Copilot mode:** when in doubt it stops acting and starts
asking. That is a product feature, not just an error path.
