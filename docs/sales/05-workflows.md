# Sales — Workflows

**Status:** Draft · **Depends on:** [01](01-architecture.md)–[04](04-ai-copilot.md), DealerAI OS [05](../05-workflows.md)

Every behaviour is an event handler on the DealerAI OS queue: transactional enqueue, `SKIP LOCKED`
claim, exponential backoff, dead letter after five attempts, a reaper for stuck rows. Handlers are
idempotent on `(event_type, dedupe_key)`.

---

## 1. Event catalogue additions

| Event | Emitted by | Handler does | Priority |
|---|---|---|---|
| `whatsapp.message_received` | Webhook | Ingest ([03](03-whatsapp.md) §4) | 10 |
| `whatsapp.status_received` | Webhook | Status update | 10 |
| `whatsapp.echo_received` | Webhook | Store phone-app reply, stop the timer | 10 |
| `whatsapp.account_update` | Webhook | Channel state | 10 |
| `whatsapp.send_requested` | Send API, task draft send | Claim `queued → sending`, then the connector | 10 |
| `whatsapp.send_watchdog` | The send claim, +2 min | A send still `sending` becomes "delivery unknown" | 10 |
| `conversation.assign_requested` | Ingest, rep stops taking chats, opening-time sweep | Routing | 8 |
| `conversation.sla_check` | Every minute | Due-soon and missed notifications | 8 |
| `whatsapp.contacts_synced` | Webhook | Upsert names and phones | 8 |
| `whatsapp.user_id_changed` | Webhook | Rewrite BSUID identity | 8 |
| `channel.connected` | Connect API | Start syncs, schedule watchdogs | 8 |
| `channel.sync_watchdog` | +2h, +20h | Alert if no history arrived | 8 |
| `contact.reassigned` | Reassign API | Notify the new owner | 8 |
| `notification.push_requested` | A notification row | Web push to the user's subscriptions | 8 |
| `task.due_check` | The `tasks_book_due` trigger, at the task's due time | Tell the assignee, unless it was done or moved | 5 |
| `message.media_requested` | Ingest | Download media to Storage | 5 |
| `message.transcription_requested` | Media stored, audio | Transcribe | 5 |
| `copilot.draft_requested` | Ingest, +20 s | Draft loop ([04](04-ai-copilot.md) §3) | 5 |
| `conversation.idle` | Any message, +15 min | Profile, signals, score, summary | 2 |
| `followup.check` | Hourly sweep, `vehicle.price_changed`, `vehicle.created` | Eligibility → follow-up agent → task | 2 |
| `whatsapp.template_status` | Webhook | Template state | 2 |
| `whatsapp.templates_sync_requested` | Connect API, Settings, daily sweep | Re-read the WABA's templates | 2 |
| `whatsapp.quality_update` | Webhook | Quality rating | 2 |
| `channel.history_imported` | Final history chunk | Recompute conversation state, notify | 2 |
| `whatsapp.history_chunk` | Webhook | Import messages | 0 |
| `document.uploaded` | Knowledge API | Extract, chunk, embed | 0 |
| `sales.brief_due` | 08:00 tenant time | Brief agent | 0 |

### Cron (APScheduler only emits events)

| Schedule | Emits |
|---|---|
| Every minute | `conversation.sla_check` |
| Every 15 minutes | `conversation.assign_requested` for unassigned conversations whose team just opened |
| Hourly | `followup.check` sweep |
| Daily 03:00 | Template sync and channel health per WhatsApp channel |
| Daily 02:00 | Score decay, retention purge (existing job extended) |
| 08:00 tenant time | `sales.brief_due` |

---

## 2. S1 — A customer writes

