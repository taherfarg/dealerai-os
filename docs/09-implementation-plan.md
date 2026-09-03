# DealerAI OS Implementation Plan

> **For agentic workers:** implement this plan task by task. Each task is a branch and a
> PR. Before writing code for a task, expand it into TDD steps — failing test, run it,
> minimal implementation, run it, commit — using `superpowers:subagent-driven-development`
> or `superpowers:executing-plans`. This document defines *what* each task is, its exact
> files, and the check that proves it done; the micro-steps are produced at pickup time so
> they reflect the code as it actually exists by then.

**Goal:** Ship the Phase 1 MVP defined in [06-mvp-scope.md](06-mvp-scope.md) — a dealer
connects Instagram, uploads 30 cars, and one week later has 40 published on-brand pieces,
sub-minute replies on every channel, and a scored lead list.

**Architecture:** Next.js dashboard reads Supabase directly under RLS; every
side-effecting action goes to a FastAPI service that enqueues Postgres-backed events; a
worker runs an agent orchestrator that dispatches a DAG of specialist agents over a
tenant-scoped tool layer, with guards enforced in code before anything reaches a customer.

**Tech stack:** Python 3.12 · FastAPI · asyncpg · Pydantic v2 · APScheduler · Playwright ·
FFmpeg · Google GenAI SDK (`gemini-2.5-pro` / `gemini-2.5-flash` / `gemini-2.5-flash-lite`) ·
Next.js 15 · TypeScript · Tailwind · shadcn/ui · Supabase (Postgres 15, pgvector, Auth,
Storage) · uv · ruff · mypy · pytest.

**Definition of done for every task:** tests pass, `ruff` and `mypy --strict` clean, the
cross-tenant isolation test still green, and the acceptance check in the task reproduces
on a fresh checkout.

---

## Milestone M0 — Foundation (weeks 1–2)

### T0.1 — Repository skeleton
**Files:** `package.json`, `apps/api/`, `apps/web/`, `docker-compose.yml`,
`.env.example`, `.gitignore`

Monorepo per [08-folder-structure.md](08-folder-structure.md). `docker-compose.yml` brings
up Postgres 15 with pgvector, MinIO (Storage stand-in), and a Playwright image.
`apps/api/src/dealerai/config.py` holds every environment variable as a
`pydantic-settings` model; `.env.example` is generated from it.

**Acceptance:** `npm run dev` starts Postgres, migrates, and serves the API; `curl localhost:8000/internal/health`
returns 200; a missing required env var fails startup with the variable's name.

---

### T0.2 — Apply the schema
**Files:** `supabase/migrations/0001_init.sql` (already written), `supabase/config.toml`,
npm scripts `db:migrate` and `db:reset`

**Acceptance:** `npm run db:reset` runs clean against an empty database.
`select count(*) from pg_policies where schemaname='public'` returns a policy for every
table in the RLS loop. Every view reports `security_invoker=on` in `pg_class.reloptions`.

---

### T0.3 — Tenant-scoped database session
**Files:** `apps/api/src/dealerai/db/session.py`, `apps/api/tests/test_tenant_isolation.py`

Implement `tenant_session(tenant_id)` — acquires a pooled connection, opens a transaction,
issues `select set_config('app.tenant_id', $1, true)`, yields. It is the only function in
the codebase that acquires a connection. Create the `dealerai_app` role per the ops block
at the bottom of `0001_init.sql` and point `DATABASE_URL` at it.

**Acceptance:** the isolation test seeds tenants A and B with a row in every RLS table and
asserts, for both the `dealerai_app` path and a JWT path, that A's context returns A's rows
and zero of B's — including through `v_vehicle_stock` and `v_lead_funnel`. Deliberately
connecting as `service_role` in the test makes it fail, proving the test has teeth.

---

### T0.4 — Errors, logging, money, locale
**Files:** `core/errors.py`, `core/logging.py`, `core/money.py`, `core/locale.py`, `main.py`

RFC 9457 `problem+json` handlers for every exception class ([07](07-api-design.md) § 2).
`structlog` JSON with `tenant_id`, `run_id`, `trace_id` bound per request. `money.py`
exposes `Money(amount_minor, currency)` with parse and format helpers and no float
constructor.

