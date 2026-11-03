# DealerAI OS — The vehicle lifecycle

> **From the day a car is bought to the day it is sold, one platform, and the AI does the work.**
> A person signs where money or the law is involved. Everything else is the AI's job.

---

## What this is

The founder's direction, 2026-11-03: DealerAI OS becomes the whole operating system of a
showroom — not marketing plus a sales inbox, but every step a car goes through between the
dealer buying it and a customer driving it away.

Marketing (docs `00–09`) and Sales (`docs/sales/`) are built. Both start once a car is already
on the forecourt with a price on it. Everything *before* that — where the car came from, what it
cost, what was spent making it saleable, how the price was decided — does not exist in the
product today. Nor does most of what happens *after* a customer says yes. This document plans
both ends.

---

## The lifecycle

Twelve stages. "Today" is what exists in the codebase now.

| # | Stage | What happens | What the AI does | What a person signs | Today |
|---|---|---|---|---|---|
| 1 | **Sourcing** | Find cars worth buying: auctions, trade-ins, dealers, imports | Turns unmet demand (customers asking for cars that are not in stock — the sales copilot already sees every one) into a buying list; scores opportunities by expected margin and days to sell | Nothing — it is a list | ❌ |
| 2 | **Appraisal** | Decide what a car is worth and the most to pay | Valuation range from the dealer's *own* sales history and the comparables it is given; reads damage from photographs (the vision pipeline exists); proposes a maximum bid for a target margin | The bid | ❌ |
| 3 | **Purchase** | The car is bought | Reads the auction receipt or purchase invoice and proposes the acquisition and its cost lines | Confirms what the document says | **L1** |
| 4 | **Inbound** | Shipping, customs, transport, registration | Tracks each milestone, chases what is late, adds every fee to the car's cost, keeps the document checklist | — | ❌ |
| 5 | **Reconditioning** | Inspect, repair, detail, photograph | Writes the repair plan and estimate from the inspection; flags a car going over its budget; knows when it will be ready | The repair budget | ❌ |
| 6 | **Pricing** | List price and the floor | Recommends both from landed cost, target margin, the dealer's own history and days in stock; proposes re-prices as a car ages | Every price change (it already writes history and warns published content) | ⚠️ manual only |
| 7 | **Merchandising** | Photo QA, specs, selling points | Rejects bad photos, picks the hero, fills specs only from the dealer's documents | — | ✅ M2 |
| 8 | **Marketing** | Content, publishing, ads | Plans and produces a week of bilingual content per car, guarded | Publishing, per autonomy mode | ✅ M3 · publishing M4 |
| 9 | **Selling** | Inbox, CRM, follow-ups | Drafts replies grounded in live stock, scores leads, writes follow-ups | Every message (Phase 1 is copilot-only) | ✅ Sales S0–S7 |
| 10 | **Deal desk** | Offer, trade-in, reservation, finance, insurance | Builds the offer inside the floor, values the trade-in (back to stage 2), prepares the bank and insurer packets | The deal, any discount, the deposit | ❌ |
| 11 | **Handover** | Invoice, sale agreement, transfer or export papers, delivery | Drafts every document from the record and checks it against the record | Every document | ❌ |
| 12 | **After the sale** | Follow-up, review, service reminders, referral, trade-back | Runs the after-sale programme and notices when a past buyer is ready to trade again | — | ⚠️ follow-ups only |

And running across all twelve: **unit economics** — what every car cost, what it made, how long
it took, and what it cost to hold. That is the number a dealer actually runs the business on, and
it is only possible once stage 3 records the cost.

---

## Decisions

### What changes from the earlier documents

| Document | Said | Now | Why |
|---|---|---|---|
| 00 §10 | "We do not do vehicle valuation" | **Pricing guidance and appraisal are in scope.** Valuation for *lending* is still out. | A dealer cannot run purchase-to-sale without knowing what to pay and what to ask. The guidance is grounded in the dealer's own history and supplied comparables — never in a model's memory of what a car is worth |
| 00 §10 | "We do not take payments, deposits, or handle contracts" | **We record** deposits and payments, and **draft** contracts and invoices. We still never take card details and never sign. | A deal desk that cannot record a deposit is not a deal desk. Taking payment details and signing stay `ALWAYS_HUMAN` in `orchestrator/gate.py`, unchanged |
| 00 §1 | A marketing and sales department | **The operating system of a showroom** | The founder's direction above |

### What does not change

- **The AI does the work; a person signs.** "Done by AI" means the AI reads the invoice, proposes
  the price, drafts the contract and chases the late shipment. It does not mean money moves or a
  legal document is signed without a person. `ALWAYS_HUMAN` in the autonomy gate is the line,
  and it does not move.
- **Never invent a fact about a car.** Every figure a stage writes comes from a document the
  dealer supplied, a row in the database, or a person — and the verification is code, not a
  prompt. This now covers money the dealer *spent*, not only money it asks for.
- **One record per car.** Every stage reads and writes the same `vehicles` row and its children.
  No second inventory.

### The buy side is need-to-know

What a dealer paid for a car is the most sensitive number in the business. A salesperson who can
see it negotiates down to it; a customer who learns it never pays the asking price again.

- Acquisition and cost rows are **invisible in Postgres** to any session that is not cleared for
  them — the same rule as tenancy and sales visibility: forgetting a `WHERE` must not cause a
  leak. The API clears a session only for a caller with `costs.view`.
