# Sales — Frontend

**Status:** Draft · **Depends on:** [01](01-architecture.md) §2, [06](06-api-contract.md), DealerAI OS [08](../08-folder-structure.md) §2

---

## 1. What exists today

`apps/web` is Next.js 16.3.8 (App Router), React 19.2, TypeScript strict, Tailwind v4 with tokens in
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

Desktop uses a rail of icons and multi-pane layouts; a phone has a bar floating at the bottom and
moves from list to detail as separate screens (§5). The `[tenant]` segment stays in the URL so a pasted link opens
the same workspace for whoever clicks it.

---

## 5. UI system

What the app is drawn with. Why it looks the way it does is [11 — the new look](11-ui-refresh.md);
this is what exists.

- **Every colour has a name** in `app/globals.css`, with one value for light and one for dark,
  mapped into Tailwind in `@theme inline`: the canvas (`ground`), panels (`background`), the soft
  fill (`surface`), two borders, text and its quieter kind, the accent with what is written on it
  and its two relatives (`accent-ink`, `accent-soft`), four states each with a soft fill
  (`danger`, `warning`, `info`, `hot`), and seven tints for avatars. A component never writes a
  colour of its own. Dark mode is not a second class beside the first: the name carries both.
- **Three things hold that.** `app/palette.test.ts` reads `globals.css` and fails if a pair that
  carries text is under 4.5 to 1 in either mode, if a name has one value and not the other, or if
  a name is not mapped (its classes would paint nothing, silently). `npm run check:colours`, in
  `npm run check` and in CI, refuses a colour written by hand; one is allowed, the black that dims
  the page behind a dialog. And the end-to-end sweep runs once more with the device set to dark.
- **One typeface**, Readex Pro, for Latin and Arabic, through `next/font/google` in `app/fonts.ts`
  — a file of its own, so that nothing a test imports reaches `next/font`. Next fetches it when it
  builds and serves it from the app's own address. Arabic keeps its extra leading, and is never
  letter-spaced (§6).
- **Shared classes**, in the components layer of `globals.css` so that a utility on the same
  element still wins: `btn` with `btn-primary`, `btn-quiet`, `btn-danger`; `icon-btn`; `field`
  with `field-soft`; `pill` with `pill-danger`, `pill-warning`, `pill-info`, `pill-accent`,
  `pill-hot`; `badge`. Classes and not React components: a `<Button>` would be one more thing
  every file imports to draw what CSS already draws.
- **`components/Icon.tsx`**: every drawing, in one table, named by what it means here. Always
  hidden from a screen reader — the control an icon sits in has the name. One that points is
  mirrored in Arabic by a wrapper with `rtl:-scale-x-100`.
- **`components/Avatar.tsx`**, on `lib/avatar.ts`: a person's initials on a tint chosen from their
  name, so the same person is always the same colour; one letter for an Arabic name, because two
  would join. A customer's flag rides on its corner, and `CustomerName` is given no country
  wherever an avatar is beside it.
- **The frame** is `components/Shell.tsx`: one `<aside>` that is a rail down the side of a desk
  and a row across the top of a phone, the phone's floating bar, and the account menu
  (`AccountMenu.tsx`) with the language, the workspace and the way out. On a desk `<main>` is the
  canvas and each page sits on one white sheet. The inbox says `data-inbox` and gets no sheet; it
  fits the window, using `--shell-top`, which the shell sets to the height of its top row; and on
  a phone an open conversation (`[data-thread]`) has the whole screen.
- **A lead's band** is a pill said once, in `components/crm/band.ts`.

Not built: a colour per dealership; a `card` class (the sheet is one element and says its own
classes); keyboard shortcuts.

---

## 6. Language and direction

- Messages move from `lib/i18n.ts` into `messages/en.ts` and `messages/ar.ts`; the Arabic file uses
  `satisfies Record<MessageKey, string>`, so a missing translation fails `tsc`, not the user.
- `useT()` for client components; the existing cookie-based `setLocale` server action still sets
  `dir` on the first server render, so the layout never flips after paint.
- **What a person wrote keeps its own direction.** `components/Bidi.tsx` is where the rule lives:
  `Auto` (`dir="auto"`) for a message, a name, a title — on the element that truncates, so a Latin
  name in an Arabic line loses its end and not its beginning; `Ltr` for what is a number — a phone
  number, a price, a score, an id — inline, so the number keeps its order without leaving the side
  of the page its line starts on; `CustomerName`, which keeps the flag outside the name (a flag is
  made of left-to-right characters and would turn an Arabic name left to right).
- **Two things side by side get a gap on their parent**, never a margin on one of them: an element
  with a direction of its own has its own idea of which side is the start. `check:rtl` refuses
  `space-x-*` for the same reason, and tests its own patterns before trusting them.
- **Times are words, not numbers.** A duration, an age, a due time and a date are said by
  `lib/format.ts` in the reader's language — every formatter takes the language as a required
  argument — and flow with their sentence. Wrapping one in `dir="ltr"` puts its parts in the wrong
  order ("د 38" for "38 د"), which is what Parts A and B did to their dates.