**Acceptance:** an unhandled exception returns `application/problem+json` with a `trace_id`
that appears in the log line for the same request. `Money` rejects a float argument with a
`TypeError`.

---

### T0.5 — Event bus and worker — **done**
**Files:** `events/bus.py`, `events/worker.py`, `worker.py`, `tests/test_events.py`

`emit(conn, event_type, payload, *, tenant_id=None, dedupe_key=None, run_after=None,
priority=0)` inserts into `events` **on the caller's connection**, so the event and its
cause commit together. Worker: claim with `FOR UPDATE SKIP LOCKED`, dispatch by name,
exponential backoff (`2^attempts` minutes, capped), dead-letter once `attempts` reaches
`max_attempts` (default 5). A reaper releases rows stuck in `processing` for over 15
minutes.

Two things the implementation settled that the plan had not:

- **`UPDATE ... RETURNING` does not preserve the sub-select's `ORDER BY`.** Priority chose
  which events were claimed but not the order they ran in, so a customer reply could sit
  behind nineteen metric fetches inside one batch. The claimed batch is re-sorted in
  Python.
- **An unknown event type retries rather than dead-lettering immediately.** During a
  rolling deploy an old worker briefly sees types it has no handler for; a few minutes of
  backoff rides that out, and a genuinely unknown type still dead-letters at
  `max_attempts`.

> **Deferred: `events/scheduler.py` (APScheduler).** A scheduler is only useful once there
> is a cron with a real handler behind it, and at M0 there is none — the reaper runs on
> its own interval inside the worker loop. Add it with the first real cron in M2
> (`vehicle.stale` nightly sweep), registering the table from [05](05-workflows.md) § 1.

**Acceptance:** met — 100 events across 3 concurrent workers are each handled exactly
once; a raising handler backs off with a growing `run_after` and dead-letters on the 5th
attempt; a row force-set to `processing` with an old `locked_at` is reclaimed by the
reaper and then processed.

---

### T0.6 — Model gateway — **done**
**Files:** `ai/models.py`, `ai/gateway.py`, `ai/prompts/_rules.md`, `tests/test_gateway.py`,
`tests/evals/test_gateway_cache.py`

`complete(task, *, tenant_id, run_id, system_layers, messages, tools, output_schema)`.
Routing table from [01](01-system-architecture.md) § 5. Assemble the system prompt in cache
order and set `cache_control` after the tenant layer. Always
`thinking={"type": "adaptive"}` — **never** `budget_tokens`, which returns a 400 on these
models. `output_config={"effort": ...}` per task kind. Stream when `max_tokens` is large
and take `.get_final_message()`. Check `stop_reason == "refusal"` before reading content.
Write an `agent_traces` row with tokens, cache read/write, cost, and latency on every call.
Refuse the call when the tenant is over `monthly_ai_budget_usd`.

**Acceptance:** met against stubs — 23 tests. A refusal surfaces as `ModelRefusal` and is
still traced (a refusal costs money, so it belongs in the bill). A tenant seeded over budget
raises `BudgetExceeded` and the client is asserted never to have been called. Cost maths is
tested against the cache multipliers directly.

> **Verified against the live API.** `npm run eval:gateway` passes: a cold call caches
> nothing, the same prefix ~5s later reads 16,372 of 16,850 tokens from cache (97%), and
> a real call returns usable text with correct token and cost accounting. The evals stay
> marked `eval` and deselected by default because they spend money on every run.

One thing the implementation settled: `output_schema` is enforced server-side via
`output_config.format` **and** re-validated locally with Pydantic, raising `ModelOutputInvalid`.
Trusting the server alone means a schema drift shows up as an `AttributeError` three call
frames later instead of at the boundary.

---

### T0.7 — Mock connector and the connector contract — **done**
**Files:** `connectors/base.py`, `connectors/mock.py`, `connectors/crypto.py`,
`tests/connectors/test_contract.py`, `tests/connectors/test_crypto.py`

Protocols and DTOs from [01](01-system-architecture.md) § 4. `mock.py` implements every
capability deterministically, with failure injection for rate limits and expired tokens.
`test_contract.py` is the shared suite that **every** connector must pass — Meta and
WhatsApp are written against it in M4 by appending to its `FACTORIES` list. If a real
connector needs the suite edited to go green, the change belongs in the connector.

Three things the contract pins down that the plan had left implicit:

