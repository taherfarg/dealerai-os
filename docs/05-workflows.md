# Workflows

**Status:** Approved · Depends on: [02-agent-architecture.md](02-agent-architecture.md)

Every behaviour in the product is an event handler. This document is the catalogue and
the end-to-end flows.

---

## 1. Event catalogue

`M` = milestone. Handlers live in `src/handlers/<domain>.py` and are registered by name.

### Inventory

| Event | Emitted when | Handler does | M |
|---|---|---|---|
| `vehicle.created` | Vehicle added or imported | Enrich specs, queue photo QA, emit `vehicle.ready` | M2 |
| `vehicle.media_uploaded` | Photos uploaded | Vision QA, angle labelling, ranking, hero selection | M2 |
| `vehicle.ready` | Enrichment complete | Suggest a content plan for this vehicle | M3 |
| `vehicle.price_changed` | Price row written | Flag published content showing the old price | M4 |
| `vehicle.sold` | Status → sold | **Unpublish or pause every ad and scheduled item for it** | M4 |
| `vehicle.stale` | Nightly: in stock > tenant threshold with low content | Content Strategist proposes a push | M6 |

### Content

| Event | Emitted when | Handler does | M |
|---|---|---|---|
| `content.requested` | User or agent asks for content | Run the content factory (W3) | M3 |
| `content.rendered` | Assets produced | Run guards, then approve or queue for approval | M3 |
| `content.approved` | Human or autopilot approves | Schedule it | M4 |
| `content.rejected` | Human rejects | Record the reason as learning signal; optionally regenerate | M4 |
| `content.publish_due` | Scheduled time reached | Publish to each target channel | M4 |
| `content.published` | Publication succeeded | Schedule metric fetches at +1h, +24h, +7d | M4 |
| `content.publish_failed` | Connector error after retries | Notify, mark degraded, keep the item scheduled | M4 |
| `publication.metrics_ready` | Metric fetch completed | Store, compare to baseline, feed learning | M6 |

### Conversations

| Event | Emitted when | Handler does | M |
|---|---|---|---|
| `comment.received` | Meta webhook | Classify → reply, escalate, or ignore (W5) | M4 |
| `message.received` | DM / WhatsApp / site chat | Sales conversation turn (W6) | M4 |
| `message.send_requested` | Agent produced a reply | Guards → send or queue for approval | M4 |
| `conversation.escalated` | Escalation trigger | Assign a human, pause the AI, notify | M5 |
| `conversation.idle_24h` | Sweep | Decide follow-up or close | M5 |

### CRM

| Event | Emitted when | Handler does | M |
|---|---|---|---|
| `lead.created` | Buying intent detected | Score, assign, notify sales | M5 |
| `lead.scored` | Scoring complete | Reorder the sales queue | M5 |
| `lead.no_response_48h` | Sweep | Follow-up Agent (W7) | M5 |
| `lead.stage_changed` | Stage moves | Log activity, recompute attribution | M5 |
| `deal.won` | Deal recorded | Attribute revenue back to content and campaign | M6 |

### Ads — Phase 2

| Event | Emitted when | Handler does | M |
|---|---|---|---|
| `campaign.metrics_ready` | Daily sync | Store, evaluate against targets | M7 |
| `campaign.underperforming` | CPL above threshold for 2 days | Ads Agent proposes action | M7 |
| `creative.fatigued` | Frequency up, CTR decaying | Request new creative from the content factory | M7 |
| `budget.change_requested` | Ads Agent decision | Budget guard → execute or request approval | M7 |

### System

| Event | Emitted when | Handler does | M |
|---|---|---|---|
| `channel.connected` | OAuth completed | Backfill recent posts, health check | M4 |
| `channel.disconnected` | Token invalid | Notify owner, degrade that connector | M4 |
| `approval.decided` | Human decides | Resume or cancel the dependent DAG branch | M3 |
| `run.completed` | All tasks terminal | Write summary and cost | M3 |
| `tenant.budget_warning` | 80% of monthly AI budget | Notify, pause non-critical agents at 100% | M6 |
| `daily.brief` | 07:00 tenant local | Compose and deliver the morning brief (W10) | M6 |

### Cron

