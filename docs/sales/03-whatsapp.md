# Sales — WhatsApp

**Status:** Draft · **Depends on:** [01](01-architecture.md), [02](02-data-model.md)

Everything specific to WhatsApp: the platform rules the design depends on, Meta onboarding, how each
webhook becomes data, identity, the 24-hour window, sending, media and coexistence.

---

## 1. Platform facts this design depends on

Verified against Meta's documentation on 2026-09-15. Re-check the ones marked † when implementing —
field names and dates move.

| Fact | Consequence here |
|---|---|
| The WhatsApp Business Platform (Cloud API) is the only supported integration | No WhatsApp Web automation, ever ([00](00-prd.md) §9) |
| **Coexistence** lets one number run on the WhatsApp Business app and the Cloud API together. Only Solution Partners and Tech Providers can onboard it | Pollux Motors registers as a Tech Provider (§2) |
| Coexistence numbers have a fixed throughput of 20 messages per second | Far above dealer volume; the rate guard respects it |
| Messages sent from the app are free, arrive as `smb_message_echoes`, and do not open or extend the 24-hour window | Echo handling (§4, §9) |
| History sync covers up to 180 days in three phases, in chunks with progress. Media ids only for messages within 14 days of onboarding. Sync must be started within 24 hours of onboarding | Import pipeline and watchdog (§9) |
| Contacts from the phone arrive as `smb_app_state_sync` | Identity resolution (§5) |
| Onboarding unlinks companion devices; up to four can be re-linked, except WhatsApp for Windows and WearOS, whose messages never reach webhooks | Onboarding rules for the sales team (§2) |
| Coexistence numbers: no calls or groups through the API; broadcast lists become read-only | Non-goals; template campaigns in Phase 2 |
| Every messages webhook carries a business-scoped user id (BSUID) since April 2026. The phone number can be omitted for users with a username who have not interacted with that business number in 30 days and are not in its contacts. Sending to a BSUID works since July 2026 (`recipient`). A BSUID changes when the user changes phone number (`user_id_update`) † | BSUID-first identity (§5) |
| Free-form messages only within 24 hours of the customer's last message; templates outside it | Window rules (§6) |
| Per-message pricing since July 2025: service messages free; utility templates free inside the window; marketing templates always charged; free entry point after Click-to-WhatsApp ads † | Cost labels; referral stored for lead source |
| From 1 October 2026 several markets move to standalone rate cards with higher utility and authentication rates, Morocco and Oman among them | Export follow-ups prefer the open window |
| Messaging limits apply per business portfolio: unverified portfolios send business-initiated messages to 250 customers per 24 hours; verification unlocks higher tiers | Business verification in week 1 |
| General-purpose AI assistants are prohibited on the Business Platform since 15 January 2026; business-scoped assistants are allowed | The copilot's scope ([04](04-ai-copilot.md) §1) |
| Media download URLs are short-lived | Download immediately in the worker (§8) |

---

## 2. Meta onboarding — the critical path

The Tech Provider is **Pollux Motors**. Nothing here blocks development, which runs on the mock
connector, the simulator and Meta's test number; it blocks connecting the real number.

| When | Step | Who |
|---|---|---|
| Week 1 | Business verification of the Pollux Motors portfolio (trade licence, address, phone, website, domain email) | Founder |
| Week 1 | Meta developer app "DealerAI Sales" (Business type) with the WhatsApp product; privacy policy and terms URLs; icon | Founder, Claude drafts the pages |
| Week 1 | Test WABA and test number; up to five recipient numbers added | Founder |
| Week 2–3 | Working send and template-creation flow against the test number | Claude |
| Week 2–3 | App review: two screen recordings (a message sent from our app arriving in WhatsApp; a template created), request **advanced access** to `whatsapp_business_messaging` and `whatsapp_business_management` | Founder records, Claude prepares the script |
| After approval | Tech Provider enrolment; Embedded Signup configuration with WhatsApp Business app onboarding enabled | Founder |
| After approval | Webhook subscriptions: `messages`, `smb_message_echoes`, `history`, `smb_app_state_sync`, `message_template_status_update`, `account_update`, `phone_number_quality_update`, `user_id_update` † | Claude |
| After approval | Payment method on the WABA; three utility templates in AR/EN/FR (`vehicle_available`, `price_update`, `appointment_reminder`) | Founder |
| Pilot start | Connect Pollux's number through our own Embedded Signup; sync starts immediately | Founder, Claude on call |

### Rules for the Pollux team (printed and pinned)

1. Keep the WhatsApp Business app updated, and open it on the phone at least weekly — a device
   inactive for 14–30 days can be disconnected.
2. After onboarding, re-link WhatsApp Web or desktop if you use them. **Never use WhatsApp for
   Windows** — what you send from it is invisible to the platform.
3. Never press *Settings → Business Platform → Disconnect* in the app. It disconnects the number.
4. Broadcast lists become read-only. New-arrival messages go through templates (Phase 2).

