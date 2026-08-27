# Memory Architecture

**Status:** Approved · Depends on: [03-database-schema.md](03-database-schema.md)

---

## 1. The rule that governs everything here

> **Most of what looks like "AI memory" is a SQL join. Use the join.**

Vector search is for **unstructured text where you do not know the right query key**:
policy documents, past conversations, learned observations. It is the wrong tool for
anything with an ID.

| Question | Wrong | Right |
|---|---|---|
| "What MG6s do we have under 70k?" | Embed the question, search vehicle descriptions | `SELECT ... WHERE make='MG' AND price_minor < 7000000 AND status='available'` |
| "What did this customer say before?" | Semantic search over all messages | `SELECT ... WHERE conversation_id = $1 ORDER BY created_at` |
| "What is our brand's primary colour?" | RAG over the brand guide PDF | `brand_profiles.colors->>'primary'` |
| "Do we ship to Algeria and what documents are needed?" | SQL | **Retrieval** over the export policy document |
| "What creative styles work for this brand?" | Guess | `playbooks` (rules) + `memories` (evidence) |
| "Has a customer asked something like this before?" | SQL | **Retrieval** over past resolved conversations |

A system that embeds its inventory returns "a car kind of like an MG6" to a customer
asking a price. That is the failure mode this rule exists to prevent.

---

## 2. The eight brains, mapped to real storage

The conceptual model from the product vision, resolved to actual tables:

| Brain | Holds | Storage | Access |
|---|---|---|---|
| **Brand** | Identity, tone, rules, templates, forbidden terms | `brand_profiles`, `brand_assets`, `creative_templates` | Direct read, loaded into the cached prompt prefix |
| **Product / Vehicle** | Inventory, specs, media, price history | `vehicles`, `vehicle_media`, `vehicle_price_history` | SQL via `inventory` tools |
| **Customer** | Identity, history, preferences, consent | `contacts`, `conversations`, `messages`, `leads`, `activities` | SQL join = Customer 360 |
| **Content** | What was made, published, and how it performed | `content_items`, `publications`, `content_metrics` | SQL + `similar_content` retrieval |
| **Sales** | Objections, negotiations, wins, losses | `messages`, `deals`, `activities` | SQL + retrieval over resolved threads |
| **Ads** | Campaigns, spend, creative fatigue | `ad_entities`, `ad_metrics_daily`, `ad_changes` | SQL |
| **Market** | Demand, prices, competitors, trends | `market_signals`, `competitor_observations` | SQL + retrieval |
| **Learning** | What worked, and the rules derived from it | `memories`, `playbooks` | Retrieval + direct read |

**Knowledge documents** — export policy, finance terms, warranty, FAQ, spec sheets — are
the only source that is *primarily* retrieval: `documents` → `doc_chunks`.

---

## 3. Embeddings

**Requirement: the embedding model must be genuinely multilingual.** Arabic, English, and
French content must land near each other in vector space, because a customer asks
"بتصدروا للجزائر؟" about a policy written in English.

| Property | Choice |
|---|---|
| Dimension | **1024** — fixed in the schema |
| Candidates | Cohere `embed-multilingual-v3.0` (1024), Voyage multilingual, OpenAI `text-embedding-3-large` truncated to 1024 |
| Index | pgvector HNSW, cosine |
| Where | `doc_chunks.embedding`, `memories.embedding` |

Changing the dimension is a migration plus a full re-embed, so it is decided once. Embed
the **query in the customer's language and the chunk in its own language** — a good
multilingual model handles the cross-lingual match; do not machine-translate before
embedding, which loses the original phrasing.

### Chunking

| Source | Strategy |
|---|---|
| Policy / FAQ documents | Semantic split on headings, 400–800 tokens, 15% overlap, heading path prepended to each chunk |
| Spec sheets | One chunk per section — never split a spec table across chunks |
| Conversations | One chunk per resolved thread, with a one-line summary header |
| Memories | Never chunked. One statement, one row. |

Every chunk stores `tenant_id`, `document_id`, `locale`, and `meta` (heading path, source
page). **Filters run before the vector search, not after:**

```sql
select content, 1 - (embedding <=> $1) as score
from doc_chunks
where tenant_id = $2 and locale = any($3)          -- pre-filter
order by embedding <=> $1
limit 8;
```

RLS makes the `tenant_id` predicate redundant — it is written anyway, because a query that
is correct without RLS is a query that survives a policy mistake.

### Retrieval quality

Hybrid, not pure vector: run the HNSW search and a Postgres full-text search over the
same chunks, merge with reciprocal rank fusion, take the top 8. Exact-match terms
(a trim name, a VIN, "Algeria") are exactly what dense retrieval loses, and they are
exactly what a car customer types.

> `ponytail:` RRF over two Postgres queries, no reranker model. Ceiling is recall on
> paraphrase-heavy queries. **Upgrade trigger:** golden-set retrieval recall below 85%.
> Then add a cross-encoder rerank over the top 30. Not before.

---

## 4. What each agent gets

Context assembly is explicit per agent. No agent gets "everything relevant."

| Agent | Context |
|---|---|
| Sales Agent | Brand tone + Customer 360 (SQL) + last 20 messages (SQL) + matching inventory (SQL) + top 5 policy chunks (retrieval) + playbook sales rules |
| Copywriter | Brand voice + vehicle record (SQL) + top 3 performing captions for this make/model (SQL on metrics) + playbook copy rules |
| Creative Director | Brand visuals + ranked photos with vision labels (SQL) + template list + playbook creative rules |
| Content Strategist | Inventory with stock age (SQL) + last 30 days of content and performance (SQL) + market signals (SQL) + calendar gaps |
| Community Manager | The comment + its parent post + vehicle + last 3 exchanges with this contact + FAQ chunks |
| Growth Director | Aggregates only: inventory summary, funnel, spend, playbook. **Never raw rows.** |

