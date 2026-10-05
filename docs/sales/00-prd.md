# Sales — Product Requirements

**Version:** 1.0 · **Status:** Draft for review · **Owner:** Founder · **Tenant zero:** Pollux Motors

---

## 1. One sentence

A sales operating system for car dealers: every conversation on the company WhatsApp number lands
in one inbox and one customer record, an AI copilot drafts replies that are true to live inventory,
salespeople send them, and the manager sees who is answering, who is not, and which deals are close.

---

## 2. The problem

What happens at a dealer like Pollux today:

| Symptom | Root cause |
|---|---|
| Each salesperson answers on their own WhatsApp; the manager cannot see a single conversation | The channel lives on personal phones |
| Customers wait hours, overnight, or forever | No assignment, no response tracking, no alert |
| When a salesperson leaves, their customers leave with the phone | The relationship belongs to a device, not the company |
| Prices and availability are quoted from memory and are sometimes wrong | Inventory is not in the conversation |
| A returning customer is qualified again from zero | No shared history |
| Follow-ups happen when someone remembers | No tasks, no reason-driven reminders |
| "How are sales going today?" has no answer before the evening | No live data |

The dealer does not lack a CRM product — Kommo, WATI and respond.io exist. They lack **control of
the conversation** and **inventory-true answers**, in Arabic, English and French, on a phone.

---

## 3. Who it is for

| Persona | Wants | Judges the product on |
|---|---|---|
| **Owner / GM** (Khalid) | Control of every customer relationship; sales visibility | One screen each morning: what happened, who is late, which deals to push |
| **Sales manager** (Sara) | Every customer answered fast, fairly distributed | Live waiting list, per-rep response times, reassign in one click |
| **Salesperson** (Ahmed) | Warm leads, fast accurate answers, no forgotten follow-ups | Is the inbox faster than WhatsApp on the phone? Are the AI drafts right? |
| **Export desk** (Salem) | Buyers in Algeria, Morocco, Tunisia, Oman, Saudi Arabia | French and Arabic drafts that get shipping and documents right |

**Not for (Phase 1):** marketplaces, private sellers, rental fleets, non-automotive businesses.

---

## 4. Product principles

1. **The conversation belongs to the company.** Every message on the number is recorded against a
   customer, whoever sent it and from wherever.
2. **Never invent a fact about a car.** Price, availability and specs come from the database or the
   draft is blocked. Enforced in code (DealerAI OS guards), not in a prompt.
