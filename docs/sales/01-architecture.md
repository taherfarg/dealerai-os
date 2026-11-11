# Sales — Architecture

**Status:** Draft · **Depends on:** [00](00-prd.md), DealerAI OS [01](../01-system-architecture.md), [03](../03-database-schema.md)

This document covers only what the Sales module adds or changes. The event queue, model gateway,
connector contract, guards, autonomy gate and tenant session are described in DealerAI OS 01–03
and are reused as they are.

---

## 1. Component map

```
┌──────────────────────────────────────────────────────────────────────────┐
│ apps/web — Next.js 16                                                    │
│ Inbox · My day · Customers · Pipeline · Tasks · Dashboard · Settings     │
│ types generated from OpenAPI · React Query · one SSE connection          │
└──────┬───────────────────────────────┬───────────────────────────────────┘
       │ sign-in only                  │ REST /v1/*   +   SSE /v1/stream
       ▼                               ▼
  Supabase Auth          ┌─────────────────────────────────────────────────┐
                         │ FastAPI  api                                    │
                         │ inbox · customers · pipeline · tasks · dashboard│
                         │ settings · channels · stream · webhooks/whatsapp│
                         └──────┬──────────────────────────────────────────┘
                                │ tenant_session(tenant, user, scope)
                                ▼
                  ┌───────────────────────────────────────────┐
                  │ Postgres 17 + pgvector                    │
                  │ RLS = tenant wall + visibility            │
                  │ events (queue) · NOTIFY 'rt' (live)       │
                  └──────┬────────────────────────────────────┘
                         │ claim (SKIP LOCKED)
                         ▼
                  ┌───────────────────────────────────────────┐
                  │ worker                                    │
                  │ ingest · media · transcribe · assign ·    │
                  │ response targets · copilot · profile ·    │
                  │ scoring · follow-ups · brief · push       │
                  └──────┬──────────────────────┬─────────────┘
                         ▼                      ▼
              connectors/whatsapp.py      ai/gateway.py (Gemini)
              (Cloud API, coexistence)    guards/* · tools/*
```

### New modules (`apps/api/src/dealerai/`)

| Module | Responsibility |
|---|---|
| `routes/webhooks/whatsapp.py`, `routes/webhooks/verify.py` | Verify signature on raw bytes, persist, route to tenant, enqueue, 200 |
| `connectors/whatsapp.py` | Cloud API: send (text, media, template), mark read, media download/upload, template list, coexistence sync calls. Passes `tests/connectors/test_contract.py` |
| `sales/identity.py` | Phone normalisation (E.164), resolve contact by BSUID then phone, merge |
| `sales/assignment.py` | Routing rules → team → least-recently-assigned available member |
| `sales/hours.py` | Business-hours arithmetic: response-target due times in the tenant timezone |
| `sales/scoring.py` | Pure function: signals → score, band, reasons |
| `db/queries/{inbox,customers,pipeline,tasks,dashboard}.py` | Plain SQL per domain |
| `routes/{inbox,customers,pipeline,tasks,dashboard,settings,channels,stream,me}.py` | REST and SSE |
| `events/handlers/{whatsapp,inbox,crm,copilot}.py` | Event handlers |
| `agents/sales/{intent,copilot,profile,followup,brief}.py` | Model-calling agents |
| `media/transcribe.py` | Voice note → transcript through the gateway (`transcribe` task kind) |
| `realtime.py` | One LISTEN connection per API process, fan-out to SSE subscribers |
| `notifications/push.py` | Web Push (VAPID) from the worker |
| `ai/embeddings.py`, `ai/retrieval.py` | Knowledge documents (DealerAI OS T5.2, pulled into Phase 1) |

Import rules from DealerAI OS 08 still hold: `agents` never import `connectors`; only
`db/session.py` acquires a connection; `guards` stay pure. `sales/` is pure domain logic and
imports nothing from `routes`, `events` or `connectors`.

---

## 2. Request paths

Every feature is one of four paths.

### A. App data — browser to FastAPI (replaces DealerAI OS 01 §2 path A)

```
browser ──Authorization: Bearer <Supabase access token>, X-Tenant-Id──► /v1/*
FastAPI: verify JWT → tenant_ctx (membership → role → scope) → tenant_session(tenant, user, scope)
```

- The browser never reads a table. The migration revokes every privilege in `public` from `anon`
  and `authenticated`, and CI asserts `has_table_privilege` is false for both on every table.
- Interactive screens fetch with React Query from client components. Server components may call the
  API with the cookie session (the existing `lib/api.ts`).
- Frontend types are generated from `/openapi.json` into `apps/web/lib/api/schema.ts`; CI
  regenerates and fails on any diff ([07](07-frontend.md) §2).

### B. Live updates — Postgres to the browser

```
any commit that changes a conversation, message, lead, task, notification or channel
   └─► pg_notify('rt', {tenant_id, type, id, conversation_id, owner_id, assignee_id, team_id})
          (delivered only if the transaction commits · payload is ids only, far below 8 KB)
API process ──one LISTEN 'rt' connection (session pooler :5432; transaction mode cannot LISTEN)
   └─► for each open SSE stream: same tenant? visible to this user? → send the event
browser ──► invalidates the matching React Query keys → refetches over REST
```