- **Idempotency is part of the contract, not each connector's problem.** `PublishRequest`
  and `MessageRequest` both require an `idempotency_key`, and replaying one returns the
  original result without acting again. A retried worker posting the same car twice is a
  public mistake; sending a customer the same WhatsApp twice gets the number blocked.
- **Capabilities are declared, not assumed.** A connector publishes `supports:
  frozenset[PublishKind]` and raises `NotSupported` otherwise, so no caller carries a
  per-platform table.
- **The failure vocabulary is typed.** `RateLimited` (with `retry_after_seconds`),
  `TokenExpired` (not retryable — a human must reconnect), `NotSupported` (never retry),
  `OutsideMessagingWindow` (the 24-hour WhatsApp rule the Follow-up Agent branches on).
  Callers branch on type, never on a message string.

> **Deviation: MultiFernet, not envelope encryption.** Envelope's payoff is re-wrapping
> small data keys instead of re-encrypting large ciphertexts. These are 200-byte OAuth
> tokens, so it buys nothing and costs a key hierarchy to get wrong. `MultiFernet`
> decrypts with any configured key and encrypts with the first, so rotation is: prepend a
> key, redeploy, re-save channels, drop the old one. Tested end to end.

> **Deferred: `connectors/registry.py`.** A platform-to-connector registry with one
> implementation is a premature abstraction. It arrives in M4 with the second connector,
> where it also becomes the place credentials get decrypted.

**Acceptance:** met — the contract suite passes against three mock shapes (generic,
Instagram-like, WhatsApp-like). A token round-trips through `crypto` and
`test_stored_credentials_are_unreadable_in_the_database` asserts it does not appear in
`channels.credentials::text` read as superuser.

---

### T0.8 — CI, and platform app review
**Files:** `.github/workflows/ci.yml`, `tests/test_import_contracts.py`, `docs/runbook.md`

CI runs ruff, mypy --strict, pytest, migrations from empty, the isolation test, and the
import contracts: `agents` must not import `connectors`, and `pool.acquire()` may appear
only in `db/session.py`.

**In parallel, non-code and on the critical path:** submit the Meta app for
`instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`, and
`pages_manage_posts`; register the WhatsApp Business account and submit at least three
message templates; create the TikTok developer app and begin audit.

**Acceptance:** CI is green, and a PR that violates an import contract turns it red. Meta
and WhatsApp submissions have ticket numbers recorded in `docs/runbook.md`.

---

## Milestone M1 — Tenancy and auth (weeks 2–3)

### T1.1 — Auth and tenant bootstrap — **done**
**Files:** `routes/tenants.py`, `deps.py`, `apps/web/app/(auth)/`, `lib/supabase/`

Supabase Auth with email/password and Google. Sign-up creates `profiles`; then
`POST /v1/tenants` creates the tenant plus an `owner` membership in one transaction. The
`tenant_ctx` dependency validates `X-Tenant-Id` against `memberships` and raises **404**,
never 403 ([07](07-api-design.md) § 2).

**Acceptance:** met on the API side — 25 route tests. Requesting another tenant's ID
returns 404 with `problem+json`. The sign-up screen itself lands with T1.3, which needs a
real Supabase project; the backend verifies HS256 tokens with Supabase's exact claim shape
(`sub`, `aud=authenticated`, `exp`) and tests mint them locally with `mint_test_token`.

Two RLS walls hit here, both written up in [03](03-database-schema.md): the
`memberships` policy recursed infinitely, and every bootstrap write runs before a tenant
context exists. Fixed by `0003_bootstrap.sql` and `0004_membership_policy_recursion.sql`.

### T1.2 — Roles and invitations — **done**
**Files:** `routes/tenants.py`, `core/security.py`, `apps/web/app/(app)/[tenant]/settings/team/`

Five roles per [03](03-database-schema.md). A `require_role("admin")` dependency guards
mutating routes. Invitations are signed, single-use, 7-day tokens.

**Acceptance:** met, with one deliberate change. A `viewer` gets 403 on `PATCH` and 200 on
reads. **An invite consumed twice is a no-op, not an error** — replaying a link returns the
role the user already holds and never re-roles them, which is the safer behaviour for a
link that may be forwarded or double-clicked. Single use is enforced by the unique
`(tenant_id, user_id)` on memberships rather than by a consumed-invitations table.
Invitations are signed and expiring rather than stored, so there is no table to clean up
and a leaked link dies on its own. A user token cannot be replayed as an invite: both are
signed with the same secret and only the `kind` claim separates them, so that has a test.

