# DealerAI OS — Product Requirements

**Version:** 1.0 · **Status:** Approved for build · **Owner:** Founder

---

## 1. One sentence

DealerAI OS is an autonomous AI marketing and sales department for automotive
businesses — it researches the market, produces the creative, publishes it, talks to
every customer, runs the ads, and improves itself from the results.

---

## 2. The problem

A mid-size dealer in the UAE has 40–200 cars in stock and 1–3 people covering marketing,
social, and inbound sales. What actually happens:

| Symptom | Root cause |
|---|---|
| Cars sit 60+ days because nobody produced content for them | Content is manual; effort goes to the 5 cars someone remembers |
| Instagram DMs answered hours later, or never at 11pm | Humans, one timezone, one shift |
| "What's the price?" answered with a wrong or stale number | Inventory lives in a spreadsheet, not in the answering process |
| Ad budget burns on a creative that stopped working 9 days ago | Nobody reads Ads Manager daily |
| The same customer is re-qualified from scratch every visit | No memory beyond one WhatsApp thread |
| Marketing spend cannot be tied to a single sale | Lead → showroom → sale is offline and untracked |

The dealer does not have a *tooling* gap. Buffer, Hootsuite, Canva, and a CRM already
exist and they still have this problem. They have a **headcount and attention gap**.
Tools require an operator. We are selling the operator.

### Why now

- Frontier models are good enough to run a real sales conversation in Arabic and English.
- Meta, WhatsApp, TikTok, and Google all expose the publishing, messaging, and ads
  surface programmatically.
- The dealer's most valuable asset — inventory plus past conversations — is exactly the
  context a model needs, and it is already digital.

---

## 3. Who it's for

**Primary market:** UAE and GCC new/used car dealers and re-exporters, 30–500 units in
stock, AED 20k–200k per month in marketing spend.

| Persona | What they want | What they judge us on |
|---|---|---|
| **Owner / GM** ("Khalid") | Sell aging stock, know what the spend bought | One morning screen: what happened, what it cost, what to do |
| **Marketing lead** ("Sara") | Stop being a poster factory | Does the creative look like *our* brand without her rebuilding it |
| **Sales team** | Warm leads, not tire-kickers | Does the AI hand over a lead that already knows the price and the car |
| **Export desk** | Buyers in Algeria, Iraq, East Africa | Does it answer shipping, documents, and LHD/RHD correctly |

**Not for (v1):** OEM head offices, marketplaces and classifieds, single-car private
sellers, rental fleets.

---

## 4. Positioning

| Category | Examples | Why they lose here |
|---|---|---|
| Social schedulers | Buffer, Hootsuite, Later | No product knowledge, no inventory, no sales, no ads. A calendar with no operator. |
| Design tools | Canva, AdCreative-class tools | Produce an image. Do not know which car, which angle, which market, or whether it sold. |
| Auto CRMs | DealerSocket, local CRMs | Store the lead. Do not create demand or produce creative. |
| Generic AI chat widgets | Intercom-class bots | No inventory truth, no price authority, no follow-up, no cross-channel memory |
| Agencies | Local marketing agencies | AED 8–25k per month, 48h turnaround, zero inventory awareness, no 24/7 response |

**Our wedge:** we are the only system that closes the loop from *a specific VIN in stock*
to *a specific dirham of revenue*, and remembers what worked.

**The moat is the Company Brain.** A competitor can copy the feature list in a quarter.
They cannot copy 18 months of one dealer's creative performance, customer history, and
learned playbook. Switching cost compounds monthly.

---

## 5. Product principles

1. **Never invent a fact about a car.** Specs, prices, and availability come from the
   database or the answer is an escalation. This is enforced in code, not in a prompt.
2. **The real car, not a generated one.** Creative composites the dealer's actual photos.
   We never text-to-image a vehicle. (See [01](01-system-architecture.md) § Media.)
3. **Autonomy is granted, never assumed.** Every tenant chooses what the AI may do
   unsupervised. Defaults are conservative.
4. **Every action is attributable.** Which agent, which model, which prompt, what it
   cost, what it produced. No black boxes in front of a customer's money.
5. **Show the decision, not the dashboard.** The product's home screen is a recommendation
   with an Execute button, not fifteen charts.
6. **One tenant can never see another.** Non-negotiable, enforced at the database.
7. **Trilingual by default.** Arabic, English, French are first-class — including in
   retrieval, not just in output.

---

## 6. Jobs to be done

| # | Job | v1 |
|---|---|---|
| J1 | "Turn my stock into content without me" | Yes |
| J2 | "Publish it on the right channels on schedule" | Yes |
| J3 | "Answer every customer instantly, correctly, in their language" | Yes |
| J4 | "Qualify and score leads so my team calls the right people" | Yes |
| J5 | "Chase the customers who went quiet" | Yes |
| J6 | "Tell me what my money bought" | Basic |
| J7 | "Run and optimize my ads" | Phase 2 |
| J8 | "Tell me what competitors and the market are doing" | Phase 2 |
| J9 | "Get better every month without me tuning it" | Phase 2 |
| J10 | "Give me a plan when I state a goal" | Phase 3 |

---

## 7. Scope by phase

### Phase 1 — Operate (MVP)

Workspaces, Brand Brain, inventory, content factory, Instagram and Facebook publishing,
unified inbox, WhatsApp sales agent, leads CRM, basic analytics, Meta Ads read-only
reporting.

**Thesis to prove:** the AI can do a real day of a marketing coordinator's work, and a
dealer will let it.

### Phase 2 — Grow

