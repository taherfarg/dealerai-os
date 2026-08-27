# MVP Scope

**Status:** Approved · Depends on: [00-prd.md](00-prd.md)

---

## 1. The one-line test

> **A dealer connects Instagram, uploads 30 cars, and one week later has published
> 40 pieces of on-brand content, answered every comment and WhatsApp message within a
> minute, and has a scored lead list — without hiring anyone.**

Anything that is not required for that sentence is not in the MVP.

---

## 2. In scope

| # | Module | What ships | Explicitly not in v1 |
|---|---|---|---|
| 1 | **Workspaces** | Tenant creation, Supabase Auth, roles (owner/admin/marketer/sales/viewer), invitations, RLS | SSO, SCIM, multi-brand under one tenant, custom domains |
| 2 | **Brand Brain** | Logo + brand-guide upload, AI extraction of palette/typography/tone, human confirmation, forbidden terms, disclaimers, CTA style | Brand style transfer across tenants, auto-generated logos |
| 3 | **Vehicle inventory** | Manual add, CSV import with LLM-assisted column mapping, photo upload, vision QA + angle labelling + ranking, price history, status lifecycle | Live DMS integrations, VIN decoder API, auction feeds |
| 4 | **Content factory** | Briefs, creative direction, copy in AR/EN, deterministic compositor, 4 aspect ratios, 8 templates | Video / Reels, user-authored templates, stock imagery |
| 5 | **Calendar & approvals** | Week and month views, drag to reschedule, approval queue, inline edit of caption and asset choice | Multi-stage approval chains, client-review portals |
| 6 | **Publishing** | Instagram + Facebook: posts, carousels, stories. Scheduling, retries, per-channel publication state | TikTok, LinkedIn, X, Snapchat, YouTube |
| 7 | **Unified inbox** | IG comments, IG DMs, FB comments, WhatsApp. One thread view, assignment, AI-paused state | Email, live site chat, voice, Telegram |
| 8 | **AI responders** | Intent classification, Community Manager for comments, Sales Agent for DM/WhatsApp, escalation | Voice calls, outbound cold messaging |
| 9 | **Leads CRM** | Contacts, Customer 360, leads with score and band, stages, activities, assignment, follow-up sweep | Full pipeline automation, quotes, contracts, e-signature |
| 10 | **Analytics** | Content performance, funnel (impressions → leads → qualified → deals), per-vehicle content coverage, AI cost per tenant | Custom report builder, exports beyond CSV, BI connectors |
| 11 | **Ads (read-only)** | Connect Meta Ads, sync campaign metrics, show real CPL joined to our funnel | Creating, editing, or budgeting campaigns |
| 12 | **Agent runtime** | Runs, task DAG, traces, approvals, cost accounting, SSE streaming, autonomy modes | Growth Director goal decomposition (Phase 3) |
| 13 | **Daily brief** | Morning digest with up to 3 recommendations | Executable one-click plans (Phase 3) |

---

## 3. Out of scope for v1, with the trigger to build it

Not "never" — "not until."

| Deferred | Build it when |
|---|---|
| Reels / video | Content approval rate is stable above 70% and a design partner asks twice |
| TikTok publishing | App audit is approved *and* a tenant has an audience there |
| Ads write access | Read-only CPL has been accurate for 30 days against the tenant's own reporting |
| Competitor tracking | Two design partners name the same competitor unprompted |
| Learning loop | A tenant has 100+ published items with outcome data — below that the statistics are noise |
| Growth Director | The specialist agents each hold above an 80% shadow-mode agreement rate |
| French | An export-focused tenant signs |
| Redis / ARQ | Sustained queue depth above 500 or p95 pickup latency above 5 s |
| Reranker model | Golden-set retrieval recall drops below 85% |
| Separate render service | More than 10k renders/day or render p95 above 4 s |
| Multi-vertical core | Automotive has 20 paying tenants |

---

## 4. Acceptance criteria

MVP is done when **all** of these are demonstrably true on a real tenant.

### Functional

