# Sales — Screens

**Status:** Draft · **Depends on:** [06](06-api-contract.md), [07](07-frontend.md)

One section per screen: what it is for, its data, the layout on desktop and on a phone, its states,
and what must be true before it is done. Every screen also obeys the seven rules in
[07](07-frontend.md) §12, which are not repeated here.

---

## 1. Shell and navigation

**Route:** `app/[tenant]/layout.tsx` · **Who:** everyone

- **Desktop:** a sidebar (collapsible to an icon rail) with the workspace name, the navigation, a
  "Taking chats" switch, and the user menu (name, role, Arabic/English, sign out). A top bar holds
  the page title and the notifications bell.
- **Mobile:** a top bar plus a bottom navigation bar — Inbox, My day, Customers, Pipeline, More.
- **Navigation, role-gated:** Inbox (unread badge) · My day · Customers · Pipeline · Tasks ·
  Dashboard (`dashboard.manager`) · Inventory · Approvals · Settings, with Command Center and Content
  in a "Marketing" group.
- The "Taking chats" switch calls `PATCH /v1/me` and immediately affects assignment.

**Done when:** switching to Arabic mirrors the whole shell with nothing clipped; the bottom bar works
at 360px; the unread badge updates live without a refresh.

---

## 2. Inbox — conversation list

**Route:** `app/[tenant]/inbox` · **Data:** `GET /v1/conversations`, `GET /v1/conversations/counts`

- **Tabs by scope:** salespeople see Mine and Unassigned; managers add Team; owners, admins and
  viewers add All. Counts come from the counts endpoint. The current view is in the URL.
- **Filters:** status (open by default), channel when there is more than one, and search across
  names, numbers and message text including voice transcripts.
- **Row:** avatar with a channel badge · name and country flag · last message preview (with a mic
  icon and duration for voice, "You:" for our messages, a phone icon for phone-app replies) ·
  relative time · unread badge · assignee avatar or an "Unassigned" chip · the waiting timer
  ("Waiting 12m", amber when due soon, red when missed) · a sparkle when a draft is ready · a flame
  when the customer's lead is hot.
- **Order** comes from the API: customers waiting on us first, oldest first, then latest activity.
- Infinite scroll; J/K to move, Enter to open; a new message re-sorts the row with a brief highlight.

**Done when:** a message that arrives while the list is open moves the row and increments the unread
count without a refresh; a salesperson sees no conversation belonging to a colleague.

---

## 3. Inbox — conversation thread

**Route:** `app/[tenant]/inbox/[conversationId]` · **Data:** `GET /v1/conversations/{id}`,
`GET .../messages`, `POST .../read`