- The event is a nudge, never data. REST stays the only source of truth, so a missed event costs a
  refetch, not a wrong screen.
- Authentication: `fetch`-based SSE with the `Authorization` header (the native `EventSource` cannot
  send headers). Heartbeat comment every 15 s. On reconnect the client refetches its active queries;
  there is no replay.
- The in-memory visibility check uses the ids in the payload and a per-stream cache of the user's
  visible owner ids, refreshed every 60 s and on `membership.changed`.

> `ponytail:` NOTIFY + SSE fan-out in each API process. Ceiling is roughly 2,000 open streams per
> instance and NOTIFY's single queue. **Upgrade trigger:** sustained streams above that, or NOTIFY
> queue usage above 50% (`pg_notification_queue_usage()`). Then Supabase Realtime Broadcast or
> Redis pub/sub. Do not pre-build.

### C. Webhooks — Meta to FastAPI

The DealerAI OS 07 §5 order, unchanged: verify `X-Hub-Signature-256` on the raw body → insert
`webhook_deliveries` → route `phone_number_id` to a channel and tenant → one event per item with
`dedupe_key` = the WhatsApp message id (or message id + status) → 200 within 500 ms. Every webhook
type and what it becomes: [03](03-whatsapp.md) §4.

### D. Worker — events to side effects

Handlers run inside `tenant_session(tenant_id, scope='all')`. Priorities, highest first:

| Priority | Work |
|---|---|
| 10 | Ingest inbound message, echo, status; send outbound |
| 8 | Assignment, notifications, response-target sweep |
| 5 | Media download, transcription, AI draft |
| 2 | Profile extraction, scoring, summaries |
| 0 | History import chunks, daily brief, embeddings |

A customer's message is stored and visible before any model runs on it.

---

## 3. Visibility

### Scope from role

| Role | Scope | Sees |
|---|---|---|
| owner, admin, viewer | `all` | Everything in the tenant (viewer read-only) |
| manager | `team` | Rows owned by members of their teams, those teams' unassigned rows, their own |
| sales | `own` | Their own rows, their teams' unassigned rows (tenant setting), conversations assigned to them |
| marketer | `own` | Effectively none: not in a sales team and owns no customers |
| worker / system | `all` | Acts on rows already routed |

### Mechanism

`tenant_session(tenant_id, user_id=None, scope='all')` sets three transaction-local settings:
`app.tenant_id` (existing), `app.user_id`, `app.scope`. RLS on the owner-bearing tables adds a
visibility predicate to the existing tenant predicate:

```sql
using (
  app.has_tenant_access(tenant_id)
  and (
    (select app.visible_owner_ids()) is null                    -- scope 'all'
    or owner_id = any((select app.visible_owner_ids()))
    or (owner_id is null and team_id = any((select app.my_team_ids())) and (select app.pool_visible()))
  )
)
```

- `app.visible_owner_ids()` is SECURITY DEFINER and STABLE; wrapped in `(select …)` it is evaluated
  once per statement, not once per row. It returns `null` for scope `all`, `{me}` for `own`, and
  `{me} ∪ members of my teams` for `team`.
- Policies read `memberships`, `teams` and `team_members` **only** through SECURITY DEFINER
  functions — the recursion rule from DealerAI OS 0004.