### T1.3 — App shell
**Files:** `apps/web/app/(app)/[tenant]/layout.tsx`, `components/ui/`, `messages/{en,ar}.json`

Sidebar, tenant switcher, RTL driven by locale (`dir` on `<html>`, logical CSS properties
throughout), shadcn/ui installed.

**Acceptance:** switching the UI to Arabic mirrors the layout with no clipped or
overlapping elements at 360px, 768px, and 1440px.

### T1.4 — Autonomy settings and the gate — **done**
**Files:** `routes/tenants.py`, `orchestrator/gate.py`, `apps/web/.../settings/autonomy/`

The permission matrix from [02](02-agent-architecture.md) § 5 as data. `gate.py` answers
`can(action, ctx) -> Allow | NeedsApproval | Forbidden` from `tenants.autonomy_mode` and
`autonomy_rules`.

**Acceptance:** met — 88 tests, and they run with **no database at all**, which is the
point: the gate is pure logic and must stay trivially testable. The matrix is transcribed
by hand in the test from [02](02-agent-architecture.md) § 5, so editing one without the
other fails loudly.

Beyond the plan: an unknown action and an unknown mode both resolve to FORBIDDEN rather
than falling through to allow, and the Always-Human list is FORBIDDEN in every mode
including Autopilot — the AI escalates rather than asking permission.

### T1.5 — Approvals — **done (one part deferred)**
**Files:** `routes/approvals.py`, `events/handlers/system.py`, `apps/web/.../approvals/`,
`components/agent/ApprovalCard.tsx`

Create, list, approve, reject, bulk. `approval.decided` resumes or cancels the dependent
branch of the run's DAG.

**Acceptance:** partially met. Approvals are created (`request_approval`, transactional
with whatever produced them), listed, decided under `SELECT ... FOR UPDATE` so two
simultaneous clicks cannot both win, and emit `approval.decided`. Bulk decisions report
partial success rather than failing — one already-decided item must not sink the other
forty-nine.

> **Deferred: resuming the DAG branch.** "Resumes to completion after approval, marks
> dependent tasks skipped after rejection" needs the executor, which lands in T3.2. The
> `approval.decided` event is emitted and recorded now; its handler is written there,
> beside the code that owns task state. Writing it here would mean writing it twice.

---

## Milestone M2 — Inventory (weeks 3–5)

### T2.1 — Vehicle CRUD — **done**
**Files:** `routes/vehicles.py`, `db/queries/vehicles.py`, `apps/web/.../inventory/`

List with filters, create, update, status transitions, price changes writing
`vehicle_price_history`. `min_price_minor` is excluded from every response model that a
customer-facing surface can reach.

**Acceptance:** met. `VehicleSummary` — the shape a customer-facing agent sees — has no
discount-floor field *in the model at all*, asserted directly and again as a strict-subset
check against `VehicleOut`. Omitting it at the call site would be one forgotten
`exclude` away from a leak.

Three behaviours settled here:

- **Selling emits `vehicle.sold` at raised priority**, not a generic status event. Its
  handler cancels every scheduled item referencing the car; marketing a vehicle that is
  gone is the most visible way this product can embarrass a dealer.
- **A price change always writes history, but only emits when the number actually moved.**
  The audit row is always wanted; waking every downstream handler for a no-op is not.
- **Marketers publish, admins price.** A marketer changing a list price gets 403.

### T2.2 — Media upload and storage
**Files:** `media/storage.py`, `routes/vehicles.py`, `apps/web/components/inventory/Uploader.tsx`

Multipart upload to Supabase Storage at `{tenant_id}/vehicles/{vehicle_id}/{ulid}.{ext}`,
private, signed URLs for display. Emits `vehicle.media_uploaded`.

**Acceptance:** 20 photos upload in one request; a signed URL expires; a URL for tenant B's
object is not obtainable from tenant A's session.

### T2.3 — Photo QA and angle detection — **done (accuracy eval pending photos)**
**Files:** `media/vision.py`, `events/handlers/inventory.py`, `tests/media/test_vision.py`