- **A stored code is said as a word.** `lib/words.ts`: a channel's status, a template's category, a
  lead's source, a score's signals, why a draft was held back, what the thread says about itself,
  and counts in Arabic's own forms. A code with no word yet is shown as it is, never as a blank.
- **The server learns the language twice** ([06](06-api-contract.md) §1, §2): per request, from
  `Accept-Language`, for what it refuses; and per person, in `profiles.locale`, for what it writes
  when nobody is there to ask — a notification and its push. A sentence written that way may begin
  with a name in another script, so the server wraps names in Unicode isolates and the bell reads
  them with `unicode-bidi: plaintext`, which looks past isolates where `dir="auto"` does not.
- Arabic is never letter-spaced (it breaks joining) — one rule in `globals.css` — and Arabic
  strings run about 25% longer than English, so buttons, badges and table headers wrap or truncate
  rather than clip.
- **Not translated:** what the model writes for the team (a draft's "needs a person" line, action
  chips, the summary, a follow-up's reason) is English by S4's design; stage, team and pipeline
  names are the dealership's own words.

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

Labels on every icon-only button in both languages · one visible focus ring, the accent's
(`:focus-visible` in `globals.css`) · a dialog is a `<dialog>` opened with `showModal()` through
`components/Modal.tsx`, so focus moves in, Tab stays inside, Escape closes and focus returns to
whatever opened it — the customer panel and the lead drawer are dialogs wherever they cover the
screen · the thread's messages sit in a `role="log"` wrapper, `aria-live="polite"` · one `h1` on
every page and one name per landmark, with a skip link past the navigation · colour is never the
only signal (response state and lead band carry text or an icon) · `prefers-reduced-motion`
respected, in CSS and in the one animation started from script · controls are 44 px to press, bar
a link inside a sentence.

Checked with `axe-core` (already installed, under the lint config) over 40 states in each language
at 375 px, and by a walk with the keyboard alone; the scripts and the numbers are in the
[Part C review](plans/s7-pilot-readiness.md#part-c-review--2026-10-03).

Not built: the keyboard map (`?`, J/K, R, N, G then I…). Everything is reachable with Tab, Enter,
Escape and the arrows; shortcuts are for somebody who works the inbox from a desk all day.

---

## 11. Tests

| Layer | What |
|---|---|
| Unit (Vitest) | Money and date formatting, relative times, the window countdown, edit-ratio maths, query-key builders |
| Component (Testing Library) | Composer refuses free text with a closed window and opens the template picker · draft panel records sent, edited and discarded · role-gated actions hidden · message bubble per type |
| End-to-end (Playwright) | `apps/web/e2e`, against a stack of its own with seeded data. The day's work — sign in, inbox → reply using a draft → create a lead → move a stage → send a follow-up task → manager dashboard — as owner, manager and salesperson, in English and Arabic, at 360px and 1440px. Then, in English on a desk and in Arabic on a phone: the shell, joining, a path through every other screen, and `axe-core`, one top heading and no sideways scroll on every page. And the checker once more, on a desk with the device set to dark |
| Visibility | The end-to-end suite asserts a salesperson cannot see a colleague's customer — in a list, in a search, and by pasting the URL of their conversation or their record |
| Live | Two people at once: what a salesperson does reaches a manager's open pages without a reload |
| CI | typecheck · `check:rtl` · lint · unit · component · end-to-end · OpenAPI drift |

No screenshot comparisons: fonts differ between a developer's Windows machine and CI, so a pixel
diff would measure the font stack, not the layout (the lesson from the creative templates in
DealerAI OS T3.5). Structural assertions instead.

**Running the end-to-end suite.** Docker up; `npx playwright install chromium`, once; no other
`next dev` in this checkout, because Next refuses a second; then `npm run e2e` — with
`E2E_DB_PORT=54432` on a machine where Windows has taken the usual port. It makes and migrates a
database of its own (`dealerai_e2e`), starts an API on :8100, the worker, and a development web
server on :3100, and puts the seeded workspace back before every test. So a run never empties a
workspace somebody is looking at, and — the model key being blank — never buys anything. The
stack's every setting is in `e2e/stack.ts`; CI's `e2e` job runs the same thing.

- **A development server, not a build**: the local sign-in is compiled out of a production build
  ([01](01-architecture.md) §7), and that lock is not loosened for a test.
- **The worker is in it**: a customer who has been answered is still waiting until the reply has
  actually been sent, and only the worker sends.
- **A test says what the app says**: it finds a control by its role and by the words in
  `messages/en.ts` and `ar.ts`, so one test runs in both languages and a change of wording does
  not break it. What has no words of its own has a `data-` hook (`data-lead`, `data-stage`,
  `data-task`, `data-kind`, `data-sla`).
- **An address typed in is waited for** (`arrive()`): the server draws a page before the browser
  has made it work, and a tab pressed in that gap does nothing.
- **Not in it**: a real sign-in (staging's, [10](10-staging.md) §7), Safari and Firefox, and what
  the worker does with a model.

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