- Denormalised owner columns keep predicates on one row: `contacts.owner_id`,
  `conversations.owner_id` (the customer's owner) plus `conversations.assigned_to`,
  `leads.owner_id`, `tasks.assignee_id`. One writer keeps them consistent:
  `app.reassign_contact(contact, new_owner, actor)`. An invariant test asserts
  `conversations.owner_id = contacts.owner_id` after every write path.
- Child tables (`messages`, `ai_suggestions`, `contact_identities`, `activities`) are visible when
  their parent is: `exists (select 1 from conversations c where c.id = conversation_id)` — the
  inner select is itself filtered by the conversations policy.
- `notifications` and `conversation_reads` are always the caller's own rows.

Full SQL, indexes and the test matrix: [02](02-data-model.md) §4.

---

## 4. Channel layer

`connectors/whatsapp.py` implements the DealerAI OS connector contract (`send_message` with a
required `idempotency_key`, typed failures including `OutsideMessagingWindow`, `RateLimited`,
`TokenExpired`) plus messaging capabilities the contract gains in this module:

```python
async def send_template(req: TemplateRequest) -> MessageResult
async def mark_read(external_message_id: str) -> None
async def download_media(media_id: str) -> tuple[bytes, str]      # bytes, mime
async def upload_media(data: bytes, mime: str) -> str            # media id
async def list_templates() -> list[TemplateInfo]
async def start_history_sync() -> None                           # coexistence
async def start_contacts_sync() -> None                          # coexistence
```

The mock connector gains the same capabilities with deterministic behaviour and failure injection;
the contract suite gains window, template and idempotency cases that every messaging connector
must pass. Instagram and Messenger (Phase 2) are new files against the same suite.

---

## 5. Media

- Inbound media is downloaded by media id in the worker immediately — Meta media URLs expire in
  minutes — and stored at `{tenant}/messages/{yyyy}/{mm}/{uuid}.{ext}` (`media/storage.object_path`).
- Objects are private. Message DTOs carry short-lived signed URLs (1 hour) issued by the API.
- Outbound attachments: `POST /v1/uploads` (multipart) → Storage → `upload_id`; the send handler
  uploads the bytes to Meta and sends by media id.
- Voice notes (`audio/ogg; codecs=opus`) go straight to the gateway's `transcribe` task — Gemini
  accepts the audio directly, no FFmpeg step.

---

## 6. Deployment changes

| Component | Change |
|---|---|
| `api` | Must support long-lived streaming responses — Fly.io, beside the database: Singapore for staging, Mumbai for the pilot, as decided on 2026-10-05 ([`fly.toml`](../../fly.toml)); not serverless. One extra Postgres connection per process for LISTEN, on the session pooler. One image, `apps/api/Dockerfile`, which serves the API by default. Outside a laptop it refuses to start with settings that would fail on the first request, naming each (`config.deploy_problems`) |
| `worker` | Media download, transcription and push added; no new system packages. The same image, with `python -m dealerai.worker`, and the same refusal |
| `web` | Vercel was the plan, and its free plan is for non-commercial personal use: staging's web app is a second free service on Render, beside the API, and the pilot's host is not decided ([10](10-staging.md) §1, §5). `NEXT_PUBLIC_API_URL`; PWA manifest and service worker |
| Supabase | A new project: the first one is gone, which answers Q1 ([00](00-prd.md) §12) by where the new one is made. Sessions are verified against the keys it publishes (`core/security.py`). Storage for message media is not set up, and needs a decision first ([10](10-staging.md) §8) |

The order to do all of it in, and how to tell each step worked: [10](10-staging.md).

New configuration (declared in `config.py`, generated into `.env.example`):
`WHATSAPP_APP_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`,
`WHATSAPP_GRAPH_VERSION`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `APP_BASE_URL`,
and `WEB_ORIGINS` — the browser origins allowed to call the API, since the web app calls it directly.

---

## 7. Local development without Meta

Everything in Phase 1 except coexistence onboarding is buildable and testable offline:

- **Seed data:** a Pollux-style tenant — five users in two teams, twelve vehicles, thirty customers
  in Arabic, English and French, forty conversations, leads in both pipelines, tasks, templates,
  quick replies and knowledge documents. `npm run db:seed`.
- **Simulator:** `npm run wa:simulate -- inbound|voice|echo|status|history ...` builds a real
  WhatsApp webhook payload, signs it with the local app secret, and POSTs it to
  `/webhooks/whatsapp`. It exercises the real path — signature, persistence, routing, events —
  not a shortcut around it. Local environment only; the route refuses unsigned bodies everywhere.
- **Sign-in:** `/dev-login` signs in as any seeded person with a locally minted token. It exists only
  when the API runs with `ENV=local` and the web app is a non-production build with
  `NEXT_PUBLIC_DEV_AUTH=1` — checked on both sides.
- **Outbound:** the mock connector records sends and emits the status webhooks a real send would.
- **Staging:** Meta's test phone number (up to five recipient numbers) for real sends before approval.

---

## 8. Observability

| Signal | Where |
|---|---|
| Webhook ack latency, per type | structlog + `/internal/metrics` histogram |
| Queue depth and oldest pending age | `/internal/health`: `queue.waiting`, `queue.oldest_seconds` — what is due and not yet taken. With no worker it only grows, which `npm run smoke` reads |
| LISTEN connection state, open SSE streams | `/internal/health` |
| Channel health (token, quality rating, sync state) | `channels.health`, surfaced in Settings |
| Draft latency, cost, acceptance by intent | `agent_traces` + `ai_suggestions` |
| Reassignments, merges, deletions, role changes | `audit_log` |

---

## 9. Failure modes

| Failure | Behaviour |
|---|---|
| Invalid webhook signature | 401, nothing persisted beyond a log line |
| Duplicate webhook delivery | Unique `dedupe_key`; no-op |
| Unknown `phone_number_id` | 200 and drop — never error, or Meta disables the endpoint |
| Free-form send outside the 24h window | Refused before calling Meta with a 422; the UI offers templates |
| Meta send error | Message `failed` with the readable cause; retry allowed with the same idempotency key |
| Owner disconnects inside the phone app (`account_update` `PARTNER_REMOVED`) | Channel `revoked`, sends blocked, banner and owner notification |
| History sync not started within 24 h of onboarding | Watchdog event alerts the owner with reconnect steps |
| Media download or transcription fails | Backoff retries; then a placeholder and a manual retry; the message row is never lost |
| AI draft fails or a guard rejects it twice | No draft shown, reason stored; the inbox is unaffected |
| LISTEN connection drops | Reconnect with backoff; streams stay open; clients refetch on the next event |
| Worker down | Webhooks still persisted; the backlog drains on recovery in priority order |
| Model budget exhausted | Drafts and profile extraction pause; ingest, assignment, sends and notifications continue |