Vision pass with `gemini-2.5-flash` and a strict output schema: rejection reason, angle from
the 12-class enum, quality score 0–1. Ranks per angle and sets one hero.

**Acceptance:** partially met, and the gap is data rather than code.

Met: exactly one `is_hero` per vehicle, enforced in code with 18 tests over the ranking
rules. Live evals confirm the image path works end to end and that the model rejects a
non-vehicle image while returning `angle: unknown` rather than guessing.

**Outstanding: the 85%-on-40-photos accuracy bar.** That needs real dealer photographs
with known angles, which this repo has none of. The harness is written and skips itself:
drop labelled JPEGs into `tests/evals/fixtures/photos/<angle>/` and
`test_angle_accuracy_on_real_photographs` turns on with no code change. Pollux's catalogue
is the obvious source.

Three decisions worth keeping:

- **`is_hero` is chosen in code, never asked of the model.** A per-photo call cannot see
  the other photos, and two heroes or none is a broken vehicle page.
- **Every exterior angle outranks every interior one**, regardless of score. A listing
  that leads with a photo of the steering wheel is a listing nobody clicks. The first
  version omitted plain `rear` from the preference list, which let a 0.99 dashboard shot
  beat a 0.4 exterior — caught by a test.
- **A vehicle whose photos are all rejected gets no hero at all.** Promoting the
  least-bad blurry shot is exactly the outcome the module exists to prevent.

### T2.4 — CSV import
**Files:** `routes/vehicles.py`, `events/handlers/inventory.py`, `apps/web/.../inventory/import/`

Upload, then an LLM-assisted column mapping proposal, then **human confirmation**, then row
creation. Errors are reported per row; a partial import is a valid outcome.

**Acceptance:** a 50-row messy CSV (mixed headers, Arabic column names, prices with commas)
maps correctly after one confirmation, and three deliberately broken rows are reported
without aborting the other 47.

### T2.5 — Enrichment and USP extraction
**Files:** `agents/content/enrichment.py`, `tools/inventory.py`, `ai/prompts/enrichment.md`

Normalize names and units. Fill missing specs **only** from the tenant's documents. Extract
3–5 USPs grounded in the record.

**Acceptance:** a vehicle with no horsepower in its record and no document mentioning it
still has `power_hp IS NULL` after enrichment, and no USP references horsepower. This test
is the codified form of "never invent a fact about a car."

### T2.6 — Stock report — **done (API side)**
**Files:** `apps/web/.../inventory/`, `routes/vehicles.py` route `/stock-report`

Grid and table views, aging highlight, content-coverage column from `v_vehicle_stock`.

**Acceptance:** met on the API side — `GET /v1/vehicles/stock-report?min_days&uncovered_only`
over `v_vehicle_stock`, covering available stock only, ordered by age. The UI lands with
T1.3, which needs a Supabase project.

---

## Milestone M3 — Content factory (weeks 5–8)

### T3.1 — Brand ingestion
**Files:** `routes/brand.py`, `agents/content/brand_ingest.py`, `ai/prompts/brand_ingest.md`,
`apps/web/.../brand/`

Extract palette and typography from the logo and past posts (vision), tone and CTA style
from past captions, chunk and embed the brand guide. Present a draft for **mandatory human
confirmation**.

**Acceptance:** ingesting the design partner's assets produces a palette within ΔE 5 of the
real brand colours, and the profile cannot reach a confirmed state without a human action.

### T3.2 — Agent runtime
**Files:** `agents/base.py`, `agents/registry.py`, `orchestrator/planner.py`,
`orchestrator/executor.py`, `routes/runs.py`

`Agent` protocol, `AgentContext`, `AgentResult` exactly as in
[02](02-agent-architecture.md) § 2. The executor resolves `depends_on`, runs ready tasks in
parallel, resolves `from_task` from `agent_tasks.output`, and commits the result and its
emitted events in one transaction.

**Acceptance:** a run with a diamond DAG (t1 → t2, t3 → t4) executes t2 and t3 in parallel
and t4 once. Killing the worker mid-run and restarting resumes without repeating a
completed task.

### T3.3 — Tool layer
**Files:** `tools/registry.py`, `tools/inventory.py`, `tools/brand.py`, `tools/memory.py`,
`tools/content.py`