- **Header:** back (mobile) · customer name and number · channel · assignment control · Close,
  Reopen, Mark as spam · the window indicator ("Window open · 18h left" or "Window closed ·
  templates only"). Salespeople get "Assign to me" on unassigned conversations; managers get the
  full member list.
- **Summary bar** under the header when one exists: what the customer wants, where it stands, the
  next step.
- **Messages:** newest at the bottom, older loaded upwards, date separators, consecutive messages
  grouped within five minutes. Every type from [06](06-api-contract.md) renders: text, image with a
  lightbox, voice note with a player and its transcript, video, document, location with a maps link,
  sticker, template (labelled), button reply, car card, and an honest placeholder for unsupported
  types.
- **Ours** show delivery ticks, the author's name, "Sent from phone" for phone-app replies, and a
  red "Not delivered" with Retry on failure. **Internal notes** are a yellow full-width card that can
  never be mistaken for a sent message. **Events** are centred grey lines. Imported history sits
  under a divider.
- `?message={id}` scrolls to a message and highlights it — used by score reasons and profile
  evidence.

**Done when:** an Arabic conversation mirrors correctly including the voice player; a 200-message
thread scrolls smoothly on a phone; opening the thread marks it read for that user only.

---

## 4. Composer and AI draft panel

**Part of:** the thread · **Data:** `POST .../messages`, `.../notes`, `/v1/quick-replies`,
`/v1/channels/{id}/templates`, `/v1/vehicles`, `GET .../suggestion`, `POST /v1/suggestions/{id}/outcome`

- **Open window:** auto-growing text area, attachments, `/` for quick replies in the conversation's
  language, a car-card picker, a template button, and an internal-note toggle that turns the whole
  composer yellow.
- **Closed window:** free text disabled with an explanation, and a template picker whose variables
  are prefilled from the customer and car, with a live preview and a "Paid message" hint on
  marketing templates.
- **Draft panel** above the composer: the draft text, a High/Medium/Low confidence badge, the intent,
  a "Based on" row of car and document chips, an amber callout when a person must decide, and action
  chips (Create lead, Move to Negotiation, Follow up Thursday). Buttons: Send, Edit, Regenerate,
  Dismiss with a reason. Blocked drafts show one muted line with the reason; superseded drafts
  disappear.
- The panel never sends by itself. Alt+Enter sends, the panel collapses, and the collapsed state is
  remembered per browser.

**Done when:** sending a draft records the outcome and stops the waiting timer; editing before
sending records "edited"; a closed window makes a template the only path; an echo arriving while
typing shows "A reply was just sent from the phone".

---

## 5. Customer panel

**Part of:** the thread (a sheet on mobile) · **Data:** `GET /v1/customers/{id}`, `PATCH`,
`/v1/leads`, `/v1/tasks`

Header with name, number, country, owner and tags. Then "What we know": interest, budget, local or
export, destination, timeline, payment, trade-in, objections — each value marked as set by the AI
(clicking the marker jumps to the message it came from) or by a person, each editable inline, which
makes it a person's. Then the open lead (car, stage select, band, score, next action) or a Create
lead button, the open tasks with quick complete, and a link to the full profile.

**Done when:** editing an AI value changes its marker; the evidence link highlights the right
message; a salesperson without `contacts.reassign` sees the owner but no Reassign button.

---

## 6. Customer 360

**Route:** `app/[tenant]/customers/[contactId]` · **Data:** `GET /v1/customers/{id}`, `/timeline`,
`reassign`, `merge`

Header with identities (WhatsApp, phone, email, Instagram), owner, tags, and a red chip when the
customer has opted out. Tabs: **Timeline** (every channel merged, notes and events included),
**Leads** (open and closed, opening the lead drawer), **Tasks**, **Profile** (the full editor).
Actions: Message, Reassign, Merge.

**Merge dialog:** search the other record, compare identities, owner, leads and last activity side by
side, choose which to keep, confirm an irreversible move. **Reassign dialog:** pick a person, see
their open conversation count and availability, and read exactly what moves.

**Done when:** a merged customer's old URL explains what happened; reassigning moves conversations,
leads and tasks and leaves an event line in each conversation.

---

## 7. Customers list

**Route:** `app/[tenant]/customers` · **Data:** `GET /v1/customers`

A table on desktop, cards on a phone: name, number, country, language, owner, band, tags, last seen.
Filters in the URL: search, owner (managers and above), band, country, tag. Row selection with bulk
reassign. Empty state explains that customers appear automatically from WhatsApp.

**Done when:** filters survive a reload and a shared link; bulk reassign shows what will move and
updates the inbox.

---

## 8. Pipeline board and lead drawer

**Route:** `app/[tenant]/pipeline` · **Data:** `GET /v1/pipelines`, `/v1/leads`, `PATCH /v1/leads/{id}`

Pipeline switcher (Local sale, Export), board or list view, filters for band, owner and search. Each
column shows its stage, lead count and total value. Cards carry the customer, car, budget, band and
score, owner, next action and days in stage. Dragging moves a lead; Won and Lost are collapsed drop
zones, and Lost requires a reason. Every card also has a "Move to…" menu, so dragging is never the
only way. On a phone, columns snap one per screen.

**Lead drawer (`?lead=`):** the car, stage, owner, band and score; "Why this score" listing each
signal, its points and a link to the message that proves it; budget, source, created date, the
conversation link, stage history, tasks, and the lost reason when lost.

**Done when:** a stage move survives a reload, writes history and shows in the conversation; score
reasons link to the right messages; the board is usable with the keyboard.

---

## 9. Tasks

**Route:** `app/[tenant]/tasks` · **Data:** `GET /v1/tasks`, `POST`, `PATCH`, `POST .../send-draft`

Tabs: Overdue (red), Today, Upcoming, Done, with a Mine/Team switch for managers. Rows: complete
checkbox with an Undo toast, title, kind icon, customer link, due time, assignee (Team view) and an
"AI" badge for generated follow-ups. Snooze offers an hour, tomorrow morning or next week.

**AI follow-up card:** the reason in bold ("BYD Seal 05 dropped AED 4,000 since they asked"), the
draft, and Send now, Edit in conversation, or Skip with a reason. When the window is closed it says so
and sends the approved template instead.

**Done when:** Send now delivers the message in the conversation and completes the task in one tap;
snoozing moves the task between tabs; a salesperson sees only their own tasks.

---

## 10. My day

**Route:** `app/[tenant]/today` · **Data:** `GET /v1/dashboard/me`

A greeting, three numbers (replied today, my median first response, the Taking chats switch), then
"Waiting on you" (oldest first), "Due today", and "Hot leads". One column on a phone, two on desktop.

**Done when:** every section links to the thread, task or lead behind it, and updates live.

---

## 11. Manager dashboard

**Route:** `app/[tenant]/dashboard` · **Data:** `GET /v1/dashboard/manager`, `GET /v1/brief/today`

- The **daily brief** at the top: a headline and up to five items, each linking to what it is about.
- **Tiles:** new conversations, waiting now, median first response (green, amber or red against the
  target), missed targets, new leads, hot leads, won, lost — each opening the matching filtered list.
- **Waiting now:** the oldest waiting conversations with Open and Reassign.
- **Team table:** per salesperson — open, waiting, median first response, missed targets, overdue
  tasks, leads by band, won this month. Clicking a person opens their waiting conversations and
  overdue tasks.
- **Pipeline** totals per stage, **lead sources**, and the **inbox-versus-phone share** with the line
  "Replies typed on the phone skip AI drafts and response tracking."
- Non-managers get a short "This page is for managers" with a link to My day.

**Done when:** every number is traceable to rows behind it; reassigning from here changes the inbox;
tiles wrap two per row on a phone and the team table becomes cards.

---

## 12. Notifications

**Part of:** the shell · **Data:** `GET /v1/notifications`, `POST /v1/notifications/read`

Bell with an unread count; a popover on desktop, a full-screen sheet on mobile; newest first with an
icon per kind; clicking opens the target and marks it read; "Mark all as read". Toasts for missed
response targets, new assignments and newly hot leads, with a Do-not-disturb switch stored locally.

---

## 13. Settings

**Route:** `app/[tenant]/settings/*` · Sections hidden when the role lacks the permission.

| Section | Contents |
|---|---|
| **Channels** (`settings.channels`) | Channel cards with status, quality and mode; the history-sync progress bar with its phase; Connect WhatsApp as a three-step dialog that states plainly what coexistence keeps and what it costs; the template list with statuses and rejection reasons; after an import, "Assign imported customers" with bulk assignment |
| **Team and roles** (`settings.team`) | Members with role, teams, languages and availability; invitations; a "Who sees what" explainer; the last owner cannot be removed |
| **Routing and response targets** (`settings.routing`) | Business hours per day, the first-response target, the unassigned-queue switch, ordered routing rules with a plain-language preview, and a sticky Save bar |
| **Pipelines** (`pipeline.edit_stages`) | Stage editor per pipeline with names, categories and order; deleting a stage that holds leads is refused with the count |
| **Quick replies** (`settings.quick_replies`) | Shortcut, title and one body per language, with a `{name}` hint |
| **Knowledge** (`settings.knowledge`) | Upload PDF, DOCX or TXT; processing status and chunk count; the line "Prices and stock always come from Inventory, never from documents" |
| **AI assistant** (`settings.ai`) | Drafts on or off, the Arabic register, follow-up timing, the read-only list of what the AI never does, and last month's draft acceptance |
| **Notifications** (everyone) | Enable push, per-device list, a test notification, and the iOS Home Screen note; Install the app where the browser offers it |

**Sign out** sits at the end of the sections, on a phone and on a desk. It stops this device's
notifications before it ends the session.

**Done when:** every save shows its effect (routing changes where the next conversation lands, the
target changes when timers turn amber); a salesperson sees only Quick replies, read-only, and
Notifications.

---

## 14. Sign-in and joining

**Routes:** `app/(auth)/login`, `accept-invite`

Email and password (and Google) through Supabase Auth, the invitation flow from DealerAI OS T1.2, and
a first-run screen for an owner with no workspace. The error message never reveals whether an email
exists.

**Done when:** a real sign-in works end to end — the gap recorded in the DealerAI OS README — and an
invited salesperson lands in the inbox with the right scope.

---

## 15. Screen build order

Grouped so that each step is demonstrable on its own:

1. Shell, sign-in, tokens, states (§1, §14)
2. Inbox list and thread, read-only (§2, §3)
3. Composer, then the draft panel (§4)
4. Customer panel, Customer 360, customers list (§5–§7)
5. Pipeline board and lead drawer (§8)
6. Tasks and My day (§9, §10)
7. Manager dashboard and notifications (§11, §12)
8. Settings (§13)
9. Installable app, push, accessibility and Arabic pass (§1–§13 revisited)