```
POST /webhooks/whatsapp ── verify ── persist ── route ── event ── 200            [< 500 ms]
   ▼ whatsapp.message_received
resolve identity (BSUID → phone → create)                          [03 §5]
conversation: find open for (contact, channel), else reopen the latest, else create
insert message (origin=customer) ── unique (tenant_id, external_id) makes a replay a no-op
update: last_message_at, last_inbound_at, wa_window_expires_at = ts + 24h, unread,
        waiting_since (if not already waiting), sla_due_at = hours.due(waiting_since, target)
media?  → message.media_requested (→ message.transcribe_requested for audio)
unassigned? → conversation.assign_requested
opt-out phrase? → consent.opted_out_at = now (code, before anything else is queued)
intent-worthy? → copilot.draft_requested (+20 s) · conversation.idle (+15 min)
notify: the assignee, or the team's managers when unassigned
commit → live-update trigger → the inbox shows it
```

| Failure | Behaviour |
|---|---|
| Identity lock timeout | Event retries; nothing half-written — everything above is one transaction |
| Media download fails | The message is already visible with a "media unavailable, retry" placeholder |
| The conversation was closed | Reopened with an event line "Reopened by customer message" |

---

## 3. S2 — A salesperson replies from the inbox

```
POST /v1/conversations/{id}/messages   Idempotency-Key
   permission inbox.send · visible under RLS · free-form + window closed → 422
   insert message (queued, origin=inbox, author) + message.send_requested   [one transaction]
   ▼
send handler: queued → sending (locked_at) → connector.send → external id → sent
   stop waiting: first_response_at (if null), waiting_since = null, sla_due_at = null
   draft involved? → ai_suggestions.outcome
   ▼
statuses webhook → delivered → read
```

| Failure | Behaviour |
|---|---|
| `OutsideMessagingWindow` from the connector | `failed`, "Window closed — send a template" |
| Meta error | `failed` with the readable cause; Retry reuses the same message row |
| Crash between Meta and our write | Row stuck in `sending` → after 2 minutes `failed`, "Delivery unknown — check the conversation before resending". Never auto-resent |

---

## 4. S3 — Someone replies from the phone app

```
smb_message_echoes → whatsapp.echo_received
insert message (origin=phone_app, sender=human, no author)
stop waiting (first_response_at if null) · supersede the live draft · window unchanged
live update → thread shows "Sent from phone"; an open composer shows "A reply was just sent from the phone"
```

---

## 5. S4 — Assignment and response targets

```
conversation.assign_requested
   customer has an owner who is accepting chats            → assign to the owner
   else routing rules, first match (language, country, ad)  → team (else default team)
   inside the team: least recently assigned member who is accepting chats,
     inside business hours, under max_open_conversations
     select … for update skip locked on memberships        (two assignments never pick the same person twice)
   nobody available → stays in the team queue; the 15-minute sweep retries when the team opens
   assign → conversations.assigned_to, owner_id (if the customer had none, contacts.owner_id too),
            last_assigned_at = now, event line, notification

conversation.sla_check (every minute)
   waiting and due within 2 minutes → push the assignee (once)
   waiting and past due             → notify the assignee and the team's managers (once); sla_state = breached
   unassigned for longer than the target → notify the team's managers (once)
```

"Once" is enforced by a dedupe key per conversation, level and waiting period. Business hours are
computed by `sales/hours.py` — a customer writing at 23:30 is due at opening plus the target, not in
five minutes.

---

## 6. S5 — AI draft

The loop in [04](04-ai-copilot.md) §3. Workflow-level failure handling:

| Failure | Behaviour |
|---|---|
| Model 429 or 5xx | Gateway retries with jitter; still failing → no draft; nothing else waits on it |
| Guard rejects twice | `blocked` with the reason, shown as a slim row in the composer |
| A newer message arrives mid-draft | The finished draft is saved as `superseded`, never shown |
| Budget exhausted | No draft; tenant owners notified once per day |

---

## 7. S6 — Profile, summary and score