3. **The AI suggests; a person sends.** In Phase 1 nothing reaches a customer without a human.
4. **A salesperson sees their own customers.** Enforced in the database, not by hiding buttons.
5. **Mobile first.** Salespeople live on phones; the inbox has to beat the WhatsApp app there.
6. **Three languages, first class.** Arabic (with the customer's dialect), English and French — in
   the drafts, in retrieval, and in the interface (EN/AR in Phase 1).
7. **Show the decision, not a chart.** The manager's first view is who is waiting and what to do.

---

## 5. Jobs to be done

| # | Job | Phase |
|---|---|---|
| J1 | "See every customer conversation on our number, including replies from the phone" | 1 |
| J2 | "Make sure nobody waits — assign fairly and tell me when someone does" | 1 |
| J3 | "Answer correctly and fast in the customer's language" | 1 (copilot) |
| J4 | "Know who this customer is and what they want without scrolling" | 1 |
| J5 | "Track every lead to won or lost" | 1 |
| J6 | "Remind me to follow up only when there is a reason" | 1 |
| J7 | "Tell me each morning how sales are going and what to do" | 1 |
| J8 | "Same, for Instagram, Messenger, website chat and email" | 2 |
| J9 | "Answer routine questions after hours without me" | 2 |
| J10 | "Coach my salespeople from their real conversations" | 2 |
| J11 | "Let me design my own automations" | 3 |

---

## 6. Scope by phase

### Phase 1 — Control the conversation (~14 weeks)

| Area | Ships |
|---|---|
| WhatsApp | Company number via coexistence · 180-day history import · phone-app replies mirrored · send and receive text, media, voice notes, locations, documents · templates when the 24h window is closed · voice notes transcribed · delivery and read status |
| Inbox | Views Mine / Unassigned / Team / All · auto-assignment (existing owner, routing rules, least-recently-assigned) · internal notes · quick replies · car cards · live updates · unread counts · response timers |
| Customers | Channel identities · Customer 360 timeline · structured profile (AI or human, with evidence) · tags · reassign · manual merge |
| Pipeline | Configurable pipelines (Pollux: Local sale, Export) · leads with score and band · board and list · stage history · lost reasons |
| Tasks | Tasks and follow-ups with due dates · AI follow-up drafts with a reason · My day |
| Team | Roles owner / admin / manager / sales / marketer / viewer · teams · languages · taking-chats availability · invitations |
| AI copilot | Intent and language · drafts grounded in inventory and knowledge documents · guards · summaries · profile extraction · lead scoring · follow-up drafts · knowledge uploads |
| Manager | Dashboard (waiting, response times, missed targets, per-rep, pipeline, sources, inbox-vs-phone share) · daily brief · notifications |
| App | Responsive web app, installable (PWA), push notifications · UI in English and Arabic |

### Phase 2 — Every channel, some autonomy

Instagram DMs and Facebook Messenger · website chat widget · email (Gmail, Outlook) · after-hours
Assisted mode for routine questions (with AI disclosure and handoff) · AI sales coach · image
understanding (car photos, listing screenshots) · quotation PDF · template campaigns (the
replacement for broadcast lists) · global search.

### Phase 3 — Operating system

Visual automation builder · calls with summaries · AI Manager Q&A · self-serve onboarding for other
dealers · a separate SaaS Tech Provider entity.

---

## 7. Phase 1 success criteria

Measured live on Pollux. All must hold.

| # | Criterion | Target |
|---|---|---|
| S1 | Conversations on the number visible in the inbox, including phone-app replies | 100%, p95 within 5 s |
| S2 | Median first response in business hours | Under 5 minutes (baseline from imported history) |
| S3 | A salesperson can see another salesperson's customers | Never — automated test on every table and list endpoint |
| S4 | Wrong price or availability in an AI draft | Zero across the eval set and a production audit |
| S5 | AI drafts sent unchanged or lightly edited | 60% or more by week 4 of the pilot |
| S6 | Open leads without an owner or a next action | Zero |
| S7 | Webhook acknowledgement | p95 under 500 ms; zero duplicate sends |
| S8 | Replies sent from the inbox rather than the phone app | Tracked; rising week over week |

### Counter-metrics

Customer complaints about bot-like replies · drafts discarded as "wrong info" · guard rejections ·
WhatsApp quality rating drops · template rejections · reps reverting to the phone app.

---

## 8. Deferred, with the trigger to build

| Deferred | Build it when |
|---|---|
| Visual automation builder | Preset rules (assignment, response targets, follow-up cadence) fail a real request twice |
| AI Autopilot on WhatsApp | Drafts for an intent are accepted 80%+ for 30 consecutive days |
| Instagram / Messenger | Phase 1 criteria met; Meta permissions approved |
| Redis / Celery | Queue depth above 500 sustained, or p95 pickup above 5 s |
| Calls | Phase 3 — calling is not available on coexistence numbers |
| Multi-vertical SaaS | 20 paying automotive tenants |
| Support role | A tenant has an after-sales team using the inbox |
| Reranker for retrieval | Golden-set recall below 85% |

---

## 9. Non-goals

- **No payments.** Deposit and payment are pipeline stages, not transactions (DealerAI OS PRD §10).
- **No unofficial WhatsApp access.** No WhatsApp Web automation, no Selenium, no personal numbers.
  Only the WhatsApp Business Platform.
- **No cold outbound or broadcasts in Phase 1.** Templates are for customers who already wrote.
- **No automatic merging by name or email similarity.** Merges are manual and audited.
- **No general-purpose chatbot.** The assistant only works this dealer's sales and service
  (WhatsApp Business Solution Terms, January 2026).
- **No native mobile apps in Phase 1.** The PWA must earn them.

---

## 10. Compliance

- **WhatsApp Business Messaging Policy.** Opt-in for business-initiated messages; opt-out honoured
  immediately ("stop" revokes consent in code); free-form only inside the 24-hour window; templates
  outside it; a clear path to a human (in Phase 1 a human sends everything).
- **WhatsApp 2026 AI terms.** General-purpose AI assistants are prohibited on the Business Platform.
  The copilot is scoped to this dealer's vehicles, policies and customers, and redirects off-topic
  requests.
- **Meta Tech Provider terms.** Pollux Motors is the provider business; business verification and app
  review with advanced access to `whatsapp_business_messaging` and `whatsapp_business_management`.
- **UAE PDPL.** Conversations, voice notes, documents (passports for export) and contact data are
  personal data: per-tenant retention (default 24 months), export and delete per customer, access
  limited by role and scope, audit log on reassign, merge and deletion.
- **AI disclosure.** Not applicable while a human sends every message; mandatory for Phase 2
  after-hours replies.
- **Model data use.** Paid Gemini API tier only — free-tier prompts may be used for training.

---

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Tech Provider review slow or rejected | High | Submit by week 3; build everything else on the test number and the mock connector; fallback pilot on a second API-only number |
| Salespeople keep replying from the phone app | High | Inbox-vs-phone share on the dashboard; the inbox must be faster on mobile; manager policy |
| AI draft states a wrong price | Company-ending | Price and inventory guards in code; zero-tolerance eval gate; human sends |
| Phone number hidden (usernames) splits a customer in two | Medium | BSUID-first identity; manual merge with audit |
| Arabic dialect or Darija voice notes mis-transcribed | Medium | Transcript shown beside the audio; drafts cite it; 50-note spot check before rollout |
| Visibility RLS slows large lists | Medium | Visible owners computed once per query; owner-column indexes; measured on seeded volume |
| Supabase in Tokyo adds 150–200 ms per request from the UAE | Medium | Q1 below — answered: the new project is made in Mumbai |
| Template spend outside the window grows | Low | Follow-ups prefer the open window; marketing templates only with consent; costs visible per category |

---

## 12. Open questions

| # | Question | Needed by | Owner |
|---|---|---|---|
| Q1 | ~~Recreate the Supabase project in Mumbai (ap-south-1) before real customer data?~~ **Answered 2026-10-05: Mumbai, for the project customers' data will live in.** The first project was found gone, so there is nothing to move. Staging's project is in Singapore, where it happened to be made and where the owner left it, with its API and worker beside it on Fly.io ([10](10-staging.md) §1) | — | Founder |
| Q2 | Which two salespeople pilot first? | Week 11 | Founder |
| Q3 | Default Arabic register for UAE customers: mirror the customer, or Gulf-leaning formal? | Week 7 (drafts) | Founder + sales team |
| Q4 | When does the SaaS company exist, so the Tech Provider can move to it? | Phase 3 | Founder |