Ads write access with budget guardrails, competitor tracking, market intelligence,
content performance learning, playbook v1, TikTok.

**Thesis to prove:** the system's decisions beat the human's defaults on cost per lead.

### Phase 3 — Autonomous

Growth Director goal decomposition, automated experimentation, forecasting, advanced
lead scoring, multi-vertical core.

**Thesis to prove:** a dealer will hand over a monthly budget and a goal.

Full in/out lists: [06-mvp-scope.md](06-mvp-scope.md).

---

## 8. Success metrics

### Product health (per tenant, monthly)

| Metric | Phase 1 target |
|---|---|
| Content pieces published | 60 or more |
| Percent published without human edit | 50% or more |
| Median first-response time, all channels | Under 60 seconds |
| Conversations fully handled without escalation | 60% or more |
| Leads captured | 120 or more |
| AI-attributed qualified leads | 35 or more |
| Vehicles with zero content in 30 days | 0 |
| Wrong-price or wrong-availability incidents | **0 — hard gate** |

### Business

| Metric | Target |
|---|---|
| Design-partner tenants live | 3 by end of Phase 1 |
| Time from signup to first published post | Under 48 hours |
| Net revenue retention | Above 110% by month 12 |
| Gross margin after model and media cost | Above 70% |
| AI cost per tenant per month | Under USD 120 at MVP volume |

### Counter-metrics (watch for damage)

Escalation rate rising, customer complaint rate, brand-guard rejection rate, unfollow and
mute rate, share of replies a human rewrites before sending.

---

## 9. Pricing hypothesis

| Tier | AED/month | Includes |
|---|---|---|
| **Starter** | 2,500 | 1 brand, 3 channels, 60 content/mo, inbox + WhatsApp agent, leads |
| **Growth** | 6,500 | Plus ads management, competitor tracking, learning loop, 200 content/mo |
| **Scale** | 15,000+ | Multi-brand and multi-branch, export desk, API access, priority models |
| Overages | metered | Content beyond quota, video minutes, ad spend under management |

Anchor against one marketing hire (AED 8–12k per month, works 8 hours) plus an agency
retainer. Do not price against Buffer.

---

## 10. Non-goals

- We do not build a website builder or a classifieds marketplace.
- We do not take payments, deposits, or handle contracts.
- We do not do vehicle valuation or financing underwriting.
- We do not fabricate vehicle imagery.
- We do not offer a generic "AI social tool" for non-automotive verticals in v1 to v3.
- We do not scrape platforms in violation of their terms to build market intelligence.
  Official APIs and licensed or permitted sources only. See section 12.

---

## 11. Key risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Meta / WhatsApp / TikTok app review delay** | High | Start review in M0, before the feature is finished. Build against mock connectors so review is never the critical path. |
| **AI states a wrong price or offers a sold car** | Company-ending | Price and inventory guards run in code after generation. Any reply containing a number not sourced from the database is blocked and escalated. Zero-tolerance metric. |
| **Generated creative embarrasses the brand** | High | Deterministic compositor with brand tokens, plus Brand Guard validation, plus a tenant-configurable approval gate. |
| **Ad budget overrun by an agent** | High | Hard caps in code: max percent change per 24h, max daily, max campaign total. Breach means human approval, never auto-execute. |
| **Platform policy change breaks publishing** | Medium | The connector layer isolates blast radius. Every connector has a health check and a degraded mode. |
| **Cost per tenant exceeds price** | Medium | Model gateway routes to the cheapest sufficient tier, prompt caching on all stable prefixes, Batch API for bulk generation, per-tenant cost ceiling with alerting. |
| **Tenant data leakage** | Company-ending | RLS on every table, no service-role key in request paths, a cross-tenant test in CI that must fail loudly. |
| **Dealer will not grant Autopilot** | Medium | Copilot is a complete product on its own. Autonomy is an upgrade path, not a prerequisite. |
| **Arabic quality — dialect, RTL rendering** | Medium | Multilingual embeddings, a native-speaker eval set per tenant, and RTL treated as a first-class case in the compositor rather than an afterthought. |

---

## 12. Compliance and legal

- **UAE PDPL** — customer conversations and contact data are personal data. Per-tenant
  data residency preference, export and delete endpoints, defined retention.
- **WhatsApp Business** — opt-in required. The 24-hour customer service window governs
  free-form replies; outside it, only approved template messages. This shapes the
  Follow-up Agent's design — see [05](05-workflows.md) § W7.
- **Platform terms** — publishing, messaging, and ads go through official APIs.
  Competitor intelligence uses only publicly documented endpoints such as Meta's Ad
  Library, plus licensed data. No credential-based scraping of competitor accounts.
- **AI disclosure** — automated conversations identify as an assistant on first contact
  and offer a human. Cheaper than the trust damage of being caught.
- **Advertising claims** — price and offer text in creative carries the tenant's
  disclaimer block. The Brand Guard enforces required legal wording per market.

---

## 13. Open questions

| # | Question | Needed by | Owner |
|---|---|---|---|
| Q1 | Do we resell ad spend, or does the tenant's own Meta billing pay? Changes billing and liability. | Phase 2 start | Founder |
| Q2 | Which video path for Reels: FFmpeg compositor only, or a licensed model for B-roll? | M4 | Eng |
| Q3 | Do we support Arabic dialect selection per tenant (Gulf, Egyptian, MSA)? | M2 | Founder + design partner |
| Q4 | Do exporters need a separate tenant type, or is it a market flag on the same tenant? | M1 | Founder |
