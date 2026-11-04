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
- `recon.edit`: owner, admin, manager — a manager runs the workshop. The **budget** a repair is
  measured against is `costs.edit`: whoever commits the work cannot be whoever moves the line.
- **Where a car is, is not the buy side.** Its journey and ETA are readable by every member — a
  salesperson promising a customer a date needs them. Its papers (a bill of sale is the price,
  printed) and what its landed cost is missing are. `inbound.edit`: owner, admin, manager.
- **No customer-facing agent may read the buy side.** A test fails the build if a tool queries
  it, and the price guard would block a cost figure in a reply anyway — two locks, not one.

---

## Slices

Each ends in something a dealer can use. The order is the order every later stage depends on.

| # | Slice | Scope | Exit criterion |
|---|---|---|---|
| **L1** ✅ | **Purchase and unit economics** | Acquisition record, cost ledger in any currency, landed cost, margin at list and at floor, the buy side in Postgres, an AI that reads a purchase invoice into cost lines for a person to confirm, the inventory screens | A car bought at auction, with five cost lines entered **from a photograph of the invoice in one confirmation**, shows its landed cost and its margin at list and at floor — and a salesperson's session cannot read any of it, even with SQL |
| **L2** ✅ | **Pricing intelligence** | Recommended list price and floor; aging re-price proposals through approvals; the floor written from cost and target margin | A car 60 days in stock gets a re-price proposal an owner or admin approves in one click, and the published content that quoted the old price is flagged |
| **L3** ✅ | **Reconditioning** | Inspection, work orders, repair estimates from inspection photos, budget alerts, ready-to-sell date | A repair over budget raises an approval before the money is spent |
| **L4** ✅ | **Inbound** | Shipments, customs, transport, registration milestones; document checklist; fees flow into the ledger | A US-auction car shows where it is and what is missing, and its landed cost is complete the day it arrives |
| **L5** | Appraisal and sourcing | Valuation from own history, trade-in appraisal with damage read from photos, maximum bid, a buying list from unmet demand | The buying list names cars customers asked for this month that the dealer does not have |
| **L6** | Deal desk | Offers inside the floor, reservations by deposit, payment in stages (deposit, balance on inspection and documents, logistics as it ships), an invoice that separates price, fees, freight and duties, transfer receipts read into payments; no bank finance (Q3) | An offer below the floor cannot be sent; a deposit reserves the car and stops its marketing |
| **L7** | Handover and export | The export file per destination — Pollux's own procedures for Algeria, Tunisia and everywhere else ([pollux.md](pollux.md)): RTA export inspection and certificate, export plates, customs card, bill of lading draft then original, Dubai Chamber certificate, commercial invoice — as an outbound journey on L4's machinery; RTA transfer and delivery checklist for a local sale | Every document for one sale is drafted from the record and a person signs it, and an export car shows which step of its destination's procedure it is on |
| **L8** | After the sale, and the numbers | After-sale programme, service reminders, trade-back signals; per-car P&L, gross per unit, turn, holding cost in the dashboard and the morning brief | The owner's morning brief says what the month made and which cars are costing money to keep |

**L1 first** because every later slice reads cost: pricing needs a floor that comes from it, the
deal desk needs a margin, the numbers need both. **L2 next** because it is the fastest way to sell
a car sooner, and the AI pipeline it needs already exists.

**After L4: L6 and L7 before L5.** Pollux sells new cars and exports most of them
([pollux.md](pollux.md)): a deposit, staged payments and a ten-step export file are every sale,
while a trade-in appraisal is the occasional one. L5 keeps its place in the plan, after them.

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

## L2 — Pricing intelligence

### Data

`supabase/migrations/0017_lifecycle_pricing.sql`: `tenants.pricing_settings` (the dealer's rules,
validated by `PricingSettings`), two notification kinds (`price_proposed`, `content_stale`) and an
index that makes "one pending proposal per car" cheap to check.

### The rules — code, not a model

`lifecycle/pricing.py`. A price is arithmetic on facts the dealer can check; a model adds nothing
there but a way to be wrong. Every number is integer minor units, rounded **up** to the dealer's
rounding unit so a rounded price never keeps less margin than the rule.

- **Target** — the price that keeps the target margin on landed cost (default 12%).
- **Floor** — the same at the floor margin (default 5%). Proposed when the car has none or its
  floor keeps less; a higher floor the dealer set is never lowered.
- **The aging ladder** — after 45, 60 and 90 days in stock the target is cut by 3%, 3% and 5%. Only
  age moves a price down: a new car above target holds, and the screen says there is room to
  negotiate.
- **Demand holds** — a car with three or more leads in 30 days keeps its price.
- **Below the floor, no cost, another currency, not for sale** — said, never proposed.

### The loop