```
conversation.idle (15 minutes after the last message, only if nothing newer)
   ≥ 2 new customer messages since the last run? else stop
   profile agent → updates, signals, summary
   code: drop updates to human-set fields, drop evidence outside this conversation, validate values
   write profile · summary · score_signals → scoring.score() → leads.score, band, score_reasons
   band changed to hot → notify the owner ("Karim is now a hot lead")
```

---

## 8. S7 — Follow-up

```
followup.check (hourly sweep · price drop · similar arrival)
   eligibility in code ([04](04-ai-copilot.md) §6) ── fail → stop, record why in the event result
   followup agent → genuine_reason?
      no  → stop; the cadence decides when to look again
      yes → guards on the draft → task (follow_up, ai, due now or at opening) + notification
   salesperson: Send now → message.send_requested with the draft (text or template)
                Edit in conversation → composer prefilled
                Skip → task cancelled with a reason
```

---

## 9. S8 — Reassign a customer

```
POST /v1/customers/{id}/reassign {owner_id}      permission contacts.reassign
   app.reassign_contact() — one transaction:
     contacts.owner_id · open conversations (owner_id, assigned_to) · open leads · open tasks
     event line in each open conversation · audit_log
   contact.reassigned → notify the new owner
```

---

## 10. S9 — Merge two customers

```
POST /v1/customers/merge {keep_id, merge_id}     permission contacts.merge
   app.merge_contacts() — one transaction:
     identities, conversations, leads, tasks, activities → keep
     profile: keep's human fields win, then keep's AI fields, then merge's
     delete the merged contact · audit_log with both snapshots
```

A merge is not undoable; the audit snapshot is what a manual repair would start from.

---

## 11. S10 — Connect WhatsApp and import history

```
Settings → Connect WhatsApp → Embedded Signup → POST /v1/channels/whatsapp/connect
   exchange code · encrypt token · subscribe webhooks · (coexistence) skip registration
   channel.connected → start contacts sync + history sync · schedule watchdogs (+2h, +20h)
whatsapp.contacts_synced ... → names and phones
whatsapp.history_chunk ...   → messages (origin=history), sync_state.progress, no side effects
channel.history_imported     → conversation state recomputed ([03](03-whatsapp.md) §9)
                               → owner notified: "History imported: 1,240 conversations. Assign them."
```

| Failure | Behaviour |
|---|---|
| Watchdog finds no history webhook | Owner alert with reconnect steps (Meta's 24-hour limit) |
| A chunk fails to import | Retries; replaying a chunk creates nothing twice |
| The owner closes Embedded Signup halfway | No channel row is created; nothing to clean up |

---

## 12. S11 — The channel breaks

| Signal | Behaviour |
|---|---|
| `account_update` `PARTNER_REMOVED` | Channel `revoked`; sends refused with "WhatsApp was disconnected from the phone app"; red banner; owner notified |
| Token rejected by the Graph API | Channel `error` (`TokenExpired`, not retried); banner with Reconnect |
| Quality rating yellow or red | Owner notified; follow-up templates paused on red |

History, customers and conversations stay intact in every case.

---

## 13. S12 — Daily brief

```
sales.brief_due (08:00 tenant time)
   SQL gathers: yesterday's conversations, first-response medians per rep, missed targets,
                customers still waiting, new and hot leads, stage moves, won and lost,
                overdue tasks per rep, inbox-vs-phone share, cars most asked about
   SQL ranks candidates for attention (longest waits, hot leads without a next action, reps with
                the most overdue follow-ups)
   brief agent writes the headline and up to five items — every number comes from the SQL input;
                the price guard runs on the text
   store · notify owners and managers · show on the dashboard
```

---

## 14. S13 — Retention and erasure

```
nightly retention job
   messages, transcripts, identities past the tenant's retention → deleted (cascade)
   their media objects → a worker job deletes them from Storage
   ai_suggestions older than 12 months → aggregated, then deleted
   notifications older than 90 days → deleted

DELETE /v1/customers/{id}  (owner or admin)
   export offered first · cascade delete · media deletion queued · audit_log keeps who and when, not what
```
