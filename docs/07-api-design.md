# API Design

**Status:** Approved · Depends on: [01-system-architecture.md](01-system-architecture.md)

---

## 1. Surfaces

| Surface | Base | Auth | Purpose |
|---|---|---|---|
| Supabase (direct) | `https://<ref>.supabase.co` | User JWT, RLS | All reads and trivial writes from the browser |
| Public API | `https://api.dealerai.os/v1` | User JWT (`Authorization: Bearer`) | Side-effecting actions, agent runs, media |
| Webhooks | `https://api.dealerai.os/webhooks/{platform}` | Platform signature | Inbound events |
| Internal | `https://api.dealerai.os/internal` | Shared-secret HMAC, network-restricted | Next.js server actions, cron triggers |

**The routing rule:** if it only reads, the browser goes straight to Supabase. If it
spends money, calls a model, touches a third party, or must be audited, it goes to
FastAPI. There is no third case.

---

## 2. Conventions

**Versioning.** URL-prefixed `/v1`. Breaking changes get `/v2`; additive fields do not.

**Errors.** RFC 9457 `application/problem+json`, always:

```json
{
  "type": "https://api.dealerai.os/errors/guard-rejected",
  "title": "Content rejected by brand guard",
  "status": 422,
  "detail": "Caption contains a forbidden term: 'cheapest'",
  "instance": "/v1/content/9f2c.../approve",
  "trace_id": "01JQ8Z...",
  "errors": [{"field": "caption", "code": "forbidden_term", "value": "cheapest"}]
}
```

Never a bare string. `trace_id` correlates to `agent_traces` and the logs.

| Status | Meaning here |
|---|---|
| 400 | Malformed request |
| 401 | Missing or invalid token |
| 403 | Authenticated, but not a member of this tenant, or role too low |
| 404 | Not found **or** belongs to another tenant — deliberately indistinguishable |
| 409 | Conflict (duplicate stock number, already published) |
| 422 | Valid syntax, rejected by a guard or business rule |
| 429 | Rate limited, `Retry-After` set |
| 503 | Downstream platform unavailable, retry advised |

**403 vs 404:** a cross-tenant ID returns 404. Returning 403 confirms the resource exists,
which is an enumeration oracle.

**Pagination.** Cursor-based everywhere:

```
GET /v1/vehicles?limit=50&cursor=eyJpZCI6...
→ {"data": [...], "next_cursor": "eyJpZCI6...", "has_more": true}
```

Offsets are wrong on a moving list, and every list here moves.

**Idempotency.** Required on every `POST` that publishes, sends, or spends:

```
Idempotency-Key: <client uuid>
```

Stored 24h against the response. A replay returns the original result and does not
re-execute. Without the header those endpoints return 400 — this is the difference between
a retry and sending a customer the same message twice.

**Tenant resolution.** The JWT carries the user. The tenant comes from
`X-Tenant-Id`, validated against `memberships` on every request. A user in two tenants
must state which. No implicit "current tenant" server-side session.

**Rate limits.** Per tenant: 600 req/min general, 60/min on generation endpoints,
10/min on run creation. Headers: `X-RateLimit-Limit`, `-Remaining`, `-Reset`.

**Timestamps** are RFC 3339 UTC. **Money** is `{"amount_minor": 6600000, "currency": "AED"}`,
never a formatted string, never a float.

---

## 3. Routes

### Tenants & members

```
GET    /v1/tenants                       tenants the caller belongs to (no X-Tenant-Id)
POST   /v1/tenants                       create (also creates owner membership)
GET    /v1/tenants/{id}
PATCH  /v1/tenants/{id}                  name, timezone, locales, autonomy_mode, autonomy_rules
GET    /v1/tenants/{id}/members
POST   /v1/tenants/{id}/invites          {email, role} -> signed, 7-day, single-use token
POST   /v1/invites/accept                {token} -> membership (idempotent)
DELETE /v1/tenants/{id}/members/{uid}
GET    /v1/tenants/{id}/usage            AI spend this period vs budget
```

### Brand

```
GET    /v1/brand                         brand profile
PUT    /v1/brand                         full replace after human confirmation
POST   /v1/brand/ingest                  → 202 {run_id}  — extract from uploads
POST   /v1/brand/assets                  multipart: logo, font, watermark
GET    /v1/brand/templates               tenant + global creative templates
```

### Vehicles

