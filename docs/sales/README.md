# DealerAI OS — Sales

> **One inbox. One customer record. One AI copilot.** Every conversation on the dealer's WhatsApp
> number, including replies typed on the phone, lands in one place that the whole sales team works
> from and the manager can see.

---

## What this is

The Sales module turns a dealer's company WhatsApp number into a managed sales channel:

- every conversation lands in a shared **inbox** and a **customer record**, whether the reply was
  sent from the inbox or typed in the WhatsApp Business app on the phone;
- conversations are **assigned** automatically, with **response targets** the manager can see;
- an **AI copilot** drafts replies grounded in live inventory and the dealer's documents, and a
  salesperson sends them;
- leads move through configurable **pipelines** (local sale, export), with **tasks** and
  **follow-ups** that have a reason to exist;
- the manager gets a live **dashboard** and a **daily brief**.

It is a module of DealerAI OS, not a separate product. It sits on the foundation that already
exists and is tested — tenancy and RLS, the Postgres event queue, the model gateway, the connector
contract, guards, the autonomy gate and the agent runtime. Those are documented in `docs/00–09` and
are not re-described here.

**Tenant zero:** Pollux Motors (UAE dealer and exporter; customers write in Arabic, English and
French). Every Phase 1 feature must be usable by their sales team in week one of the pilot.

---

## Reading order

| # | Document | Read it for |
|---|---|---|
| 00 | [PRD](00-prd.md) | The problem, personas, phases, success criteria, non-goals, compliance |
| 01 | [Architecture](01-architecture.md) | What is added to DealerAI OS, request paths, live updates, visibility, failure modes |
| 02 | [Data model](02-data-model.md) | Every new and changed table for the Sales migrations (one per slice), visibility RLS, the test matrix |
| 03 | [WhatsApp](03-whatsapp.md) | Cloud API, coexistence, Embedded Signup, every webhook, identity, templates, Meta onboarding |
| 04 | [AI copilot](04-ai-copilot.md) | Drafts, guards, profile, summaries, scoring, follow-ups, evals, cost |
| 05 | [Workflows](05-workflows.md) | Event catalogue additions and every end-to-end flow with failure handling |
| 06 | [API contract](06-api-contract.md) | Routes, shapes, permissions, live events, errors |
| 07 | [Frontend](07-frontend.md) | `apps/web` architecture: data access, live updates, i18n and RTL, PWA, tests |
| 08 | [Screens](08-screens.md) | Every screen: purpose, data, states, actions, roles, mobile, "done when" |
| 09 | [Implementation plan](09-implementation-plan.md) | Slices S0–S7, the Meta track, definition of done; step-by-step plans in [`plans/`](plans/) |
| 10 | [The staging day](10-staging.md) | Making staging, in order: the project, authentication, the API and the worker, the web app, the check, and the first sign-in |
| 11 | [The new look](11-ui-refresh.md) | What the app looks like and why: colours, type, shared styles, the shell, every Sales screen, and how it is checked |

---

## Decisions

Settled during brainstorming on 2026-09-15. Changing one invalidates parts of several documents —
say so explicitly if you do.

| Decision | Choice | Why |
|---|---|---|
| Relationship to DealerAI OS | **One platform, sales-first** | The foundation is built and tested, and a Pollux customer must have one record across every channel, not one per product |
| WhatsApp model | **Company number through coexistence** (WhatsApp Business app + Cloud API on the same number) | Same number, 180 days of history, the phone app keeps working, manager visibility from day one |
| Meta Tech Provider | **Pollux Motors**, for now | Coexistence is only offered by Tech Providers; Pollux has the verification documents today. Re-onboarding under a future SaaS company is cheap while there is one tenant |
| Frontend data access | **API-only**: all app data through FastAPI, TypeScript types generated from OpenAPI, Supabase in the browser for sign-in only | One contract; visibility enforced in one place; browser roles lose table privileges |
| Who builds | **Claude builds backend, frontend and integration** as vertical slices against the local stack | No browser mock API to keep in sync with the real rules |
| Customer identity | **WhatsApp business-scoped user ID first, phone second** | Since 2026 WhatsApp can omit the phone number for users with usernames |
| Visibility | **Enforced in Postgres** (session settings + RLS), like tenancy | A rep seeing another rep's customers is a leak, and forgetting a `WHERE` must not cause one |
| AI autonomy, Phase 1 | **Copilot only** — the AI drafts, a person sends | Trust is earned from measured acceptance; the autopilot trigger is defined in 00 |
| Model provider | **Gemini through the existing gateway** (the brief suggested OpenAI) | Verified live, prompt caching measured; swapping is a one-file change if an eval demands it |
| Job system | **Postgres outbox** (the brief suggested Redis + Celery) | Built and tested; upgrade trigger in DealerAI OS 01 §3 |
| Live updates | **Postgres NOTIFY → SSE** | No new infrastructure; ceiling ~2k streams per API instance |

### What this changes in the DealerAI OS documents