A `@tool` decorator that generates a strict JSON schema, traces every call, and takes
`TenantContext` first. Wire into `client.beta.messages.tool_runner` with a per-turn hook
that records traces and enforces the gate.

**Acceptance:** an agent given tenant A's context and asked for a vehicle ID belonging to
tenant B receives an empty result and reports that it cannot find the vehicle — it does not
fabricate one.

### T3.4 — Guards
**Files:** `guards/inventory.py`, `guards/price.py`, `guards/brand.py`, `guards/pii.py`,
`tests/guards/`

Pure functions over generated output. The price guard extracts every currency figure and
requires each to match a `vehicles.price_minor` or an approved offer row.

**Acceptance:** 100% branch coverage on `guards/`. A caption containing "starting at
64,000" for a vehicle priced 66,000 is rejected with the offending figure named.

### T3.5 — Creative templates and the compositor
**Files:** `templates/`, `media/compositor.py`, `tests/media/test_compositor.py`

Eight templates per [08](08-folder-structure.md) § 4. Playwright renders each at 1:1, 4:5,
9:16, and 16:9 from brand tokens. RTL via `dir="rtl"` and logical properties.

**Acceptance:** golden-image comparison per template per ratio within a 2% pixel-difference
threshold. Every template renders correctly with an Arabic headline and with an English
one. Render p95 under 4 s.

### T3.6 — Content agents
**Files:** `agents/content/strategist.py`, `creative_director.py`, `copywriter.py`, `image.py`

Wire the W3 flow from [05](05-workflows.md) § 4.

**Acceptance:** `POST /v1/content/generate` for one vehicle with 8 good photos produces at
least 8 content items, each with AR and EN copy, four aspect ratios, and all guards passed.

### T3.7 — Content UI and approvals
**Files:** `apps/web/.../content/`, `components/content/`, `components/agent/RunStream.tsx`

Grid, detail view with inline caption editing and asset swap, approve and reject with
reason, SSE run stream.

**Acceptance:** a user watches generation live over SSE, edits one caption, approves, and
the item reaches `approved`. `edited_by_human` is set on the edited copy row.

### T3.8 — Calendar
**Files:** `routes/content.py` route `/calendar`, `apps/web/.../content/calendar/`

Week and month views, drag to reschedule, gap detection, per-day posting limits.

**Acceptance:** dragging an item updates `scheduled_at` and emits nothing until the slot is
due. Scheduling above `max_posts_per_day` is refused with a named reason.

---

## Milestone M4 — Publishing and inbox (weeks 8–11)

### T4.1 — Meta OAuth and channels
**Files:** `routes/channels.py`, `connectors/meta.py`, `apps/web/.../settings/channels/`

OAuth start and callback, long-lived token exchange, encrypted storage, scheduled refresh,
health checks that emit `channel.disconnected` on failure.

**Acceptance:** connecting a real Instagram Business account stores an encrypted token and
lists the account. Revoking it in Meta marks the channel `expired` within one health cycle.

### T4.2 — Meta connector
**Files:** `connectors/meta.py`, `tests/connectors/test_meta.py`

Container-then-publish, carousels as N containers, stories, comment fetch and reply,
insights. Must pass `test_contract.py` unmodified.

**Acceptance:** the contract suite passes against recorded fixtures, and a live smoke test
publishes to a sandbox account and returns a permalink.

### T4.3 — Publisher agent and pipeline
**Files:** `agents/content/publisher.py`, `events/handlers/content.py`

The W4 flow: pre-flight checks, per-channel independent publication, retries, metric-fetch
scheduling.

**Acceptance:** a scheduled item publishes within 60 s of its slot. With Instagram
succeeding and Facebook failing, the item is `published` with one `failed` publication row
and a visible cause. A vehicle marked sold cancels its scheduled items.

### T4.4 — Webhook ingestion
**Files:** `routes/webhooks/meta.py`, `routes/webhooks/whatsapp.py`, `routes/webhooks/verify.py`

Signature verification on raw bytes before parsing, raw persistence, channel and contact
resolution, event enqueue, 200 in under 500 ms.

**Acceptance:** a tampered signature returns 401 and enqueues nothing. Delivering the same
payload three times creates one event. p95 acknowledgement under 500 ms during a 50 rps
burst.