```
GET    /v1/vehicles                      ?status&make&model&min_price&max_price&stale_days&q
POST   /v1/vehicles
GET    /v1/vehicles/{id}
PATCH  /v1/vehicles/{id}
POST   /v1/vehicles/{id}/status          {status, reason} — 'sold' cascades (W4)
POST   /v1/vehicles/{id}/price           {amount_minor, reason} — writes price_history
POST   /v1/vehicles/{id}/media           multipart, N files → 202 {run_id} for QA
DELETE /v1/vehicles/{id}/media/{mid}
POST   /v1/vehicles/import               multipart CSV → 202 {run_id, mapping_preview}
POST   /v1/vehicles/import/{run_id}/confirm   {mapping} — human confirms columns
GET    /v1/vehicles/stock-report         aging, content coverage, gaps
```

### Content

```
GET    /v1/content                       ?status&vehicle_id&from&to&kind
POST   /v1/content/generate              {vehicle_ids[], objective, count, locales[], kinds[]}
                                         → 202 {run_id}
GET    /v1/content/{id}
PATCH  /v1/content/{id}                  edit copy, swap asset, change concept
POST   /v1/content/{id}/render           → 202 {run_id}  — re-render after edits
POST   /v1/content/{id}/approve          {channel_ids[], scheduled_at?}
POST   /v1/content/{id}/reject           {reason} — reason is a learning signal
POST   /v1/content/{id}/schedule         {channel_ids[], scheduled_at}
POST   /v1/content/{id}/publish          publish now (idempotency required)
DELETE /v1/content/{id}
GET    /v1/content/calendar              ?from&to → slots, gaps, conflicts
```

### Channels

```
GET    /v1/channels
GET    /v1/channels/oauth/{platform}/start     → {authorize_url, state}
GET    /v1/channels/oauth/{platform}/callback  → redirect to app
POST   /v1/channels/{id}/health
DELETE /v1/channels/{id}
```

### Inbox

```
GET    /v1/conversations                 ?status&surface&assigned_to&unread
GET    /v1/conversations/{id}            with messages
POST   /v1/conversations/{id}/reply      {body, media[]} — human reply (idempotency required)
POST   /v1/conversations/{id}/ai-reply   → 202 {run_id} — ask the agent to draft
POST   /v1/conversations/{id}/assign     {user_id} — sets ai_paused
POST   /v1/conversations/{id}/resume-ai
POST   /v1/conversations/{id}/status     {status}
```

### CRM

```
GET    /v1/contacts                      ?q&tag&source
GET    /v1/contacts/{id}                 Customer 360
PATCH  /v1/contacts/{id}
GET    /v1/leads                         ?stage&band&owner&next_action_before
POST   /v1/leads
PATCH  /v1/leads/{id}                    stage, owner, vehicle, budget
POST   /v1/leads/{id}/score              → 202 {run_id} — rescore
POST   /v1/leads/{id}/activities         {kind, body, occurs_at}
POST   /v1/deals                         {lead_id, vehicle_id, amount_minor} — closes the loop
```

### Agent runs

```
POST   /v1/runs                          {goal, input, agent?} → 202 {run_id}
GET    /v1/runs                          ?status&from&to
GET    /v1/runs/{id}                     plan, tasks, artifacts, cost
GET    /v1/runs/{id}/stream              SSE, see § 4
POST   /v1/runs/{id}/cancel
GET    /v1/runs/{id}/traces              model + tool calls, tokens, cost
```

### Approvals

```
GET    /v1/approvals                     ?status=pending
POST   /v1/approvals/{id}/approve        {note?}
POST   /v1/approvals/{id}/reject         {note}
POST   /v1/approvals/bulk                {ids[], decision}
```

### Analytics

```
GET    /v1/analytics/overview            ?from&to  — the daily-brief payload
GET    /v1/analytics/content             per item and aggregate performance
GET    /v1/analytics/funnel              impressions → leads → qualified → deals
GET    /v1/analytics/vehicles            content coverage and aging
GET    /v1/analytics/costs               AI spend by agent, model, day
```

### Knowledge

```
GET    /v1/documents
POST   /v1/documents                     multipart → 202 {run_id} chunk + embed
DELETE /v1/documents/{id}
GET    /v1/playbook                      active version
GET    /v1/playbook/versions
POST   /v1/playbook/{version}/activate   rollback or accept a proposal
```

### Ads — Phase 2

```
GET    /v1/ads/campaigns                 with joined real CPL
GET    /v1/ads/campaigns/{id}
POST   /v1/ads/campaigns                 → 202 {run_id}   (P2 write)
POST   /v1/ads/entities/{id}/budget      {amount_minor, reason}  → budget guard
POST   /v1/ads/entities/{id}/status      {status, reason}
GET    /v1/ads/insights                  ?from&to&level
```