| Document | Said | Now |
|---|---|---|
| 01 §2 path A, 07 §1 | The browser reads Supabase directly under RLS | All application data goes through FastAPI. `anon` and `authenticated` lose table privileges |
| 03 `contacts.external_refs`, 09 T5.1 | Contacts resolved by phone and a jsonb of platform ids | `contact_identities` with a unique index; BSUID first ([03](03-whatsapp.md) §5) |
| 03 `leads.stage` | A fixed stage list | `pipelines` + `pipeline_stages` per tenant |
| 00 / 03 roles | owner, admin, marketer, sales, viewer | adds **manager**, plus **teams** |
| 06 §5, 09 | M3 → M4 → M5 → M6 | Sales Phase 1 first; T3.1, T3.7, T3.8 and M4 publishing follow it |
| 06 §3 | French "when an export-focused tenant signs" | Pollux is export-focused: AI drafts in French in Phase 1 (UI stays EN/AR) |
| 09 T4.7–T5.6 | Inbox, WhatsApp, CRM, sales agents as M4–M5 tasks | Superseded by `docs/sales/09-implementation-plan.md` |

---

## Status

| Area | State |
|---|---|
| Documentation | Draft, 2026-09-16 — awaiting review |
| Code | **S6 manager view complete** on `sales/phase-1` (S0–S4 before it): the manager's dashboard, every number read through the reader's own visibility, with a morning brief whose one model-written line a guard refuses if it holds a number the facts do not; settings screens for channels, the team, routing and targets, pipelines, quick replies, knowledge and the AI; bulk hand-over; and PDPL export and erasure — erasure reaching the raw payloads — with nightly retention ([review](plans/s6-manager-view.md#review--2026-09-26)). **S7 Part A, sign-in and joining**, is done: invitations for one address into teams, sign-up and Google, a first workspace, both languages ([review](plans/s7-pilot-readiness.md#part-a-review--2026-09-30)). **S7 Part B, installable app and push**, is done: a manifest, icons and a service worker that keeps nothing a customer said; Web Push from the worker, encrypted and signed to the letter of RFC 8291 and RFC 8292 with no push library, for assignment, waiting too long, a task falling due and a hot lead; Settings → Notifications; and signing out, which silences the device — verified locally against a stand-in for a push service, a real phone being Part D's ([review](plans/s7-pilot-readiness.md#part-b-review--2026-10-02)). **S7 Part C, the Arabic and accessibility pass**, is done: times, counts and stored codes said in the reader's language; what a person wrote keeping its own direction; the API's refusals and the worker's notifications written in Arabic for whoever reads Arabic; dialogs on the platform's own `<dialog>`; a heading and a way past the navigation on every page; and a template picker for a closed 24-hour window — 40 states in each language at 375 px with no `axe-core` violation, and a day's work done with the keyboard alone ([review](plans/s7-pilot-readiness.md#part-c-review--2026-10-03)). **S7 Part D, the Playwright suite and what staging needs from the code**, is built: 65 end-to-end tests walk every slice's exit — the day's work as a salesperson, a manager and the owner, in both languages at 360 px and 1440 px, then joining, who sees whom, live updates, a path through every other screen and `axe-core` on every page — against a stack of their own, in under five minutes, as a CI job; it found a search box that lost letters and fixed it. For staging: sessions verified against the keys a project publishes, a deployment that refuses to start wrong, one image for the API and the worker, `npm run smoke`, email links that open in any browser, a forgotten password, and [the staging day](10-staging.md) written down ([review](plans/s7-pilot-readiness.md#part-d-review--2026-10-05)). **The new look** is built, before anybody outside sees the app: every colour behind a name with a light and a dark value, one typeface for Latin and Arabic, a rail of icons on a desk and a floating bar on a phone, and every Sales screen redrawn on them — the 65 end-to-end tests passing as they were written, and one more that sweeps every page in dark mode ([11](11-ui-refresh.md), [reviews](plans/ui-refresh.md)). **Not done: staging itself.** Its Supabase project exists with the schema on it, and nothing after that has been run ([10](10-staging.md)). Next: the rest of the staging day; S5 waits on Meta |
| Meta | Business verification and Tech Provider review not started (Pollux Motors). **Critical path** |
| Supabase project | Staging: Singapore (`ap-southeast-1`), on the Free plan, with the schema on it. The pilot's is to be in Mumbai (`ap-south-1`), on a paid plan ([10](10-staging.md) §1) |

---

## Glossary

- **Coexistence** — one phone number used by the WhatsApp Business app *and* the Cloud API at the
  same time; messages sync both ways.
- **Echo** — a message the business typed in the phone app, delivered to us by the
  `smb_message_echoes` webhook.
- **BSUID** — WhatsApp's business-scoped user ID (`US.1349…`). Stable for one customer across all
  numbers of one business portfolio; changes if the customer changes their phone number.
- **24-hour window** — after a customer's last message, the business may send free-form messages
  for 24 hours. Outside it, only approved **templates**.
- **Template** — a message pre-approved by Meta, with variables, in a category (utility, marketing,
  authentication) that decides its price.
- **Response target** — the time within which a waiting customer should get a first reply
  (the SLA). Measured in business hours.
- **Draft** (suggestion) — a reply the AI proposes. Never sent without a person in Phase 1.
- **Scope** — what a user may see: `own` (sales), `team` (manager), `all` (owner, admin, viewer).
- **Owner** (of a customer) — the salesperson who holds the relationship. Not to be confused with
  the `owner` role.