### T4.5 — Intent classifier and the golden set
**Files:** `agents/sales/intent.py`, `tests/evals/golden_messages.jsonl`,
`tests/evals/test_intent.py`

`gemini-2.5-flash-lite`, `effort=low`, strict output schema. Build the 200-message golden set
from the design partner's real history, Arabic and English.

**Acceptance:** accuracy above 95% on the golden set; spam recall above 90%.

### T4.6 — Community Manager
**Files:** `agents/content/community.py`, `events/handlers/inbox.py`, `ai/prompts/community.md`

The W5 flow: classify, look up real facts, draft a public reply plus a DM, run guards,
apply the gate.

**Acceptance:** a comment asking a price gets a reply containing the exact
`vehicles.price_minor` value plus the tenant disclaimer, in under 60 s end to end. A comment
about a sold vehicle never receives a price.

### T4.7 — Unified inbox
**Files:** `routes/inbox.py`, `apps/web/.../inbox/`, `lib/hooks/useRealtimeInbox.ts`

Thread list and view across surfaces, assignment, `ai_paused`, human reply, "ask the AI to
draft", realtime via Supabase subscriptions.

**Acceptance:** a WhatsApp message appears in the inbox within 5 s of the webhook. Assigning
a conversation sets `ai_paused` and the AI stops replying to it.

### T4.8 — WhatsApp connector
**Files:** `connectors/whatsapp.py`, `tests/connectors/test_whatsapp.py`

Cloud API send and receive, media, templates, delivery receipts, and the 24-hour window
tracked in `conversations.wa_window_expires_at`.

**Acceptance:** the contract suite passes. A free-form send outside the window is refused by
the connector and falls back to an approved template.

---

## Milestone M5 — Sales and CRM (weeks 11–14)

### T5.1 — Contacts and Customer 360
**Files:** `routes/crm.py`, `db/queries/crm.py`, `apps/web/.../leads/[id]/`

Contact resolution across platforms via `external_refs`, the 360 query from
[04](04-memory-architecture.md) § 5, and duplicate merging.

**Acceptance:** the same person messaging on Instagram and WhatsApp resolves to one contact
when the phone number matches, and the 360 view shows both threads.

### T5.2 — Retrieval
**Files:** `ai/embeddings.py`, `ai/retrieval.py`, `routes/documents.py`,
`tests/evals/test_retrieval.py`

Chunking per source type, multilingual embeddings, hybrid vector plus full-text search
merged with reciprocal rank fusion, pre-filtered by tenant and locale.

**Acceptance:** recall above 85% on a 50-question golden set over the design partner's
export policy, including Arabic questions against English source text.

### T5.3 — Sales Agent
**Files:** `agents/sales/sales.py`, `ai/prompts/sales.md`, `events/handlers/inbox.py`

The W6 flow with full context assembly, the WhatsApp window check, escalation, and the
discount limit — the agent is told a limit, never the floor.

**Acceptance:** a 5-turn scripted conversation produces a correct price, a correct
availability answer, and a lead. `test_no_hallucinated_facts.py` passes with **zero**
violations across the whole golden set. An attempt to negotiate below the floor escalates
instead of conceding.

### T5.4 — Escalation and handoff
**Files:** `agents/sales/sales.py`, `routes/inbox.py`, `events/handlers/inbox.py`

Holding message in the customer's language, assignment, AI pause, notification.

**Acceptance:** every escalation trigger from [02](02-agent-architecture.md) § 8 is
exercised by a test and results in an assigned, AI-paused conversation.

### T5.5 — Leads and scoring
**Files:** `agents/sales/lead_intel.py`, `routes/crm.py`, `apps/web/.../leads/`

Score 0–100 with reasons, hot/warm/cold bands, stages, assignment, pipeline UI.

**Acceptance:** scores are reproducible for identical input, every score carries at least
two reasons, and moving a card on the pipeline board writes an `activities` row.

### T5.6 — Follow-up
**Files:** `agents/sales/followup.py`, `events/handlers/crm.py`, `ai/prompts/followup.md`

The W7 flow, with eligibility checked in code before any model call, and "no genuine reason
means do not send."

**Acceptance:** a lead with no new information receives **no** message and is marked cold. A
lead whose vehicle dropped in price receives one message referencing the drop. Withdrawn
consent means zero outbound. Never more than three follow-ups.