---

## 4. Streaming an agent run

```
GET /v1/runs/{run_id}/stream
Accept: text/event-stream
```

```
event: run.started
data: {"run_id":"...","goal":"Generate content for MG6","autonomy":"assisted"}

event: run.planned
data: {"tasks":[{"key":"t1","agent":"content_strategist"}, ...],"estimated_cost_usd":2.40}

event: task.started
data: {"key":"t1","agent":"content_strategist"}

event: task.completed
data: {"key":"t1","summary":"6 briefs created","cost_usd":0.31}

event: artifact.created
data: {"type":"content_item","id":"...","preview_url":"https://..."}

event: approval.required
data: {"approval_id":"...","kind":"publish_content","summary":"Publish 6 posts to Instagram"}

event: run.completed
data: {"status":"partial","completed":5,"failed":1,"cost_usd":2.18,
       "summary":"5 of 6 pieces produced. 1 rejected by brand guard: forbidden term."}

: heartbeat
```

Rules: heartbeat comment every 15 s so proxies do not close the connection; `Last-Event-ID`
supported for reconnect (events are replayed from `agent_tasks`); the stream is a **view**,
never the source of truth — if the client disconnects, the run continues and the UI
recovers state from `GET /v1/runs/{id}`.

---

## 5. Webhooks in

```
POST /webhooks/meta        Instagram + Facebook comments, mentions, messages
GET  /webhooks/meta        hub.challenge verification
POST /webhooks/whatsapp    messages, delivery and read receipts, template status
POST /webhooks/tiktok      publish status callbacks
```

Every handler, in this exact order:

1. **Verify the signature before parsing the body.** Meta and WhatsApp:
   `X-Hub-Signature-256`, HMAC-SHA256 with the app secret, constant-time compare on the
   raw bytes. Invalid → 401, log, stop.
2. Insert `webhook_deliveries` with the raw payload.
3. Resolve platform account ID → `channels` → `tenant_id`. Unknown account → 200 and drop
   (we are not the owner of that account; do not error, or the platform disables the
   endpoint).
4. Insert an `events` row with `dedupe_key` = the platform's message or comment ID.
5. **Return 200 within 500 ms.** No model calls, no connector calls, no image work.

Platforms retry aggressively and disable endpoints that are slow or error-prone. Steps 1–5
are pure database work by design.

**Replay safety:** the partial unique index on `(tenant_id, event_type, dedupe_key)` makes
duplicate deliveries a no-op insert.

---

## 6. Internal endpoints

Called only by Next.js server actions and the scheduler. Network-restricted plus an HMAC
of `(timestamp, method, path, body)` in `X-Internal-Signature`, 5-minute clock skew
tolerance.

```
POST /internal/events                    enqueue an event
POST /internal/cron/{job}                trigger a scheduled sweep
GET  /internal/health                    liveness + connector + queue depth
GET  /internal/metrics                   Prometheus
```

`/internal/health` returns degraded rather than failing when a *connector* is down — a
broken Instagram token must not take the API out of the load balancer.

---

## 7. FastAPI implementation notes

- **`async def` everywhere.** One blocking call in a sync route stalls the event loop for
  every tenant. Anything CPU-bound (image work, FFmpeg) runs in the worker, never in a
  request.
- **Dependency-injected tenant context**, resolved once per request:

```python
async def tenant_ctx(
    request: Request,
    x_tenant_id: Annotated[UUID, Header()],
    user: Annotated[User, Depends(current_user)],
) -> TenantContext:
    if not await is_member(user.id, x_tenant_id):
        raise HTTPException(404)            # never 403 — see § 2
    return TenantContext(tenant_id=x_tenant_id, user=user, role=...)
```

  Every route takes `ctx: Annotated[TenantContext, Depends(tenant_ctx)]`. A route without
  it fails a CI check.
- **Pydantic v2 models for every request and response**, and the same models are the
  agents' structured-output schemas. One definition, two uses.
- **`response_model` on every route** so the OpenAPI schema is real. The Next.js client is
  generated from it — hand-written TypeScript API types drift within a sprint.
- **Long work returns 202 with a `run_id`.** No endpoint blocks on a model call chain.
- **`SET LOCAL app.tenant_id`** happens in the `tenant_session` context manager, the only
  place in the codebase that acquires a connection ([03](03-database-schema.md) § 2).
