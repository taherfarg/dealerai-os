# Sales — AI copilot

**Status:** Draft · **Depends on:** DealerAI OS [02](../02-agent-architecture.md) (agent contract, gate),
[04](../04-memory-architecture.md) (memory, retrieval), [01](../01-system-architecture.md) §5 and §8 (gateway, guards) · [03](03-whatsapp.md)

---

## 1. Scope and hard rules

- **Phase 1 is copilot only.** The AI drafts. It never sends a message, marks a deal won or lost,
  reassigns or merges a customer, changes a price, or offers a discount or a final price.
- **A business-scoped assistant.** It works only this dealer's vehicles, policies and customers.
  Off-topic requests get a short redirect draft. This is also what keeps it inside WhatsApp's 2026
  terms, which prohibit general-purpose assistants.
- **Facts come from tools and the database.** A price, availability or specification that no tool
  returned does not exist. Guards enforce this in code after generation.
- **Customer text is untrusted data.** Messages, transcripts and documents are wrapped in
  `<untrusted>` blocks. The drafting agent's tools are read-only, so a customer cannot talk it into
  acting.

---

## 2. Agents

| Agent | Trigger | Gateway task kind | Tools | Produces |
|---|---|---|---|---|
| `intent` | Inside every draft run | `classify_intent` (thinking off) | none | intent, language, dialect hint, urgency, entities (make, model, year, colour, fuel, budget, country), opt-out flag |
| `copilot` | `copilot.draft_requested` | `sales_reply` | `search_inventory`, `get_vehicle`, `search_knowledge`, `get_customer_360` | A `Draft` (§3) |
| `profile` | `conversation.idle`, conversation closed | `analysis` | none — context is given | Profile updates, scoring signals, rolling summary |
| `followup` | Follow-up triggers (§6) | `sales_reply` | `get_vehicle`, `search_inventory` | A reason and a draft, or "no genuine reason" |
| `brief` | 08:00 tenant time | `analysis` | none — facts are given | Headline and ranked items |
| — (not an agent) | Audio message stored | `transcribe` (new task kind) | none | `{text, language}` |

Models are named only in `ai/models.py`, as in DealerAI OS. `transcribe` routes to the same Flash tier.

---

## 3. The draft loop

### Trigger and debounce

`whatsapp.message_received` emits `copilot.draft_requested` with `run_after = now + 20 s` and dedupe
key `draft:{conversation}:{message}`. Customers send bursts; one draft per burst.

The handler checks, in code, before any model call — and does nothing if any fails:

- the conversation is open and the channel is connected;
- drafts are enabled for the tenant;
- this message is still the latest customer message, and nobody replied after it;
- the customer has not opted out;
- the tenant's AI budget is not exhausted.

A newer customer message marks any live draft `superseded` in the transaction that queues the next one.

### Steps

```
1 CLASSIFY   intent agent → intent, language, entities
2 GROUND     SQL, no model:
               customer 360 (profile, country, open leads with their cars)
               last 20 messages including transcripts · last 5 internal notes as "team notes"
               available and reserved cars matching the entities
               knowledge chunks (top 4, hybrid retrieval) when the intent is about export, shipping,
                 financing, documents, specs or trade-in
               24h window state · business hours and local time · Arabic register setting
3 DRAFT      copilot agent · tool loop capped at 4 calls, then the schema pass (DealerAI OS toolloop)
4 GUARDS     price · inventory · commitments · PII · brand · script        (code, §3 Guards)
               fail → regenerate once with the reasons → fail again → status 'blocked' with the reason
5 CONFIDENCE band computed in code                                        (§3 Confidence)
6 PERSIST    ai_suggestions row → live-update trigger → the composer shows it
7 OUTCOME    recorded when the person sends, edits or dismisses           (§3 Outcomes)
```

### Draft schema

```python
class ProposedAction(BaseModel):
    kind: Literal["create_lead", "move_stage", "create_task", "update_profile"]
    params: dict[str, Any]
    label: str                        # shown on the chip, in the UI language

class Draft(BaseModel):
    reply: str | None                 # None when proposing a template
    template_name: str | None
    template_variables: list[str] = []
    language: Literal["ar", "en", "fr"]
    used_vehicle_ids: list[UUID] = []
    used_chunk_ids: list[UUID] = []
    actions: list[ProposedAction] = []
    needs_human: str | None           # e.g. "Customer asked for a final price"
```

The model never states its own confidence. When the window is closed it must pick an approved template
by name and fill its variables; free text is rejected by schema validation.

### Prompt layering

Cache order from DealerAI OS 01 §5, stable prefix first:

1. `_rules.md` and the copilot role
2. Tool declarations, sorted
3. Tenant layer: brand tone, sales playbook, quick facts (showroom address, opening hours, export
   countries, documents list)
4. Retrieved context: customer 360, car rows, knowledge chunks, window state
5. The conversation tail and the instruction

Writing rules in the role prompt, with Arabic and French examples that *are* the specification of
tone and are never paraphrased into English:

- Reply in the customer's language. With `mirror_customer`, match their Arabic register — Gulf for
  Gulf customers, Egyptian for Egyptian customers; French for North African buyers writing French or
  French mixed with Darija in Latin script.
- WhatsApp length: at most three short paragraphs, no markdown, no more than one emoji.
- End with one concrete next step ("Local registration or export?", "Shall I book Saturday 11:00?").
- Never "as an AI", never "just checking in", never a price that is not in the context.

### Guards

| Guard | Rejects | Status |
|---|---|---|
| `price` | Any currency figure not equal to a `vehicles.price_minor` or an approved offer in context | Exists (100% branch coverage) |
| `inventory` | A sold vehicle; a reserved vehicle not described as reserved | Exists |
| `pii` | Another customer's phone, name or identity; internal notes quoted verbatim | Exists, extended |
| `brand` | Forbidden terms, missing disclaimer | Exists |
| `commitments` | Discounts, percentages off, "final price", delivery dates, finance approval, trade-in values — patterns in AR, EN and FR | **New** |
| `script` | A reply in Arabic script to a customer writing in Latin script, or the reverse | **New** |

> `ponytail:` the script guard checks Arabic versus Latin script only. It cannot tell English from
> French. **Upgrade trigger:** "wrong language" becomes a top-three discard reason. Then add a
> language-identification check.

Guards run on the exact text that would be sent, against the database as it is at that moment.

### Confidence

| Band | When (evaluated in order) |
|---|---|
| **low** | intent is complaint, negotiation, financing, trade-in or human request · or `needs_human` is set · or the draft needed a regeneration · or intent confidence below 0.6 |
| **high** | intent confidence at least 0.85 · intent is greeting, price, availability, specs, export/shipping, visit/test drive or documents · every fact-bearing intent has at least one source · guards passed first time |
| **medium** | everything else |

Calibration check, monthly: acceptance must be ordered high > medium > low. If it is not, the
thresholds change and the eval report says why.

### Outcomes

- **sent** — the draft was sent unchanged.
- **edited** — the person changed it first. `edit_ratio = 1 − difflib.SequenceMatcher(draft, final).ratio()`.
  "Lightly edited" means `edit_ratio ≤ 0.2`.
- **discarded** — dismissed, with an optional reason: wrong info, wrong tone, not needed, other.
- **superseded** — a newer message or a human reply made it obsolete.

The acceptance metric in [00](00-prd.md) S5 is `(sent + edited with edit_ratio ≤ 0.2) / (sent + edited + discarded)`.

---

## 4. Customer profile and summary

- **Trigger:** `conversation.idle`, scheduled 15 minutes after each message; the handler runs only if
  no newer message arrived. Also when a conversation is closed. Skipped when fewer than two new
  customer messages arrived since the last run.
- **Input:** the current profile, the last summary, messages since the summary cursor (at most 60),
  open leads.
- **Output:** profile updates `[{field, value, evidence_message_id}]`, scoring signals
  `[{signal, evidence_message_id}]`, and the summary `{text, next_action}`.
- **Applied in code, never trusted:**
  - a field last set by a person is never overwritten — the AI can only propose a change as a chip;
  - `evidence_message_id` must belong to this conversation, otherwise the update is dropped (the same
    grounding check as DealerAI OS enrichment);
  - values are validated per field: ISO-2 countries, `Money` with the tenant currency by default,
    enumerations for purchase type and payment.

---

## 5. Lead scoring

`sales/scoring.py` is a pure function: signals in, score, band and reasons out. Same signals, same score.

| Signal | Source | Default points |
|---|---|---|
| `asked_price` | AI, with evidence | +10 |
| `asked_availability` | AI | +10 |
| `asked_export_or_documents` | AI | +10 |
| `gave_budget_or_timeline_30d` | AI | +10 |
| `requested_visit_or_test_drive` | AI | +15 |
| `negotiating_specific_car` | AI | +15 |
| `shared_id_or_asked_payment_details` | AI | +25 |
| `responsive` — median reply under an hour over the last five exchanges | code | +5 |
| `silent` — each full week without a customer message | code | −10 |

Score = clamp(sum, 0, 100). Bands: **hot** ≥ 70, **warm** 40–69, **cold** < 40. Recomputed on every
profile run and by the nightly decay sweep. Per-tenant weights are stored in `sales_settings` but not
editable in the Phase 1 UI.

**Automatic leads.** When the intent is price, availability, visit or test drive, export or shipping,
negotiation, or documents and payment, and the customer has no open lead for that car (or no open
lead at all when no car is known), code creates one: the Export pipeline when the purchase type is
export, otherwise the default; first open stage; owner = the customer's owner; source `ad` when the
conversation carries a Click-to-WhatsApp referral, else `whatsapp`. An event line records it.

---

## 6. Follow-ups

The hard part is deciding not to write.