| Schedule | Emits |
|---|---|
| Every minute | `content.publish_due` sweep |
| Every 15 min | Stuck-event reaper; channel health |
| Hourly | Metric fetches due |
| 02:00 | Inventory aging, `vehicle.stale`, retention purge |
| 07:00 tenant-local | `daily.brief` |
| 09:00 | `lead.no_response_48h` sweep |
| Weekly Mon 06:00 | Learning Agent, Content Strategist next-week plan |

---

## 2. W1 — Onboarding

Target: **first published post within 48 hours of signup.**

```
Sign up → create tenant, membership, empty brand profile
   ↓
Connect channels (Meta OAuth → IG + FB; WhatsApp; TikTok)      [user, ~5 min]
   ↓
Upload: logo, brand guide PDF, 10 past posts, inventory CSV     [user, ~15 min]
   ↓
BRAND INGESTION  (agent run, ~3 min)
   ├─ Vision: extract palette + typography from logo and past posts
   ├─ Documents: chunk + embed the brand guide
   ├─ Copy analysis: infer tone, CTA style, hashtag pattern, languages
   ├─ Backfill: pull last 30 published posts and their metrics
   └─ Draft brand_profiles → PRESENT FOR CONFIRMATION
   ↓
Human confirms or edits the brand profile                       [required — never skip]
   ↓
INVENTORY IMPORT
   ├─ Map CSV columns (LLM-assisted, human confirms the mapping)
   ├─ Create vehicles, emit vehicle.created per row
   └─ Photo QA + angle labelling per vehicle
   ↓
FIRST CONTENT: 3 posts for the 3 oldest vehicles → approval queue
   ↓
Owner approves → published → onboarding complete
```

**The brand confirmation step is mandatory in every autonomy mode.** An inferred brand
that is 80% right produces content that is subtly wrong forever, and nobody can point at
why. Thirty seconds of human confirmation removes that whole class of failure.

---

## 3. W2 — Vehicle ingestion

```
vehicle.created / vehicle.media_uploaded
   ↓
NORMALIZE       make/model/trim to canonical names; units to metric
   ↓
ENRICH          fill missing specs from the tenant's spec-sheet documents.
                Never from model knowledge. Unfilled stays null and is
                surfaced as "incomplete" in the UI.
   ↓
PHOTO QA        vision pass per image:
                  reject: blurry, dark, cluttered, another dealer's plate/branding
                  label:  angle (12 classes)
                  score:  composition 0..1
   ↓
RANK            best photo per angle; hero = best front_three_quarter
   ↓
USP EXTRACTION  3–5 selling points grounded in the record's own fields
   ↓
vehicle.ready → Content Strategist proposes a plan
```

**Nothing is invented.** If the record has no horsepower figure and no document supplies
it, the vehicle has no horsepower figure and no agent may state one.

---

## 4. W3 — Content factory

One vehicle with good photos yields 8–12 pieces.

```
content.requested {vehicle_ids, objective, count, locales}
   ↓
[Content Strategist]  → briefs: concept, platform, format, angle, locale, slot
   ↓
   ├──────────────────────────┬──────────────────────────┐
   ▼ (parallel per brief)     ▼                          ▼
[Creative Director]      [Copywriter]              [Copywriter]
 photo + template + variant   locale=ar                locale=en
   └──────────────┬───────────┴──────────────────────────┘
                  ▼
           [Image Agent] — compositor renders 1:1, 4:5, 9:16, 16:9
                  ▼
              GUARDS: inventory · price · brand
                  ├─ fail → regenerate once → still fail → human queue
                  ▼
           content.rendered → approval (per autonomy mode)
                  ▼
           content.approved → schedule
```

Typical yield from one vehicle:

| Concept | Format | Ratios |
|---|---|---|
| Hero | Post | 4:5, 1:1 |
| Specs | Carousel, 4 cards | 4:5 |
| Feature (interior) | Post | 4:5 |
| Offer / price | Post + Story | 4:5, 9:16 |
| Comparison vs. one rival | Carousel | 4:5 |
| Educational (engine, tech) | Post | 1:1 |
| Walkaround | Reel | 9:16 |
| Story teaser | Story | 9:16 |

