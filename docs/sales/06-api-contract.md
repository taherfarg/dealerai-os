# Sales — API contract

**Status:** Draft · **Depends on:** DealerAI OS [07](../07-api-design.md) (conventions), [01](01-architecture.md), [02](02-data-model.md)

Every route here is new unless marked *existing*. The shapes are defined once as Pydantic models in
`apps/api`, which generate `/openapi.json`, which generates the frontend's types — so there is one
definition and CI fails on drift ([07](07-frontend.md) §2).

The initial design of those shapes, in TypeScript, is checked in beside this document:
[`contract/types.ts`](contract/types.ts). It type-checks under `tsc --strict` and is the reference
the Pydantic models are written from. After the models exist, the generated schema wins.

---

## 1. Conventions

Inherited unchanged from DealerAI OS 07: `/v1` prefix · `Authorization: Bearer <Supabase JWT>` ·
`X-Tenant-Id` on every tenant route · RFC 9457 `application/problem+json` for every error ·
cursor pagination `{data, next_cursor}` · money as `{amount_minor, currency}` · RFC 3339 UTC
timestamps · a cross-tenant id returns **404, never 403** · `Idempotency-Key` required on anything
that sends.

Added here:

- **Visibility is invisible.** A list contains only rows the caller may see; it never errors. A
  detail route for a row they may not see returns 404, exactly like another tenant's row. 403 is
  used only when the caller's **role** lacks the permission for an action.
- **`view` instead of filters for the inbox.** `mine`, `unassigned`, `team`, `all` are server-side
  definitions, so the four tabs cannot drift between clients.
- **Long work returns 202 with a job or run id**; nothing blocks on a model call.

---

## 2. Session, team, settings

| Method | Route | Permission | Returns |
|---|---|---|---|
| GET | `/v1/me` | — | `Me`: user, tenant, role, scope, team ids, permissions, accepting_chats |
| PATCH | `/v1/me` | — | `{accepting_chats}` → `Me` |
| GET | `/v1/members` | — | `Member[]` (name, role, teams, languages, availability, open conversations) |
| PATCH | `/v1/members/{user_id}` | `settings.team` | role, teams, languages, accepting_chats |
| POST | `/v1/tenants/{id}/invites` *existing* | `settings.team` | Invitation |
| GET / POST / PATCH / DELETE | `/v1/teams`, `/v1/teams/{id}` | `settings.team` | `Team` |
| GET / PATCH | `/v1/settings/sales` | read: — · write: `settings.routing` | `SalesSettings`: business hours, first-response target, pool visibility, routing rules, default team, AI preferences |

```jsonc
// GET /v1/me
{
  "user": {"id": "…", "name": "Ahmed Nasser", "email": "ahmed@…", "avatar_url": null},
  "tenant": {"id": "…", "slug": "pollux-motors", "name": "Pollux Motors",
             "timezone": "Asia/Dubai", "currency": "AED",
             "logo_url": "https://…", "accent_color": "#4AA0FF"},
  "role": "sales", "scope": "own", "team_ids": ["…"],
  "permissions": ["inbox.send", "leads.mark_won_lost"],
  "accepting_chats": true
}
```

---

## 3. Inbox

| Method | Route | Permission | Notes |
|---|---|---|---|
| GET | `/v1/conversations?view&status&channel_id&q&cursor&limit` | — | `Page<ConversationSummary>`; ordered by waiting first, then latest activity |
| GET | `/v1/conversations/counts` | — | Per view: waiting and unread |
| GET | `/v1/conversations/{id}` | — | `Conversation` (adds summary and the linked lead) |
| GET | `/v1/conversations/{id}/messages?cursor&limit` | — | `Page<Message>`, newest first |
| POST | `/v1/conversations/{id}/messages` | `inbox.send` | `Idempotency-Key` required → the queued `Message` |
| POST | `/v1/conversations/{id}/notes` | — | `{text}` → internal `Message` (`kind: "note"`) |
| POST | `/v1/conversations/{id}/assign` | `inbox.assign`, or self-claim of an unassigned conversation | `{user_id \| null}` |
| POST | `/v1/conversations/{id}/status` | — | `{status}`: open, closed, spam |
| POST | `/v1/conversations/{id}/read` | — | Moves this user's read cursor |
| POST | `/v1/messages/{id}/retry` | `inbox.send` | Re-sends a failed message with its original id |
| POST | `/v1/uploads` | `inbox.send` | multipart → `{upload_id}` |
| GET | `/v1/conversations/{id}/suggestion` | — | `Suggestion \| null` |
| POST | `/v1/conversations/{id}/suggestion/regenerate` | `inbox.send` | 202 |
| POST | `/v1/suggestions/{id}/outcome` | `inbox.send` | `{outcome, final_text?, reason?}` |
| GET | `/v1/channels/{id}/templates` | — | Approved templates for the composer |
| GET | `/v1/quick-replies` | — | Everyone reads; editing needs `settings.quick_replies` |
| GET | `/v1/vehicles?q&status` *existing* | — | The composer's car picker |