| Trigger | Condition |
|---|---|
| `no_reply_48h` | Open lead; our message is the latest in the conversation; 48 hours passed. Hourly sweep |
| `price_drop` | `vehicle.price_changed` to a lower price; open leads on that car, or whose profile lists it |
| `similar_arrival` | `vehicle.created` as available; open leads with no car whose profile interest matches make and model |

**Eligibility, in code, before any model call:**

- not opted out;
- fewer than 3 AI follow-ups on this lead so far;
- the car is still available (for triggers tied to a car);
- inside business hours — otherwise deferred to the next opening;
- the cadence (`follow_up_cadence_days`, default 2 → 5 → 14) allows it;
- the 24h window is open → a text draft; closed → a draft on an approved utility template that fits
  the reason (`price_update`, `vehicle_available`); no suitable template → a task with no draft
  ("Call the customer").

**The agent** returns `{genuine_reason: bool, reason, draft}`. With no genuine reason — nothing new to
say — no task is created and the next check waits for the cadence. After the last step, the silence
signal carries the lead to cold on its own.

**The output** is a task for the lead's owner: `kind=follow_up`, `source=ai`, due now (or at the next
opening), `ai_draft = {reason, text | template}`, plus a notification. "Just checking in" and its
Arabic and French equivalents are rejected by the `commitments` guard phrase list and fail the judge.

---

## 7. Knowledge documents

The DealerAI OS 04 §3 design, pulled forward from T5.2:

- Upload PDF, DOCX or TXT → text extraction in the worker → chunks on headings, 400–800 tokens,
  heading path prepended → embeddings → `ready`.
- Hybrid retrieval: HNSW vector search plus Postgres full-text search, merged with reciprocal rank
  fusion; top 8 retrieved, 4 used. Always pre-filtered by tenant.
- The embedding model must be genuinely multilingual (an Arabic question against an English policy).
  It is chosen at implementation with a 50-question recall check. `doc_chunks.embedding` is empty
  today, so the S4 migration may change its dimension to fit the chosen model at no cost.
- Inventory is never embedded. Prices and stock are SQL only (DealerAI OS 04 §1).

---

## 8. Autonomy

Pollux runs `autonomy_mode = copilot`. In the DealerAI OS gate, `send_message` needs approval in
copilot mode; in the inbox, **the person pressing Send is the approval**, so no `approvals` row is
created for inbox sends. Internal actions — creating a lead or task, AI profile fields, scores — are
allowed in every mode. Phase 2 adds a per-intent after-hours action gated by the acceptance trigger in
[00](00-prd.md) §8.

---

## 9. Evals and quality gates

### The golden set

Built from Pollux's imported history ([03](03-whatsapp.md) §9): 300 customer message bursts,
stratified by language and intent. Each is labelled with its intent, the facts a correct reply must
contain (a car and its price and availability, or a policy chunk) and an acceptable next step; the
salesperson's actual reply is kept as the reference.

**Real customer conversations never enter git.** The labelled set lives in
`apps/api/tests/evals/private/` (gitignored) on the founder's machine and in tenant storage. CI runs
a committed synthetic set of 40 items in the same format.

### Gates before drafts reach salespeople

| Eval | Gate |
|---|---|
| Intent accuracy | ≥ 95% overall, ≥ 90% in each language |
| Wrong price or availability in drafts | **Zero** |
| LLM judge against the salesperson's reply | Mean ≥ 4.0 / 5; no accuracy score below 3 (rubric: accuracy, language and register, next step, brevity, banned phrases) |
| Voice-note transcription | 50 notes rated understandable by a person, ≥ 90% |
| Profile extraction | Field precision ≥ 90% on 50 labelled conversations; evidence must point at the right message |
| Follow-ups | Zero "just checking in"; ≥ 80% rated as having a genuine reason |
| Latency | Draft p95 ≤ 10 s after the debounce |
| Cost | ≤ USD 0.015 per draft at p95 |

Rollout: two salespeople for one week, then the team. After that, acceptance by intent is visible to
admins in Settings → AI assistant, from a `v_suggestion_acceptance` view.

---

## 10. Cost envelope

Estimates, to be replaced by `agent_traces` measurements in the first pilot week:

| Work | Estimate | Pollux volume guess | Monthly |
|---|---|---|---|
| Draft (classify + draft, cached prefix) | USD 0.005–0.01 | 3,000 | 15–30 |
| Profile, signals and summary | USD 0.003 | 2,000 | 6 |
| Voice-note transcription | USD 0.0005 | 1,500 | 1 |
| Follow-ups, brief, embeddings | — | — | < 5 |

Well inside the DealerAI OS per-tenant ceiling of USD 120. At 100% of the monthly budget, drafts and
profile runs pause; ingest, assignment, sending and notifications never do.

---

## 11. Prompt files

`ai/prompts/sales_copilot.md`, `intent.md`, `profile.md`, `followup.md`, `brief.md` and
`transcribe.md`, each layered for cache stability, reviewed in diffs like code.