**Failure handling.** A brief that fails guards twice is dropped from the batch, not
retried forever — the run reports "9 of 12 produced, 3 need attention" with the reasons.
Partial success is a normal outcome.

---

## 5. W4 — Publishing

```
content.publish_due  (or content.approved in autopilot)
   ↓
PRE-FLIGHT
   ├─ vehicle still available?     no → cancel, notify
   ├─ price unchanged?             no → cancel, regenerate
   ├─ channel connected?           no → reschedule +1h, notify
   └─ platform rate limit ok?      no → reschedule to the next slot
   ↓
For each target channel (parallel, independent):
   connector.publish(assets, caption, first_comment)
   ├─ success → publications row with external_id + permalink
   └─ failure → retry ×3 backoff → publication.status='failed', item stays scheduled
   ↓
content.published
   ↓
schedule metric fetches: +1h, +24h, +7d, +30d
```

**Each channel is an independent publication row.** Instagram succeeding and Facebook
failing is a normal, representable state — not a failed content item.

Platform specifics the connector absorbs: Instagram's container-then-publish two-step,
carousels as N containers, the ~50 posts/24h account limit, Reels requiring a hosted URL
rather than a byte upload, and stories not supporting all caption features.

---

## 6. W5 — Comment to lead

```
comment.received (Meta webhook, signature verified)
   ↓
persist raw → resolve channel → resolve/create contact → return 200   [<1s]
   ↓
[Intent Classifier]  gemini-2.5-flash-lite, thinking off
   → {intent, language, urgency, is_spam}
   ↓
   ├─ spam / bot        → hide or ignore, no reply
   ├─ compliment        → brand-voice acknowledgement (autopilot-safe)
   ├─ complaint         → ESCALATE, holding reply, notify owner
   ├─ question ─────────┐
   └─ buying signal ────┤
                        ▼
              [Community Manager]
                ├─ tool: get_vehicle → real price, real availability
                ├─ tool: search_knowledge → policy chunks
                └─ draft public reply + a DM invitation
                        ▼
                 GUARDS: price · inventory · brand · PII
                        ▼
                 autonomy gate → send or queue
                        ▼
              public reply + DM ("sent you the details")
                        ▼
              buying signal → contact upsert → lead.created
```

**Price questions in public comments** get the real number from `vehicles.price_minor`
plus the tenant's disclaimer, or they get "sent you the details in DM" — never an
approximation, and never a number the model produced.

---

## 7. W6 — Sales conversation

```
message.received  (WhatsApp / IG DM / site chat)
   ↓
resolve contact (external_refs) → conversation → append message → return 200
   ↓
if conversation.ai_paused → notify assigned human, stop
   ↓
[Intent Classifier] → intent, language, urgency
   ↓
CONTEXT ASSEMBLY (04 § 4)
   customer 360 · last 20 messages · matching inventory · policy chunks · playbook
   ↓
[Sales Agent]  gemini-2.5-flash
   tools: search_inventory, get_vehicle, get_customer_360, search_knowledge,
          create_lead, log_activity, escalate_to_human
   ↓
   ├─ can answer      → draft reply in the customer's language
   ├─ needs a human   → escalate + holding message
   └─ buying signal   → create/update lead, propose next step
   ↓
GUARDS: price · inventory · brand · PII · discount floor
   ↓
WHATSAPP WINDOW CHECK
   inside 24h  → free-form send
   outside     → approved template only, or hold until the customer writes
   ↓
autonomy gate → send or queue for approval
   ↓
update conversation timestamps + wa_window_expires_at
   ↓
[Lead Intelligence] rescore asynchronously
```

Conversation-level rules, all enforced in code:

- Identify as an assistant on the first message and offer a human.
- Hand over after `escalate_after_turns` (default 12) without a resolution.
- Never negotiate below `vehicles.min_price_minor`; the agent is told a limit, never the
  floor.
- Never promise a delivery date, a finance approval, or a trade-in value — always escalate.
- Respect quiet hours for outbound; inbound is always answered.

---

## 8. W7 — Follow-up

The hard part is not writing the message, it is deciding **not** to send one.