1. **07:00 tenant time**, before the brief, `pricing.sweep_due` prices every car in stock and puts
   each one that should move into the approval queue — one pending proposal per car, carrying the
   before, the after, the floor and the reasons. One notification per morning, to owners and admins.
2. **An owner or admin approves** (`APPROVER_ROLE["price_change"] = "admin"`). The worker applies it
   in one transaction — only if the price is still the one the proposal started from; a price that
   moved in between leaves the proposal stale, never overwritten.
3. **Every price change** — approved, or typed on the vehicle screen — writes price history and
   emits `vehicle.price_changed`. Unpublished content that quotes the old price is rejected (the
   same price guard that checks every draft); published content that quotes it is listed in a
   notification to whoever owns content, because a published post is the dealer's to edit.

### Screens

- **Vehicle → Pricing** — the recommendation, its reasons in words, and *Send for approval*.
- **Settings → Pricing** — target, floor, rounding, the demand hold and the ladder. Changing them
  changes tomorrow's proposals, never a price.

---

## L3 — Reconditioning

### Data

`supabase/migrations/0018_lifecycle_recon.sql`.

- **`vehicle_recon`** — one per car: `budget_minor` in the dealer's currency, `ready_by` (when it
  is expected on the lot), `ready_at` (when it got there), notes. Created with the dealer's default
  budget the first time anybody writes to it.
- **`recon_items`** — the work: `area`, `operation` (paint a panel, dent, tyre, windscreen,
  service, valet, …), `quantity`, `description`, `severity`, `vendor`, `estimate_minor`,
  `actual_minor`, `status`, the inspection photo it was read from, and links to its cost line and
  its approval.
- **`tenants.recon_settings`** — the starting budget per car, and a rate per unit of each
  operation.
- Both tables sit behind the buy-side wall. So does an over-budget approval: it names what the
  repair costs, so a restrictive policy on `approvals` hides that kind from any session not
  cleared for the buy side, and the approvals routes now open their session as the person.

### The rule

An item moves `proposed → approved | awaiting_approval → approved → done`, or is declined.

- **Commit** is the moment money is promised. If the approved estimates plus the work already
  done, plus this item, fit the budget, it is approved at once and its estimate goes into the cost
  ledger as an estimate line — so the landed cost, and tomorrow's price, already count it. If not,
  it waits in the approvals queue for an owner or admin (`APPROVER_ROLE["recon_over_budget"]`).
  **No budget spends like a budget of nothing**: every commitment asks until somebody sets one.
  The car's record is locked while it is measured, so two items committed at once cannot each fit
  a budget they overrun together.
- **Done** turns the estimate line into the actual amount. A repair that came in above its estimate
  and took the car over budget is money already spent — nothing to approve — so owners and admins
  are told (`recon.overran`).
- An approval is applied only to the item exactly as it was asked about: withdrawn, or with a
  different estimate, and the decision is stale. A "no" declines the work.
- **Ready** refuses while work is approved or waiting. A car still in draft goes on sale.

### The AI: reading inspection photos

`POST /v1/vehicles/{id}/recon/inspect` takes up to eight photos and returns **proposed** work. It
writes no item; `POST /recon/items` writes what a person confirmed.

The model says what it sees and what work that calls for, against the photo that shows it. **It
never says what the work costs.** The estimate comes from the dealer's rate card, then from this
dealer's own history — the median per unit of the last jobs of the same operation in a year, once
there are three — and otherwise a person types it. A repair price from a model's memory is a guess
about a workshop it has never been to.

What code checks: the photo a finding names was sent, the quantity is a count, and the same finding
is listed once. What it cannot — whether the damage is there — a person confirms line by line.

### Screens

- **Vehicle → Reconditioning** — budget, committed, spent and left; the work with its next step
  (commit, set an estimate, done, decline, withdraw); *Read inspection photos*; *Mark ready*.
- **Settings → Reconditioning** — the starting budget and the rate card.

---

## L4 — Inbound

### Data

`supabase/migrations/0019_lifecycle_inbound.sql`.

- **`vehicle_inbound`** — one per car: `route` (import or local), carrier, B/L or booking number,
  vessel, container, ports, `eta`, `arrived_at`. Tenant-wide.
- **`inbound_milestones`** — the journey, in order, each pending, done (with the date) or skipped.
  An import: bought, paid, picked up, at the port of loading, shipped, at the port of discharge,
  cleared customs, delivered to the lot, registered. A local car: bought, paid, collected,
  registered. Tenant-wide.
- **`inbound_documents`** — the papers: an import needs the bill of sale, title, bill of lading,
  customs declaration and customs certificate; a local car the bill of sale and registration card.
  Missing, received (with the file) or not needed. **Buy side.**

The templates live in `lifecycle/inbound.py` and are a guess until Pollux answers Q1 and Q4.
Changing a car's route keeps what the two routes share.