The Director working from aggregates is deliberate: handing a planner 200 vehicle rows
produces a plan about row 4.

---

## 5. Customer 360 is a query, not a document

```sql
select
  c.*,
  (select count(*) from conversations v where v.contact_id = c.id)          as conversation_count,
  (select jsonb_agg(x) from (
      select m.body, m.direction, m.created_at from messages m
      join conversations v on v.id = m.conversation_id
      where v.contact_id = c.id order by m.created_at desc limit 20) x)     as recent_messages,
  (select jsonb_agg(distinct l.vehicle_id) from leads l where l.contact_id = c.id) as vehicles_of_interest,
  (select max(l.score) from leads l where l.contact_id = c.id)              as best_score
from contacts c where c.id = $1;
```

Because it is a query, it is always current. A "customer memory document" that a nightly
job regenerates is stale the moment the customer sends a message — which is precisely when
it is needed.

When the customer returns after a month and asks *"العربية البيضاء لسه موجودة؟"*, the
resolution is: `external_refs` → contact → last `subject_vehicle_id` → vehicle → colour
match → current `status`. All SQL. No embedding involved, and no chance of confusing two
white cars.

---

## 6. The learning loop

This is the compounding asset. It has to be conservative or it compounds noise.

### What is recorded

Every published content item accumulates a row of outcome data:

```
hook · concept · template · aspect ratio · vehicle · locale · caption length ·
price shown? · CTA type · posting time · platform
   ↓
impressions · reach · engagement · saves · shares
   ↓
profile visits · link clicks · DMs started · comments classified as intent
   ↓
leads · qualified leads · appointments · deals · revenue
```

That chain is why `content_items` links to `publications` links to `content_metrics`, and
why `leads.source_content_item_id` exists. **Attribution has to be designed into the
schema before the first post, or it can never be recovered.**

### Weekly, the Learning Agent

1. Pulls content plus outcomes for the last 90 days
2. Groups by one attribute at a time (template, angle, caption length, time, locale)
3. Compares against the tenant's baseline
4. **Discards any group below `min_sample`** — default 30 published items
5. Produces `memories` rows with evidence and sample size:

```json
{
  "scope": "content",
  "statement": "Front three-quarter compositions on a dark background produce 27% more DM starts than lifestyle backgrounds for this brand.",
  "evidence": {"variant_a": {"n": 41, "dm_rate": 0.084},
               "variant_b": {"n": 38, "dm_rate": 0.066},
               "window": "2026-04-01..2026-06-30"},
  "confidence": 0.72,
  "sample_size": 79
}
```

6. Proposes a **playbook diff** — never writes one:

```diff
  Playbook v7 → v8 (proposed)
+ creative.default_composition: "front_three_quarter_dark" for Chinese SUVs
~ copy.arabic_max_words: 120 → 80
+ publishing.preferred_slots: ["20:00","21:30"] (was ["12:00","18:00"])
```

7. A human accepts or rejects. Accepted rules become `playbooks` version N+1 with
   `status='active'`, and enter every agent's cached prompt prefix.

### Why a human gates the playbook

An agent that silently rewrites its own operating rules from correlational data will,
within a quarter, have taught itself something confidently wrong that nobody can trace.
The playbook is small, human-readable, versioned, and diffable *specifically* so a dealer
can read it and say "no, that's a coincidence." That review is cheap, monthly, and it is
what makes the automation trustworthy.

Rollback is setting version N back to `active`. `playbooks_one_active` enforces exactly
one active version per tenant.

### Memory hygiene

- **Supersede, never mutate.** A refuted memory gets `superseded_by` pointing at its
  replacement. History stays intact.
- **Decay.** Confidence is multiplied by 0.9 per month without corroboration. Below 0.3,
  the memory drops out of retrieval.
- **Deduplicate on write.** Cosine similarity above 0.92 against an existing memory in the
  same scope updates that row's evidence and sample size instead of adding a near-copy.
- **Scope isolation.** A memory belongs to exactly one tenant. There is no shared or
  cross-tenant learning pool in v1 — the isolation guarantee is worth more than the
  aggregate insight.

---

## 7. Short-term working memory

An agent run's intermediate state lives in `agent_tasks.output` and is read by dependent
tasks through `from_task`. That is the whole mechanism.

No Redis, no scratchpad store, no conversation-buffer abstraction: a run is minutes long,
its state is small, and keeping it in Postgres means a crashed worker resumes exactly
where it stopped.

> `ponytail:` Task output in Postgres as working memory. Ceiling is roughly a few hundred
> KB per task and one round trip per read. **Upgrade trigger:** task outputs above ~1 MB
> or a run fanning out beyond ~50 tasks. Then spill large payloads to object storage and
> keep a pointer in `output`.

---

## 8. Cost control

Retrieval is cheap; putting the results in the prompt is not. Rules:

- Retrieve top 8, include top 4 after fusion. More context measurably lowers answer
  quality on short factual questions.
- Brand Brain and playbook are summarized to under ~800 tokens and sit **above** the cache
  breakpoint, so they are billed at cache-read rates after the first call of the day.
- Never embed at request time what can be embedded once at write time.
- Bulk re-embedding (a new template of the catalogue, a model change) goes through the
  Batch API at 50% cost.
- `agent_traces` records `cache_read_tokens` on every call. A tenant whose cache hit rate
  drops below 60% gets flagged — it means someone put a timestamp above the breakpoint.