```
lead.no_response_48h  (09:00 sweep)
   ↓
ELIGIBILITY (code, before any model call)
   ├─ consent to be contacted?              no → drop
   ├─ under max follow-ups (default 3)?     no → mark cold, drop
   ├─ vehicle still available?              no → switch to alternatives or drop
   ├─ quiet hours / tenant timezone ok?     no → defer
   └─ WhatsApp 24h window state?            outside → template only
   ↓
[Follow-up Agent]
   picks a reason to write, not a reminder to exist:
     · price drop on the vehicle they viewed
     · a similar vehicle arrived
     · answer to something left open in the thread
     · an offer that genuinely expires
   ↓
   no genuine reason → DO NOT SEND. Mark cold, schedule a 30-day check.
   ↓
GUARDS → autonomy gate → send
   ↓
schedule the next check with increasing spacing: 2d → 5d → 14d → stop
```

"Just checking in" is prohibited in the agent's rules and is a rejection criterion in the
LLM-judge eval. A follow-up without new information is how a dealer's number gets blocked.

---

## 9. W8 — Ads optimization (Phase 2)

```
Daily 08:00 → sync yesterday's metrics into ad_metrics_daily
   ↓
JOIN OUR FUNNEL: platform "leads" is replaced with our own
   leads.source_content_item_id → ad_entities → real qualified leads and deals
   ↓
[Ads Manager]  gemini-2.5-pro
   per campaign, evaluates: CPL vs target, frequency, CTR trend, spend pacing
   ↓
   proposes actions:
     · pause an ad with CPL 2× target and n ≥ 30 clicks
     · shift budget from a loser to a winner (bounded)
     · request fresh creative when frequency > 3 and CTR down > 25%
     · raise budget on a winner
   ↓
BUDGET GUARD (pure code, reads tenants.autonomy_rules)
   ├─ within max_budget_increase_pct_24h, max_daily, max_campaign?
   │     ├─ yes + autopilot → execute, write ad_changes
   │     └─ yes + assisted  → approval request
   └─ no → approval request, always, in every mode
   ↓
execute → ad_changes row → next-day verification of the effect
```

**Never a blind budget increase.** Every change is bounded, logged with a reason, and
re-evaluated the following day. A campaign that has spent less than the tenant's minimum
learning budget is never judged at all — killing an ad on 6 clicks is the most common way
automated ad management destroys performance.

---

## 10. W9 — Learning loop (Phase 2)

Weekly, Monday 06:00. Full detail in [04](04-memory-architecture.md) § 6.

```
pull 90 days of content + outcomes
   ↓
group by one attribute at a time (template, angle, length, time, locale, price shown)
   ↓
drop every group with n < min_sample (default 30)
   ↓
compare to tenant baseline → effect size + confidence
   ↓
write memories rows (evidence attached)
   ↓
propose a playbook diff → HUMAN APPROVAL → playbooks v(N+1) active
   ↓
new rules enter every agent's cached prompt prefix
```

Optionally, high-confidence proposals become `experiments` rows instead of rules — an
explicit A/B over the next 30 posts, concluded on data rather than on last quarter's
correlation.

---

## 11. W10 — Daily brief

07:00 tenant-local. This is the product's front door.

```
gather (all SQL, one model call to write it):
   yesterday's agent activity, conversations, leads, appointments
   content published + performance vs baseline
   campaign spend and CPL movement
   inventory aging changes
   competitor and market signals
   pending approvals
   ↓
[Analytics Agent] → plain-language brief + up to 3 ranked recommendations
   ↓
each recommendation carries a prepared agent run, ready to execute
   ↓
deliver: dashboard + WhatsApp/email digest
```

```
Good morning.
Your AI team handled 214 activities yesterday.

  37 customer conversations · 12 qualified leads · 3 appointments booked
  6 comments answered · 2 posts published

  MG7 campaign: 7 leads, cost per lead down 18%
  Competitor Al Manar cut BYD Seal by AED 3,000
  Leopard 7 engagement up 22% week over week

Recommended: increase Leopard 7 content this week.     [ Execute ]  [ Why? ]
```

`Why?` opens the `agent_run` that produced the recommendation, with its evidence and cost.
Every number in the brief is clickable down to its source rows.