```jsonc
// POST /v1/conversations/{id}/messages   — the four bodies
{"type": "text", "text": "…", "reply_to_id": null, "suggestion_id": "…"}
{"type": "attachment", "upload_id": "…", "caption": "…"}
{"type": "template", "template_id": "…", "variables": ["Ahmed", "Hilux GR Sport", "AED 165,000"]}
{"type": "vehicle_card", "vehicle_id": "…", "text": "…"}

// 422 when the window is closed
{"type": "https://api.dealerai.os/errors/window-closed",
 "title": "The 24-hour window is closed",
 "status": 422,
 "detail": "More than 24 hours since the customer's last message. Send an approved template.",
 "trace_id": "01JQ…"}
```

```jsonc
// ConversationSummary — the inbox row
{
  "id": "…",
  "channel": {"id": "…", "platform": "whatsapp", "name": "Pollux Motors"},
  "contact": {"id": "…", "name": "Karim Benali", "primary_display": "+213 …",
              "country": "DZ", "language": "fr", "owner": {"id": "…", "name": "Salem"},
              "tags": ["export"], "lead_band": "hot", "last_seen_at": "…"},
  "status": "open",
  "assignee": {"id": "…", "name": "Salem", "avatar_url": null},
  "team": {"id": "…", "name": "Export"},
  "last_message": {"preview": "Le prix pour Oran ?", "type": "text",
                   "direction": "in", "origin": "customer", "at": "…"},
  "unread_count": 2,
  "waiting_since": "2026-09-16T08:41:00Z",
  "sla_due_at": "2026-09-16T08:46:00Z",
  "sla_state": "due_soon",
  "window_expires_at": "2026-09-17T08:41:00Z",
  "has_ai_draft": true
}
```

`Message` carries every WhatsApp type in one shape — `kind` (message, note, event), `type`,
`origin` (customer, inbox, phone_app, history, system), `author`, `text`, `attachment` with a signed
URL, `transcript`, `location`, `template`, `vehicle`, `reply_to`, `reactions`, `status`, `error`,
`event`, `referral`. Full definition in [`contract/types.ts`](contract/types.ts).

---

## 4. Customers

| Method | Route | Permission |
|---|---|---|
| GET | `/v1/customers?q&owner_id&band&country&tag&cursor` | — |
| GET | `/v1/customers/{id}` | — (404 when not visible) |
| GET | `/v1/customers/{id}/timeline?cursor` | — · all channels merged, newest first |
| PATCH | `/v1/customers/{id}` | — · name, tags, profile fields (saved as human-set) |
| POST | `/v1/customers/{id}/reassign` | `contacts.reassign` |
| POST | `/v1/customers/merge` | `contacts.merge` · `{keep_id, merge_id}` |
| GET | `/v1/customers/{id}/export` | `settings.team` (admin-level) · PDPL export |
| DELETE | `/v1/customers/{id}` | owner or admin · PDPL erasure, audited |

```jsonc
// A profile field as returned and as written
"budget": {"value": {"amount_minor": 15000000, "currency": "AED"},
           "source": "ai", "evidence_message_id": "…", "updated_at": "…"}
// PATCH body — the server stamps source: "human"
{"profile": {"budget": {"amount_minor": 14000000, "currency": "AED"}}}
```

---

## 5. Pipeline and leads

| Method | Route | Permission |
|---|---|---|
| GET | `/v1/pipelines` | — |
| PUT | `/v1/pipelines/{id}/stages` | `pipeline.edit_stages` · 409 when deleting a stage that holds leads |
| GET | `/v1/leads?pipeline_id&owner_id&band&q` | — |
| POST | `/v1/leads` | — · `{contact_id, pipeline_id, vehicle_id?, budget?}` |
| GET | `/v1/leads/{id}` | — · adds score reasons and stage history |
| PATCH | `/v1/leads/{id}` | — · stage, owner, vehicle, budget · won/lost needs `leads.mark_won_lost` and a `lost_reason` for lost |

```jsonc
// GET /v1/leads/{id} — the part the UI explains to the salesperson
"score": 78, "band": "hot",
"score_reasons": [
  {"signal": "asked_price", "label": "Asked the price", "points": 10, "evidence_message_id": "…"},
  {"signal": "shared_id_or_asked_payment_details", "label": "Sent a passport", "points": 25,
   "evidence_message_id": "…"},
  {"signal": "silent", "label": "No reply for 1 week", "points": -10, "evidence_message_id": null}
]
```

---

## 6. Tasks

