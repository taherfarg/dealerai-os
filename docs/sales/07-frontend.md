# Sales — Frontend

**Status:** Draft · **Depends on:** [01](01-architecture.md) §2, [06](06-api-contract.md), DealerAI OS [08](../08-folder-structure.md) §2

---

## 1. What exists today

`apps/web` is Next.js 16.3.4 (App Router), React 19.2, TypeScript strict, Tailwind v4 with tokens in
`app/globals.css`, a Supabase auth gate in `proxy.ts` (Next 16's middleware file), the `[tenant]` URL
segment, a small typed message catalogue in `lib/i18n.ts`, a server-side fetch helper in `lib/api.ts`,
three pages (login, command center, approvals) and `scripts/check-logical-css.mjs`, which fails the
build on any physically-directional Tailwind class.

Not there yet and added in Phase 1: shadcn/ui, React Query, the generated API types, the live-update
stream, and every sales screen.

---

## 2. Data access and generated types

```
apps/api  Pydantic models ──► /openapi.json ──► openapi-typescript ──► lib/api/schema.ts
                                                                          │
lib/api/client.ts   typed fetch (openapi-fetch): base URL, Supabase access token,
                    X-Tenant-Id, Idempotency-Key, problem+json → ApiError
                                                                          │
lib/api/hooks.ts    React Query hooks + one keys object + optimistic mutations
                                                                          ▼
                    screens (client components) and server components for first paint
```

- `npm run api-types` regenerates `schema.ts`. CI regenerates it and fails if the file changes, so the
  frontend and backend cannot drift silently.
- **No component ever calls `fetch` directly, and nothing queries Supabase tables.** `lib/supabase/*`
  exists only for the session. A lint rule and a grep check in CI enforce both.
- Server components fetch for first paint on read-heavy screens (inbox list, dashboard) and hand the
  data to client components as initial React Query state; everything interactive then talks to the
  hooks.
- Optimistic updates for sending, assigning, stage moves and completing tasks; a failure rolls back
  and shows the API's `detail` in a toast.

---

## 3. Live updates

`useLiveEvents()` mounts once in `app/[tenant]/layout.tsx`:

- Opens `/v1/stream` with a fetch-based SSE reader (the native `EventSource` cannot send the
  `Authorization` header), reconnecting with exponential backoff and jitter.
- Maps each event to query invalidations — thread, conversation, lists, counts, lead, tasks,
  notifications, channels.
- Raises a toast for `sla_breached`, `assigned` and `lead_hot` notifications, and keeps the unread
  count in the tab title.
- On reconnect it refetches active queries rather than replaying anything.

---

## 4. Routes

```
app/[tenant]/
  page.tsx                     → redirect to inbox
  inbox/                       layout (3 panes on desktop) · page (list) · [conversationId]/page
  today/                       My day
  customers/                   page (list) · [contactId]/page (Customer 360)
  pipeline/                    page (board and list, ?pipeline=, ?lead= opens the drawer)
  tasks/                       page
  dashboard/                   page (managers)
  settings/                    page · channels · team · routing · pipelines · quick-replies ·
                               knowledge · ai · notifications
  inventory/ content/ approvals/   existing
```

Desktop uses a sidebar and multi-pane layouts; mobile uses a bottom navigation bar and moves from
list to detail as separate screens. The `[tenant]` segment stays in the URL so a pasted link opens
the same workspace for whoever clicks it.

---

## 5. UI system

- **shadcn/ui** components, with their physically-directional classes converted to logical ones on
  the way in (`ml-` → `ms-`, `right-` → `end-`), because `check:rtl` scans `components/` too.
- **Tokens** extend `globals.css` rather than replacing it: `--success`, `--warning`, `--info`,
  `--hot`, `--warm`, `--cold`, `--whatsapp`, plus shadcn's variables mapped onto the existing ones so
  both systems paint the same colours in light and dark mode.
- **Contrast:** white text on the Pollux accent `#4AA0FF` fails WCAG AA, so primary buttons use
  `#1F6FD1` with white text and the accent stays for highlights, focus rings and the active nav item.
  The tenant's accent and logo come from the brand profile, so a second dealer looks like themselves.
- **Fonts:** Geist for Latin, IBM Plex Sans Arabic when `dir="rtl"`, both through `next/font`.
- **Component inventory** (`components/sales/`): `ConversationRow`, `ConversationList`,
  `MessageBubble` (one per message type), `VoiceNote`, `MessageStatusTicks`, `WindowBanner`,
  `Composer`, `TemplatePicker`, `QuickReplyMenu`, `VehiclePicker`, `DraftPanel`, `CustomerPanel`,
  `ProfileField`, `IdentityList`, `LeadCard`, `StageColumn`, `ScoreReasons`, `TaskRow`,
  `FollowUpCard`, `StatTile`, `RepTable`, `WaitingList`, `BriefCard`, `NotificationList`,
  `EmptyState`, `ErrorState` and the matching skeletons.

---

## 6. Language and direction

- Messages move from `lib/i18n.ts` into `messages/en.ts` and `messages/ar.ts`; the Arabic file uses
  `satisfies Record<MessageKey, string>`, so a missing translation fails `tsc`, not the user.
- `useT()` for client components; the existing cookie-based `setLocale` server action still sets
  `dir` on the first server render, so the layout never flips after paint.
- Customer content renders with `dir="auto"` per message — a French message inside an Arabic UI
  stays left to right.
- Prices, phone numbers, times, VINs and plate numbers render in `<span dir="ltr" class="tabular-nums">`
  inside Arabic text.
- Arabic is never letter-spaced (it breaks joining), and Arabic strings run about 25% longer than
  English, so buttons, badges and table headers wrap or truncate with a tooltip rather than clip.
- `check:rtl` is extended to catch `space-x-*` and to scan the new directories.

---

## 7. States, errors and offline

Every data view has three states: skeleton, a helpful empty state with the next action, and an error
state showing `problem.detail` with Retry. A dropped connection shows an offline banner.

> `ponytail:` no offline send queue. A message typed while offline fails with a Retry button rather
> than queuing in the browser. **Upgrade trigger:** salespeople report losing messages in poor
> coverage at the showroom. Then add a durable outbox in IndexedDB with idempotency keys.

---

## 8. Installable app and notifications

- `app/manifest.ts`, a service worker that caches only the shell and static assets — never API
  responses or customer data — and an offline fallback page.
- Install prompts: `beforeinstallprompt` on Android and desktop Chrome; a one-time explanation on iOS
  Safari, where notifications only work after the app is added to the Home Screen (iOS 16.4+).
- Web Push with VAPID: subscribe in Settings → Notifications, the subscription goes to
  `POST /v1/push-subscriptions`, and the worker sends. Per-type preferences are Phase 2; Phase 1
  sends assignment, waiting-too-long, task-due and hot-lead notifications.

---

## 9. Performance

- Virtualise the conversation list and the thread past 200 rows (`@tanstack/react-virtual`).
- Images lazy-load inside a fixed aspect ratio; signed URLs are refreshed by refetching the message,
  never by guessing expiry.
- `next/link` prefetch on hover for conversation rows; route-level code splitting keeps the inbox
  bundle free of settings and charts.
- Budget: inbox interactive under 2.5 s on a mid-range Android over 4G; a sent message appears
  optimistically in under 100 ms.

---

## 10. Accessibility

Labels on every icon-only button in both languages · visible focus · focus trapped and restored in
dialogs · the thread is `role="log"` with `aria-live="polite"` for incoming messages · colour is
never the only signal (response state and lead band carry text or an icon) · `prefers-reduced-motion`
respected · a keyboard map shown with `?`: J/K move, Enter opens, R replies, N internal note,
T template, A assign to me, E close, `/` quick replies, Alt+Enter sends the draft, G then I/P/T/D
jumps to Inbox, Pipeline, Tasks, Dashboard.

---

## 11. Tests

| Layer | What |
|---|---|
| Unit (Vitest) | Money and date formatting, relative times, the window countdown, edit-ratio maths, query-key builders |
| Component (Testing Library) | Composer refuses free text with a closed window and opens the template picker · draft panel records sent, edited and discarded · role-gated actions hidden · message bubble per type |
| End-to-end (Playwright) | Against the local stack with seeded data: sign in, inbox → reply using a draft → create a lead → move a stage → send a follow-up task → manager dashboard. Run as owner, manager and salesperson, in English and Arabic, at 360px and 1440px |
| Visibility | The end-to-end suite asserts a salesperson cannot see a colleague's customer, in the UI and by pasting the URL |
| CI | typecheck · `check:rtl` · lint · unit · component · end-to-end · OpenAPI drift |

No screenshot comparisons: fonts differ between a developer's Windows machine and CI, so a pixel
diff would measure the font stack, not the layout (the lesson from the creative templates in
DealerAI OS T3.5). Structural assertions instead.

---

## 12. Definition of done, per screen

1. Loading, empty and error states exist.
2. Usable at 360px, and the layout mirrors correctly in Arabic.
3. Actions the role lacks are hidden or disabled, and the API refuses them anyway.
4. Live updates arrive without a refresh.
5. Keyboard reachable; icon buttons labelled.
6. No direct `fetch`, no Supabase table access, every string in the catalogue, every type from
   `schema.ts`.
7. One end-to-end path through the screen is in the Playwright suite.