- `costs.view`: owner, admin, manager. `costs.edit`: owner, admin. Sales, marketer and **viewer**
  see neither — viewer is deliberately excluded, because "read-only" is given out more freely than
  "sees what we paid".
- **No customer-facing agent may read the buy side.** A test fails the build if a tool queries
  it, and the price guard would block a cost figure in a reply anyway — two locks, not one.

---

## Slices

Each ends in something a dealer can use. The order is the order every later stage depends on.

| # | Slice | Scope | Exit criterion |
|---|---|---|---|
| **L1** | **Purchase and unit economics** | Acquisition record, cost ledger in any currency, landed cost, margin at list and at floor, the buy side in Postgres, an AI that reads a purchase invoice into cost lines for a person to confirm, the inventory screens | A car bought at auction, with five cost lines entered **from a photograph of the invoice in one confirmation**, shows its landed cost and its margin at list and at floor — and a salesperson's session cannot read any of it, even with SQL |
| **L2** | Pricing intelligence | Recommended list price and floor; aging re-price proposals through approvals; the floor written from cost and target margin | A car 60 days in stock gets a re-price proposal a manager approves in one click, and the published content that quoted the old price is flagged |
| **L3** | Reconditioning | Inspection, work orders, repair estimates from inspection photos, budget alerts, ready-to-sell date | A repair over budget raises an approval before the money is spent |
| **L4** | Inbound | Shipments, customs, transport, registration milestones; document checklist; fees flow into the ledger | A US-auction car shows where it is and what is missing, and its landed cost is complete the day it arrives |
| **L5** | Appraisal and sourcing | Valuation from own history, trade-in appraisal with damage read from photos, maximum bid, a buying list from unmet demand | The buying list names cars customers asked for this month that the dealer does not have |
| **L6** | Deal desk | Offers inside the floor, trade-in on the sale, reservations and deposits recorded, finance and insurance packets | An offer below the floor cannot be sent; a deposit reserves the car and stops its marketing |
| **L7** | Handover | Invoice, sale agreement, RTA transfer or export papers, delivery checklist — drafted and checked against the record | Every document for one sale is drafted from the record and a person signs it |
| **L8** | After the sale, and the numbers | After-sale programme, service reminders, trade-back signals; per-car P&L, gross per unit, turn, holding cost in the dashboard and the morning brief | The owner's morning brief says what the month made and which cars are costing money to keep |

**L1 first** because every later slice reads cost: pricing needs a floor that comes from it, the
deal desk needs a margin, the numbers need both. **L2 next** because it is the fastest way to sell
a car sooner, and the AI pipeline it needs already exists.

---

## L1 — Purchase and unit economics

### Data

`supabase/migrations/0016_lifecycle_acquisition.sql`.

- **`vehicle_acquisitions`** — one per vehicle: `source` (auction, trade-in, private, dealer,
  import, other), `seller`, `reference` (lot or invoice number), `purchased_at`, `notes`.
- **`vehicle_costs`** — the ledger. One row per cost: `category` (purchase, auction fee, transport,
  shipping, customs, registration, inspection, repair, parts, detailing, photography, storage,
  commission, other), `description`, `vendor`, `amount_minor` and `currency` **as the document
  says**, `fx_rate` and `amount_tenant_minor` in the dealer's own currency, `incurred_at`,
  `status` (estimate or actual), `source` (manual or document), and the stored invoice it was
  read from — kept on the line, **not** in `documents`, which is tenant-wide and feeds the
  copilot's knowledge base.
- **`v_vehicle_economics`** — landed cost (actual and estimated), list price, floor, margin at
  each, days in stock. `security_invoker`, so the buy-side rule applies to it.

**The purchase price is a cost line** (`category = 'purchase'`), not a column. One ledger means
one sum, and nobody has to remember that the price lives somewhere else.

**Exchange rates are facts.** A cost in the dealer's currency has a rate of 1. A cost in any other
currency must come with its rate — from the person, or printed on the document and verified there.
The model never supplies one from memory.

### The AI: reading the invoice

`POST /v1/vehicles/{id}/costs/extract` takes a photograph or PDF of an auction receipt, shipping
invoice, customs receipt or workshop bill and returns **proposed** cost lines. It writes nothing.
`POST /v1/vehicles/{id}/costs` writes the lines a person confirmed. Same rule as the CSV import:
there is no code path from a model's reading to a stored cost that does not pass through
something a person posted back.

Two mechanical checks run before a proposal is shown:

1. **Every line is quoted.** The model returns the text of the line it read each amount from;
   code checks the amount appears in its own quote.
2. **The lines add up.** If the document states a total, the proposed lines must sum to it, or
   the proposal says so in red. A reading that drops a line or doubles one is the common failure,
   and arithmetic catches it without trusting anything.

### Screens

- **Inventory** — every car, with age, status and price; cost and margin columns for those cleared
  to see them.
- **Vehicle** — overview, and for those cleared: the acquisition, the cost ledger, landed cost and
  margin, and *Add from a document*: upload, read, check, confirm.

---

## Open questions for Pollux

| # | Question | Changes |
|---|---|---|
| Q1 | Which sources do you buy from most — US auctions (Copart, IAA), Emirates Auction, trade-ins, Korean or Japanese exporters? | L4's milestones and L5's sources |
| Q2 | Should a manager see cost, or only the owner? | `costs.view` for the manager role |
| Q3 | Do you finance through partner banks, and which? | L6's finance packet |
| Q4 | For export, which documents does each destination need (export certificate, certificate of origin, bill of lading)? | L7's document set |