- [ ] A new tenant reaches its first published Instagram post in under 48 hours, unaided.
- [ ] A CSV of 50 vehicles imports with correct column mapping after one human confirmation.
- [ ] One vehicle with 8 good photos yields at least 8 approved content pieces.
- [ ] Rendered creative matches the tenant's brand tokens exactly — a designer signs off per template.
- [ ] Arabic renders correctly RTL in every template at every aspect ratio.
- [ ] A scheduled post publishes to Instagram and Facebook within 60 seconds of its slot.
- [ ] An Instagram comment asking a price receives a correct, sourced reply in under 60 seconds.
- [ ] A WhatsApp conversation runs 5+ turns and produces a scored lead.
- [ ] Marking a vehicle sold pauses every scheduled item referencing it.
- [ ] Escalation assigns a human, pauses the AI on that thread, and notifies.
- [ ] Every AI output links back to the run that produced it.
- [ ] Each autonomy mode gates exactly the actions in the [02](02-agent-architecture.md) § 5 matrix.

### Quality gates

- [ ] Intent classification accuracy above 95% on the 200-message golden set (AR + EN).
- [ ] **Zero** wrong-price or wrong-availability statements across the full eval set.
- [ ] LLM-judge mean above 4.0/5 on sales replies, with no accuracy score below 3.
- [ ] Cross-tenant isolation test passes on every table, both access paths, and views.
- [ ] Prompt cache hit rate above 60% on the agent test suite.
- [ ] p95 webhook acknowledgement under 500 ms.
- [ ] p95 content render under 4 s per aspect ratio.
- [ ] AI cost per tenant under USD 120/month at 60 posts and 500 conversations.

### Operational

- [ ] Meta app approved for `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`, `pages_manage_posts`.
- [ ] WhatsApp Business account live with at least 3 approved message templates.
- [ ] Staging mirrors production; migrations run clean from empty.
- [ ] A failed publish, an expired token, and a guard rejection each surface in the UI with a human-readable cause.
- [ ] Runbook exists for: token expiry, platform outage, stuck queue, cost overrun.

---

## 5. Milestones

| M | Name | Exit criterion | Weeks |
|---|---|---|---|
| **M0** | Foundation | Repo, CI, migrations applied, cross-tenant test green, **Meta + WhatsApp app review submitted** | 1–2 |
| **M1** | Tenancy & auth | Sign up, create tenant, invite a teammate, roles enforced end to end | 2–3 |
| **M2** | Inventory | CSV import, photo QA and angle labelling running, inventory UI | 3–5 |
| **M3** | Content factory | One vehicle → 8 rendered, on-brand, guard-passing pieces | 5–8 |
| **M4** | Publish & inbox | Live publishing to IG/FB; comments and DMs arriving and answered | 8–11 |
| **M5** | Sales & CRM | WhatsApp Sales Agent, lead scoring, follow-up sweep | 11–14 |
| **M6** | Analytics & brief | Funnel, attribution, daily brief with recommendations | 14–16 |
| — | **MVP complete** | All acceptance criteria met on a live tenant | **~16** |
| M7 | Ads management | Phase 2 |  |
| M8 | Market intelligence | Phase 2 |  |
| M9 | Learning loop | Phase 2 |  |

**M0 contains app review submission on purpose.** Meta and WhatsApp review is measured in
weeks and is outside our control. Everything until M4 is built against the mock connector,
so review runs in parallel with development instead of blocking the launch.

---

## 6. What we will be tempted to build and must not

| Temptation | Why it is a trap in v1 |
|---|---|
| A template designer UI | Weeks of work. Eight good templates plus a designer authoring HTML covers every MVP need. |
| Text-to-image vehicle generation | Demos beautifully, is unusable — the car is wrong. See [01](01-system-architecture.md) § 6. |
| Full Growth Director | Needs specialists that are already trustworthy. Building the boss before the workers produces confident nonsense. |
| Generic "AI chat with your data" | Every SaaS has one, nobody uses it. Ship the specific workflows instead. |
| Multi-vertical from day one | The automotive-specific inventory and spec model is the moat. Generalizing early destroys it. |
| Custom fine-tuned models | Frontier models with good context beat a fine-tune we cannot maintain, at this data volume. |
| Real-time collaborative editing | Two people rarely edit one caption at once. Last-write-wins with an edit log is enough. |