| Method | Route | Permission |
|---|---|---|
| GET | `/v1/tasks?assignee=me\|team\|{id}&bucket=overdue\|today\|upcoming\|done` | `team` needs a manager scope |
| POST | `/v1/tasks` | — |
| PATCH | `/v1/tasks/{id}` | — · status, due_at, title |
| POST | `/v1/tasks/{id}/send-draft` | `inbox.send` · `Idempotency-Key` → sends the AI follow-up and completes the task |

---

## 7. Dashboards, brief, notifications

| Method | Route | Permission |
|---|---|---|
| GET | `/v1/dashboard/manager?date` | `dashboard.manager` |
| GET | `/v1/dashboard/me` | — |
| GET | `/v1/brief/today` | `dashboard.manager` |
| GET | `/v1/notifications?unread_only&cursor` | — · always the caller's own |
| POST | `/v1/notifications/read` | — · `{ids}` or `{all: true}` |
| POST | `/v1/push-subscriptions` | — · `{endpoint, p256dh, auth, user_agent}` |
| DELETE | `/v1/push-subscriptions/{id}` | — |

The manager dashboard returns tiles, a row per salesperson, the oldest waiting conversations,
pipeline totals, lead sources, the inbox-versus-phone share and the brief — one request, because it
is one screen refreshed together.

---

## 8. Channels and knowledge

| Method | Route | Permission |
|---|---|---|
| GET | `/v1/channels` | — |
| POST | `/v1/channels/whatsapp/connect` | `settings.channels` · `{code, waba_id, phone_number_id}` from Embedded Signup |
| POST | `/v1/channels/{id}/templates/sync` | `settings.channels` |
| POST | `/v1/channels/{id}/health` | `settings.channels` |
| GET | `/v1/channels/{id}/imported-customers?cursor` | `inbox.assign` · the post-import assignment list |
| POST | `/v1/channels/{id}/imported-customers/assign` | `inbox.assign` · `{contact_ids, owner_id}` |
| GET / POST / DELETE | `/v1/documents` | `settings.knowledge` · POST is multipart → 202 |
| GET / POST / PATCH / DELETE | `/v1/quick-replies` | `settings.quick_replies` |

---

## 9. Live stream

```
GET /v1/stream          Authorization: Bearer …, X-Tenant-Id
Accept: text/event-stream

event: message.created
data: {"conversation_id":"…","message_id":"…"}

event: conversation.updated
data: {"conversation_id":"…"}

event: suggestion.ready
data: {"conversation_id":"…","suggestion_id":"…"}

: heartbeat                                   (every 15 s)
```

Event names match `LiveEvent` in [`contract/types.ts`](contract/types.ts). Payloads carry ids only;
the client refetches. There is no replay: on reconnect the client refetches its active queries.
Because the browser's native `EventSource` cannot send headers, the client uses a fetch-based SSE
reader.

---

## 10. Webhooks

`GET /webhooks/whatsapp` (Meta's `hub.challenge`) and `POST /webhooks/whatsapp`, described in
[03](03-whatsapp.md) §4. One URL for every tenant; routing is by `phone_number_id` or WABA id.

---

## 11. Error catalogue

| `type` | Status | When |
|---|---|---|
| `window-closed` | 422 | Free-form send outside the 24-hour window |
| `guard-rejected` | 422 | Outbound text a guard refused |
| `consent-required` | 422 | The customer opted out, or a marketing template without consent |
| `unusable-input` | 422 | A template that is not approved, or the wrong number of variables |
| `channel-unavailable` | 409 | The channel is revoked or in error |
| `stage-in-use` | 409 | Deleting a pipeline stage that still holds leads |
| `already-merged` | 409 | Merging a customer that no longer exists |
| `invalid-request` | 400 | A malformed body, or a send without `Idempotency-Key` |
| `forbidden` | 403 | The role lacks the permission for this action |
| `not-found` | 404 | Missing, another tenant's, or outside the caller's visibility |
| `rate-limited` | 429 | Per-tenant limits, `Retry-After` set |

---

## 12. Permissions by area

| Area | owner / admin | manager | sales | viewer |
|---|---|---|---|---|
| Read the inbox, customers, pipeline, tasks | everything | their teams | their own and the team queue | everything, read-only |
| Send, notes, claim an unassigned chat | ✓ | ✓ | ✓ | — |
| Assign to someone else | ✓ | ✓ | — | — |
| Reassign or merge a customer | ✓ | ✓ | — | — |
| Move a lead, mark won or lost | ✓ | ✓ | ✓ | — |
| Edit pipelines | ✓ | — | — | — |
| Manager dashboard and brief | ✓ | ✓ | — | ✓ |
| Channels, team, knowledge, AI settings | ✓ | — | — | — |
| Routing and response targets | ✓ | ✓ | — | — |
| Quick replies | ✓ | ✓ | read | read |