---

## Milestone M6 — Analytics and the daily brief (weeks 14–16)

### T6.1 — Metric collection
**Files:** `events/handlers/content.py`, `connectors/meta.py`, `db/queries/analytics.py`

Fetch insights at +1h, +24h, +7d, and +30d into `content_metrics`.

**Acceptance:** a published post has a 24h metrics row within 15 minutes of T+24h; a failed
fetch retries without duplicating rows.

### T6.2 — Funnel and attribution
**Files:** `db/queries/analytics.py`, `routes/analytics.py`

Impressions → engagement → conversations → leads → qualified → deals, joined through
`leads.source_content_item_id` and `deals.attribution`.

**Acceptance:** a seeded end-to-end journey (post → comment → DM → lead → deal) appears
correctly at every funnel stage and attributes the revenue to the originating content item.

### T6.3 — Meta Ads, read-only
**Files:** `connectors/meta.py`, `routes/ads.py`, `apps/web/.../analytics/`

Connect the ad account, sync campaign metrics, and display **our** cost per lead rather than
the platform's.

**Acceptance:** synced spend matches Ads Manager for the same window, and CPL is computed
from our `leads` count, not the platform's reported leads.

### T6.4 — Analytics Agent and the daily brief
**Files:** `agents/growth/analytics.py`, `events/handlers/system.py`,
`apps/web/.../page.tsx`, `ai/prompts/analytics.md`

The W10 flow at 07:00 tenant-local, with up to three ranked recommendations, each backed by
a prepared run.

**Acceptance:** the brief renders with every number traceable to its source rows, and `Why?`
opens the `agent_run` that produced the recommendation.

### T6.5 — Cost and usage
**Files:** `routes/tenants.py` route `/usage`, `ai/gateway.py`, `apps/web/.../settings/billing/`

Per-tenant AI spend by agent, model, and day; an 80% warning; non-critical agents pause at
100% while inbound customer replies keep running.

**Acceptance:** spend reported by the endpoint matches the sum of `agent_traces.cost_usd`
for the period. At 100% of budget, a content-generation run is refused while a
`message.received` handler still replies.

---

## MVP gate

Before declaring Phase 1 complete, walk every checkbox in
[06-mvp-scope.md](06-mvp-scope.md) § 4 against a live tenant. An unchecked box is a task,
not a footnote.

---

## Phase 2 — outline

Expand each into tasks when the milestone starts, in this document's format. Do not expand
them now; the shape will have changed by then.

### M7 — Ads management (weeks 17–21)
Apply `0002_growth.sql`; ads write capability in the Meta connector; the budget guard with
its 24-hour change window; the Ads Manager agent; the W8 loop; campaign UI.
**Gate:** 30 consecutive days where our reported CPL matches the tenant's own reporting
within 5%, before any write access is enabled.

### M8 — Market and competitor intelligence (weeks 21–25)
Research connector over official endpoints only; competitor registration and observation;
market signals; the intelligence agents; feeding signals into the Content Strategist.
**Gate:** a design partner confirms three consecutive weekly signal reports were correct and
useful.

### M9 — Learning loop (weeks 25–29)
Outcome aggregation; the Learning Agent; the memory write path with dedup and decay;
playbook versioning, proposal, approval, and rollback; experiments.
**Gate:** a proposed playbook diff is accepted by a dealer and the next 30 posts measurably
outperform the prior baseline.

### Phase 3 — Autonomous (M10 and beyond)
Growth Director goal decomposition, automated experimentation, forecasting, Reels, TikTok,
advanced lead scoring, and extracting the multi-vertical core.

---

## Critical path

```
T0.1 → T0.2 → T0.3 ──┬─→ T0.5 → T3.2 → T3.6 → T4.3 → T5.3 → T6.4
                     ├─→ T0.6 ──┘
                     └─→ T0.7 ──→ T4.2 ──┘

T0.8 app review  ═══════════════════════════╗   external, weeks long, starts week 1
                                            ╚══→ gates T4.1 going live, nothing else
```

**Three things gate everything, and all three start in week 1:** the tenant-scoped session
(T0.3), the event bus (T0.5), and platform app review (T0.8). The first two are about two
days of work each. The third is outside our control, which is exactly why it is submitted
before the feature that needs it exists.