### Where it is, what is missing

- **Where it is** — the step after the furthest one reached: a car marked shipped is at sea
  whether or not anybody ticked "paid". **Late** — past its ETA and not on the lot.
- **What is missing** — papers not received, and the landed cost checked against the fees the
  route always has: the purchase, the auction's fees for an auction car, and for every import
  transport, shipping and customs. A fee recorded only as an estimate is listed as an estimate:
  it is not what the car cost.
- **The day it arrives** — reaching the lot records `arrived_at` and emits `inbound.arrived`, once.
  Owners, admins and managers are told what is still missing — or that nothing is. Every morning
  at 07:00 tenant time, the cars past their ETA are named in one notice (`inbound.sweep_due`).
- **Fees flow into the ledger** through the invoice reader from L1: a shipping invoice or a
  customs receipt is read on the cost tab, and the landed-cost check sees it at once.

### The AI: reading a shipping document

`POST /v1/vehicles/{id}/inbound/read` takes a bill of lading, booking confirmation, arrival notice
or customs declaration and returns what it says: carrier, reference, vessel, container, ports, the
sailing date, the ETA, the step it proves and the paper it is. It writes nothing but the file;
`/inbound/confirm` applies what a person accepted, in one transaction.

What the model is not trusted with is **which car the paper is for**. It is not told the VIN. It
lists every VIN it reads, each with the line it read it from, and code keeps a VIN only when it is
17 characters with no I, O or Q and appears in that line — then the paper is this car's only if
this car's VIN is among them. A container of six cars matches the one on it; a bill of lading for
another car cannot be applied. A sailing date in the future is a schedule, not a departure.

### Screens

- **Vehicle → Arrival** — where the car is and its ETA (everybody); details, the journey with a
  date per step, the papers, the landed-cost check and *Read a shipping document* (for those who
  may see and move them).

---

## Status

| Slice | State |
|---|---|
| **L1** | **Done.** Migration `0016`, `routes/acquisition.py`, `lifecycle/invoices.py`, the inventory and vehicle screens. The buy-side wall is tested as the application role; the invoice reader is tested live (`npm run eval:invoice`) — every line of an auction invoice read exactly, no exchange rate invented, and a line removed from the printout caught by the total. |
| **L2** | **Done.** Migration `0017`, `lifecycle/pricing.py`, `events/handlers/lifecycle.py`, the pricing card and settings screen. Tested end to end in the browser: a 60-day car proposed, approved by the owner, applied by the worker. In the suite: a manager may propose but not approve, a price that moved before the decision is never overwritten, stale drafts are rejected. |
| **L3** | **Done.** Migration `0018`, `lifecycle/recon.py`, `routes/recon.py`, the reconditioning tab and settings screen. Tested end to end in the browser: AED 1,500 of paint approved inside a AED 2,000 budget, AED 900 of tyres sent for approval, approved by the owner and applied by the worker, the tyres finished at AED 1,100 and the owner told of the overrun, the car marked ready and put on sale; a photo read by the live model and priced from the rate card. The reader is tested live (`npm run eval:inspection`): nothing invented on a photo with no car, the damage found on the photo that shows it. |
| **L4** | **Done.** Migration `0019`, `lifecycle/inbound.py`, `routes/inbound.py`, the arrival tab. Tested end to end in the browser as a manager: an auction car's journey started from its purchase, a bill of lading read by the live model and applied in one confirmation (shipped on its date, ETA and carrier filled, the paper received), the car delivered, and the owner and manager told it arrived with customs still unrecorded and four papers missing. The reader is tested live (`npm run eval:shipping`): both VINs on a two-car bill of lading read as printed, the right car matched, another car refused. |
| L5–L8 | Not started. L6 (deal desk) is next, then L7 (handover and export) — see the note under Slices. |

## Open questions for Pollux

| # | Question | Changes |
|---|---|---|
| Q1 | ~~Which sources do you buy from most?~~ **Answered (2026-11-04):** new cars, Chinese-spec and GCC-spec ([pollux.md](pollux.md)); Pollux both imports from China itself and buys from traders in DUCAMZ — L4's two routes, import and local. | L4's routes |
| Q2 | ~~Should a manager see cost, or only the owner?~~ **Answered (2026-11-04):** both — `costs.view` stays with the manager. | `costs.view` for the manager role |
| Q3 | ~~Do you finance through partner banks?~~ **Answered (2026-11-04):** no bank finance, for export or local buyers; export buyers pay in stages ([pollux.md](pollux.md)). L6 has no finance packet. | L6's finance packet |
| Q4 | ~~For export, which documents does each destination need?~~ Answered by Pollux's own procedures for Algeria, Tunisia and other countries ([pollux.md](pollux.md)). | L7's document set |