---

## 3. Channel record

| `channels` column | WhatsApp value |
|---|---|
| `platform` | `whatsapp` |
| `external_id` | `phone_number_id` — globally unique across tenants |
| `account_id` | WABA id — `account_update` webhooks route by it |
| `handle`, `display_name` | Display phone number and verified business name |
| `mode` | `coexistence` or `cloud_api` |
| `credentials` | Business token from the Embedded Signup code exchange, MultiFernet-encrypted (DealerAI OS T0.7) |
| `sync_state` | `{contacts_started_at, history_started_at, phase, progress, completed_at}` |
| `quality_rating`, `health` | From the daily health check and `phone_number_quality_update` |

---

## 4. Webhooks → events

`GET /webhooks/whatsapp` answers Meta's `hub.challenge` with the verify token.
`POST /webhooks/whatsapp` follows [01](01-architecture.md) §2C: signature, persist, route
(`app.route_whatsapp`), one event per item, 200 in under 500 ms.

| Webhook item | Event | Dedupe key | Handler (priority) |
|---|---|---|---|
| `messages.messages[]` | `whatsapp.message_received` | message id | Resolve identity → open or reopen conversation → insert message (`origin=customer`) → window = timestamp + 24h → `waiting_since`, `sla_due_at` → assign if unassigned → notify → queue media download and transcription → queue AI draft after 20 s → store `referral` (10) |
| `messages.statuses[]` | `whatsapp.status_received` | message id + status | Move status forward only (`sent` < `delivered` < `read`; `failed` terminal); store `pricing` and error. Unknown message id → retry with backoff, then drop (10) |
| `smb_message_echoes` | `whatsapp.echo_received` | message id | Insert `origin=phone_app`, `sender=human`, no author → stop waiting, set `first_response_at` → supersede the live AI draft → **no window change** (10) |
| `history` | `whatsapp.history_chunk` | channel + phase + chunk order | Import with `app.suppress_rt`; no side effects; update `sync_state`; final chunk emits `channel.history_imported` (0) |
| `smb_app_state_sync` | `whatsapp.contacts_synced` | phone + timestamp | Upsert contact names and phone identities (8) |
| `message_template_status_update` | `whatsapp.template_status` | template id + status + time | Update `message_templates`; rejected → notify admins (2) |
| `account_update` | `whatsapp.account_update` | WABA + event + time | `PARTNER_REMOVED` → channel `revoked`, sends blocked, notify owner (10) |
| `user_id_update` | `whatsapp.user_id_changed` | previous + current | Replace the BSUID identity value; the contact is unchanged (8) |
| `phone_number_quality_update` | `whatsapp.quality_update` | phone + time | Store rating; notify owner on yellow or red (2) |

Replays are safe by construction: `events` dedupes on `(tenant_id, event_type, dedupe_key)`, and
messages are unique on `(tenant_id, external_id)`.

---

## 5. Identity resolution

Input: `contacts[]` (`profile.name`, `wa_id` when present, `user_id` = BSUID) and the message's
`from` / `from_user_id`.

```
phone  = E.164('+' + wa_id)  if wa_id else None
bsuid  = user_id
country = bsuid prefix ("AE.…" → AE) else the phone's country code

pg_advisory_xact_lock(hash(tenant_id, bsuid or phone))     -- one resolver per identity at a time
1. contact_identities(kind='whatsapp_user_id', value=bsuid)  → found: done
2. contact_identities(kind='phone', value=phone)             → found: attach the BSUID identity; done
3. create contact (name from profile, country, team by routing) + identities (bsuid, phone if any)
```

- The advisory lock serialises concurrent webhooks for the same new customer; the unique index on
  `(tenant_id, kind, value)` is the backstop if the lock is ever bypassed.
- The WhatsApp profile name updates `contacts.full_name` only while nobody on the team has edited it.
- **No merging by name or email similarity.** A customer who hid their number and later writes from
  Instagram is two contacts until a person merges them.
- `user_id_update` rewrites the value of the existing BSUID identity, so the customer keeps their
  history.

---

## 6. The 24-hour window and templates

- `conversations.wa_window_expires_at = last customer message time + 24h`. Echoes and our own
  sends never move it.
- Free-form types (text, media, car card) need an open window. The API refuses them with a 422
  **and** the connector raises `OutsideMessagingWindow` — two layers, because a customer receiving
  a message Meta rejects is still a failed promise.
- Templates are always allowed, subject to consent: **marketing** templates require
  `consent.marketing = true` and no opt-out; **utility** templates are for transactional updates to
  customers who wrote first. A wrong category is a rejection or a recategorisation by Meta.
- A customer message containing an opt-out ("stop", "لا تراسلني", "arrêtez") sets
  `consent.opted_out_at` in code; every business-initiated send checks it.
- Phase 1 shows cost only as a "Paid message" label on marketing templates. Exact per-country
  prices are Phase 2.

---

## 7. Sending

| Type | Phase 1 | Notes |
|---|---|---|
| Text | Yes | Link previews off by default; `context.message_id` for replies |
| Image, document, video | Yes | Uploaded to Meta by media id |
| Car card | Yes | Sent as the hero photo plus a caption rendered from the vehicle record — the price comes from the database, never typed, so no guard can be bypassed by it |
| Template | Yes | Body variables; header media in Phase 2 |
| Mark as read | Yes | When a salesperson opens the thread, for the latest inbound message |
| Voice note recorded in the browser | Phase 2 | Browsers record WebM/Opus; WhatsApp voice notes need OGG/Opus |
| Reactions, typing indicator, location | Phase 2 | |

### Double-send protection

Meta's send API takes no idempotency key, so the guarantee is ours:

1. The route creates the message row (`queued`) with the client's `Idempotency-Key`; a replayed key
   returns the same row.
2. The send handler moves `queued → sending` with `locked_at` in one statement, then calls Meta, then
   stores the WhatsApp message id and `sent`.
3. A row found in `sending` without an id after 2 minutes is **not** resent. It becomes `failed` with
   "Delivery unknown — check the conversation before resending". Guessing on a customer-facing double
   send is the wrong default; a person decides.

(`sending` is added to the `messages.status` check in `0006_sales.sql`.)

---

## 8. Media and voice notes

- Inbound media: `GET /{media-id}` → short-lived URL → download with the business token →
  Storage at `{tenant}/messages/{yyyy}/{mm}/{uuid}.{ext}` → `messages.media`
  `[{storage_path, mime, size_bytes, sha256, filename, duration_s, width, height}]`.
- Voice notes (`audio/ogg; codecs=opus`) → gateway task `transcribe` → `messages.transcript
  {text, language}`. Arabic dialects and French mixed with Darija are expected; the transcript is
  always shown next to the audio, never instead of it.
- Failures retry with backoff, then leave a placeholder with a manual retry. The message row is
  written before any media work, so a customer's message is never lost to a download error.
- Stickers render as images; unsupported types store the raw type and render "Open on the phone".

---

## 9. Coexistence

### Connecting

```
Settings → Connect WhatsApp → Meta Embedded Signup (WhatsApp Business app onboarding)
  → POST /v1/channels/whatsapp/connect {code, waba_id, phone_number_id}
  → exchange code for the business token (encrypted)
  → subscribe the app to the WABA's webhooks
  → do NOT register the number (the app already has it)
  → start contacts sync, start history sync       ← Meta allows 24 hours
  → watchdog events at +2h and +20h: no history webhook yet → alert the owner with reconnect steps
```

### Importing history

- Each thread resolves its customer through §5 and lands in that customer's conversation for this
  channel — the same conversation live messages use, so nothing is duplicated.
- Messages keep their original timestamps with `origin=history`. No AI drafts, no notifications, no
  response timers, no unread counts.
- After the last chunk: conversations with activity in the last 7 days stay `open`, older ones become
  `closed`; `waiting_since` is set only when the last message is the customer's and is less than
  24 hours old.
- Imported customers are unassigned, routed to a team by the routing rules. Settings → Channels shows
  "Assign imported customers": a list by last activity with bulk assignment, so the manager
  distributes the backlog once instead of the round-robin flooding one person.
- The imported history is also the source of the copilot's golden set and the response-time
  baseline ([04](04-ai-copilot.md) §9, [00](00-prd.md) S2).

### Living with the phone app

- A reply typed on the phone appears in the thread within seconds, labelled "Sent from phone".
- If an echo arrives while someone is typing in the inbox, the composer shows "A reply was just sent
  from the phone" before they send.
- Replies from the phone skip the copilot, guards and authorship. The manager dashboard shows the
  inbox-versus-phone share so that stays visible.
- Disconnecting from inside the app (`PARTNER_REMOVED`) keeps all history, blocks sending and alerts
  the owner. The platform cannot disconnect a coexistence number itself; the app's Disconnect button
  is the only way.

---

## 10. Tests

| Layer | Covers |
|---|---|
| Recorded fixtures | One anonymised payload per webhook item type in `tests/connectors/fixtures/whatsapp/` |
| Signature | Tampered body, wrong secret, missing header → 401 and nothing persisted |
| Contract suite | Window refusal, template send, idempotent replay, typed failures — shared with the mock |
| Ingest | Status only moves forward; unknown message id retries then drops; echo supersedes the draft and stops the timer; history chunk replay creates nothing twice; BSUID change keeps the contact; a customer with no phone resolves by BSUID |
| Concurrency | Ten simultaneous deliveries from one new customer produce exactly one contact |
| Double send | A row stuck in `sending` is never resent automatically |
| Load | 50 requests per second burst, p95 acknowledgement under 500 ms |
| Live smoke (staging, test number, manual) | Text, image, voice note and template, both directions |
