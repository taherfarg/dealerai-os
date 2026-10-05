# Sales — the new look

The app works and is checked, and it looks like a first draft: text-only navigation, borders in
place of surfaces, messages with no bubble, the browser's own controls, a header that takes a fifth
of a phone. The owner asked for it to look modern before anybody outside sees it, and staging waits
for that.

This page says what the app will look like and how it gets there. It changes how things look and
where a few controls sit. It does not change what any screen does.

**Where it stands (2026-10-05):** the direction is chosen and this design is agreed. Steps 1 to 3
of §8 are built — the palette, the typeface and the corners on every screen, the shell around
them, and the inbox ([step 1](plans/ui-refresh.md#step-1-review--2026-10-05),
[step 2](plans/ui-refresh.md#step-2-review--2026-10-05),
[step 3](plans/ui-refresh.md#step-3-review--2026-10-05)). Steps 4 to 6 are not. The step-by-step
plan is [`plans/ui-refresh.md`](plans/ui-refresh.md), written one step at a time.

---

## 1. What has been decided

| Decision | Choice | Why |
|---|---|---|
| Direction | **B, "Messenger"**, out of three mocked up on one inbox ([the canvas](https://claude.ai/artifact/Firg3c1Vh1rM44xuV4ZWYm)) | The owner's choice. Chat first, familiar to a salesperson who lives in WhatsApp, and the AI draft sits where the reply will appear |
| How | **Restyle in place** | Every screen keeps its structure, its words and its behaviour, so the 65 end-to-end tests and 347 unit tests go on proving that nothing broke |
| Component library | **None** | [07](07-frontend.md) §5 once planned shadcn/ui. It would mean new dependencies, rewriting the controls of 95 files and doing Part C's accessibility pass again, for a look that a few shared styles reach |
| New packages | **None** | The font comes through `next/font`, which Next already has. Icons are one file of our own |
| Scope | **The shell and every Sales screen**; Inventory, Approvals, Command Center and Content take the new colours, font and shell and are not redesigned | The pilot uses the Sales screens |
| Arabic and dark mode | **Part of every step**, not a pass at the end | Both exist today, and a look that only works in English and in daylight is not finished |

Not in this work: new features, new pages, keyboard shortcuts, a colour per dealership.

---

## 2. What does not change

The tests find things the way a person does, and the refresh keeps every one of those handles.

- **Roles and names.** Every control keeps its role and its name from the catalogue: the
  navigation called *Main*, the inbox tabs, the three search boxes, the *AI draft* region, the
  *Messages* log, every button, checkbox, select and dialog. A button that becomes an icon keeps its
  words as its accessible name.
- **Hooks.** `li[data-sla]`, `li[data-kind]`, `[data-thread]`, `[data-customer-panel]`,
  `section[data-stage]`, `li[data-lead]`, `li[data-task]`, `li[data-band]`.
- **Structure a screen reader relies on.** One `h1` a page, one name a landmark, the skip link,
  `aria-current` on the navigation, dialogs as `<dialog>` through `components/Modal.tsx`.
- **The rules of [07](07-frontend.md) §6.** Logical CSS only (`check:rtl` scans `.css` too), `Auto`,
  `Ltr` and `Sentence` where they are, gaps on the parent, no letter-spacing in Arabic.
- **Native controls.** A select stays a `<select>`, a date a date input, a checkbox a checkbox. They
  are styled, not replaced.
- **Classes a unit test names:** `tabular-nums`, `[unicode-bidi:plaintext]`, `truncate`, the inbox
  heading's `sr-only`, the back arrow's `rtl:-scale-x-100`, `min-w-24`, the sheet's `h-dvh`. One
  changes with its reason: the quiet text inside a sent bubble was `text-black/70` because the
  bubble was gold; on green it is white, and its test says so.

---

## 3. The foundation

Today `globals.css` holds nine colours and the 95 page and component files hold the rest by hand:
about 290 colours written outside the tokens (`border-black/10 dark:border-white/15`,
`text-red-600 dark:text-red-400`), and the same few buttons and fields written out about a hundred
times. The foundation puts every colour behind a name and every repeated control behind one class,
so that the look is changed in one file.

### 3.1 Colours

Each is a CSS variable in `globals.css`, mapped into Tailwind in `@theme`, with a value for light
and for dark (`prefers-color-scheme`, as now).

| Token | Light | Dark | What it is |
|---|---|---|---|
| `ground` | `#edf3ef` | `#0c1210` | The app's canvas: the page behind everything, and the conversation's background |
| `background` | `#ffffff` | `#141c18` | Panels, cards, fields, a customer's bubble |
| `surface` | `#f1f5f2` | `#1c2620` | A soft fill: search fields, quiet buttons, hover |
| `border` | `#e1e8e3` | `#27332c` | Hairlines |
| `border-strong` | `#cfd9d2` | `#35443b` | The outline of a control |
| `foreground` | `#14201a` | `#e8efe9` | Text |
| `muted` | `#53615a` | `#9fb0a6` | Secondary text |
| `accent` | `#0f7a55` | `#0f7a55` | A filled primary button, a sent bubble, an unread count, the chosen tab |
| `on-accent` | `#ffffff` | `#ffffff` | Text on `accent` |
| `accent-ink` | `#0b5c40` | `#6fdcb3` | Green text and icons on a plain surface |
| `accent-soft` | `#dff3e8` | `#12382b` | The chosen row, the chosen navigation item, a "high confidence" pill |
| `danger` / `danger-soft` | `#a51d12` / `#fde7e4` | `#ff9d94` / `#3b1512` | A missed target, an error, a refusal |
| `warning` / `warning-soft` | `#7a4a00` / `#fff0cf` | `#f5c873` / `#3a2a08` | Waiting, due soon, an internal note |
| `info` / `info-soft` | `#0c4a80` / `#d7ebff` | `#9ccbf5` / `#0e2a44` | A neutral notice, a cold lead |
| `hot` / `hot-soft` | `#8a3b0c` / `#ffe2cf` | `#ffb48a` / `#3d1d0a` | A hot lead |

`success` stays as a name and is the accent's green. `brand` goes with the navy, and the old gold
with it: what used them is renamed in the same pass that names everything else.

Every pair above that carries text was worked out before it was chosen: text on its own soft fill
is 6:1 or better in both modes, white on `accent` is 5.3:1, `muted` is 5.8:1 on `ground`. The
accessibility sweep is the judge, not this table (§7).

### 3.2 Type

**Readex Pro**, one family for Latin and Arabic, loaded with `next/font/google` (`latin` and
`arabic` subsets, variable weight) from `app/fonts.ts` and set on `<html>` as a variable. Next
fetches it when it builds and serves it from the app's own address, so a browser never asks Google
for anything. The rule that gave Arabic a different family goes; the rule that gives it more
leading stays.

A message is read at 16 px on a phone and 15 px on a desk. Lists are 14 to 15 px. Nothing is
smaller than 11 px, and nothing in Arabic smaller than 12.

### 3.3 Shape and depth

Controls are pills. Cards and panels have an 18 px corner, a bubble 22 px with one tight corner on
the side it speaks from, written with logical corners so it turns with the language. Depth comes
from the ground showing between white panels, with one soft shadow kept for things that float: the
phone's navigation bar, a dialog, a menu.

### 3.4 Shared classes

In `globals.css`, in the components layer, so a utility on the same element still wins:

| Class | What it is |
|---|---|
| `btn`, with `btn-primary`, `btn-quiet`, `btn-danger` | A button, 44 px to press. Outlined by default |
| `icon-btn` | A round 44 px button that holds one icon and has a name |
| `field` | A text input, a select with its own chevron, a date input, a textarea |
| `pill`, with `pill-danger`, `pill-warning`, `pill-info`, `pill-accent`, `pill-hot` | A state said in a word, with its soft fill |
| `badge` | A count |
| `card` | A white panel with the 18 px corner |

These are classes and not React components on purpose: a `<Button>` wrapper would be one more
thing every file has to import to draw what CSS already draws.

### 3.5 Icons

`components/Icon.tsx`: one component and a table of about thirty drawings (stroke, 24 px grid,
`currentColor`), named by what they mean in this app: the nine destinations and the two marketing
ones, bell, search, send, the AI's spark, clock, alert, pencil, close, note, person, chevrons,
back, check, plus, language, sign out. An icon is always `aria-hidden`; the control it sits in has
the name. An icon that points — back, a chevron — is mirrored in Arabic.

No emoji draws an icon any more. The bell was one.

### 3.6 Avatars

`components/Avatar.tsx`: a circle with a person's initials in one of seven tints, chosen from the
name so the same person is always the same colour.

- A Latin name gives two letters, the first of the first word and of the last. An Arabic name gives
  one: two Arabic initials join and read as the start of a word.
- No name gives the person icon.
- A customer's flag stays, as a small badge on the avatar's corner. On a system with no flag
  pictures (Windows) it shows the country's two letters, which is what it shows today, in a place
  where that looks deliberate. `CustomerName` stops drawing the flag wherever an avatar is beside it.

The tints (`fill` / `ink`, light then dark): `#ffe2cf` / `#8a3b0c` and `#4a2410` / `#ffc9a6`;
`#e6defc` / `#4a2f9e` and `#2e2460` / `#cfc4ff`; `#d7ebff` / `#0c4a80` and `#10304f` / `#b5d8ff`;
`#ffdfe6` / `#8f1f3c` and `#4d1626` / `#ffc2d0`; `#d9f2e4` / `#0b5c40` and `#12382b` / `#9fe6c5`;
`#fdefc4` / `#6e4a00` and `#40300a` / `#f7dc8f`; `#dcf1f4` / `#0e5560` and `#0f3840` / `#a9e3ec`.

---

## 4. The shell

**On a desk:** a white rail, 88 px wide, on the side the language starts from. The mark at the top;
the destinations as an icon over a small label, the chosen one on `accent-soft`; a hairline, then
the two marketing ones; at the foot *Taking chats*, the bell, and the person's own avatar. The
approvals count stays on its icon. The rail scrolls if a window is too short for it.

**On a phone:** one row at the top, 52 px, in place of today's three: the mark and the workspace's
name, the bell, the avatar. At the bottom, the five destinations as a floating bar of icons with
labels, clear of the edge, the chosen one on `accent-soft`.

**The account menu.** The avatar opens a dialog (a sheet on a phone) holding what used to be spread
over the sidebar: the person's name, the language, the workspace switcher, *Taking chats* on a
phone (where today it is only on My day), and *Sign out*, which today is only in Settings and
stays there too. *Taking chats* stays in the rail on a desk, because a salesperson uses it several
times a day.

The skip link and the two navigations with one name stay as they are.

---

## 5. The screens

### 5.1 Inbox

The inbox fills the window: the list and the conversation are full-height panels, with no page
margin around them.

- **The list.** Tabs as pills with their counts, the chosen one filled. A search field as a soft
  pill. Each row: the avatar, the name and the age, one line of what was said, then the waiting
  pill, who has it, and the unread count. The chosen row sits on `accent-soft`.
- **The waiting pill** is `WaitingTimer` as a pill: an icon, the word, the time. Its three states
  keep three looks: plain while the customer is within the target, `warning` when the target is
  near, `danger` when it is missed. (The mock-up drew plain waiting in amber; that was the mock-up's
  mistake.) After the first minute it counts in minutes — "Missed 29m", not "Missed 29m 4s"; it
  only refreshes every thirty seconds anyway. `formatDuration` itself is unchanged, because the
  dashboard's medians want their seconds.
- **The conversation's header.** Back (on a phone), the avatar, the name as the `h1`, and under it
  who has it and the window. The waiting pill at the end, then *Assign to me*, *Customer* and
  *Close*. On a phone those three are icon buttons that keep their words as their names.
- **The lead strip.** If the customer has an open lead, one line under the header says so: the car,
  the stage, the band, the price. It is a button that opens the customer panel, and reads from the
  same request the panel makes. No open lead, no strip.
- **Messages.** On `ground`. The customer's are white, ours are `accent` with white text, a note
  is `warning-soft` with its label, an event is a centred line. Quiet text inside our bubble is
  white and small. Ticks and retry are where they are. One of ours that failed is `danger-soft`,
  not green: its *Not delivered* line is red, red on the green cannot be read, and a message that
  failed must never pass for one that went.
- **The AI draft.** Still a region of its own between the messages and the composer, always in
  view, and never inside the log. It is drawn as a bubble on our side with a dashed `accent`
  outline: not sent yet. Label, confidence and intent on top, the text, *Based on* with its sources
  as chips, and the actions under it with *Send draft* filled and nearest the thumb. A blocked draft
  says why in `danger`, as now.
- **The composer.** *Internal note* as a pill that shows when it is on, the text field as a soft
  pill, *Send* as a round `accent` button. Quick replies and templates keep their buttons.
- **The customer panel.** A column beside the conversation on a desk, a sheet on a phone, opened by
  *Customer* exactly as now. Inside: the avatar and name, the country said as a word
  (`Intl.DisplayNames`, in the reader's language), what we know as a quiet list with an *AI* mark
  on what the model found, the open lead as a card, tasks, and the link to the full record.

### 5.2 Customers, Pipeline, Tasks, My day

Each is a column of content on `ground`, with white cards.

- **Customers.** The search pill, then rows with avatars in one card. A customer's own page: a
  header card with the avatar, name and actions, tabs as pills, the timeline as a quiet list.
- **Pipeline.** Each stage a soft column with its name and count, each lead a white card: the car,
  the customer with their avatar, the price, the band as a pill. *Move to* stays a select. On a
  phone the columns scroll sideways as they do now.
- **Tasks and My day.** A task is a row in a card with its checkbox (the browser's own, in
  `accent`), its title, its due time as a pill when late. A follow-up card shows its drafted message
  the way the inbox shows a draft. *Add a task* keeps its fields, as `field`s.

### 5.3 Dashboard, Settings, sign-in

- **Dashboard.** Stat tiles as cards with the number large; the team table in a card that scrolls
  inside itself on a phone; the waiting list with avatars and waiting pills; the brief as a card.
- **Settings.** The sections as a list of cards, each form in a card, with `field`s and `btn`s.
- **Sign-in, sign-up, onboarding, the invitation, the two password pages.** One white card centred
  on `ground`, the mark above it, the language toggle in the corner.

### 5.4 Dialogs and states

A dialog has the 22 px corner and the floating shadow; on a phone it is a sheet, as now. Empty,
loading and failed states become one pattern: an icon, one sentence from the catalogue, and the
action if there is one.

---

## 6. Arabic and dark mode

Nothing here is new machinery. The rail is a grid column, so it moves to the right in Arabic by
itself. Bubbles use logical corners. The select's chevron is the one place CSS has no logical word
(`background-position`), so it has one `[dir="rtl"]` rule.

Dark mode is the second column of §3.1. `accent` is the same green in both, because white text on
it has to stay readable; what changes is `accent-ink`, the green used as text.

---

## 7. How it is checked

| What | With |
|---|---|
| Nothing that worked stopped working | `npm run check:web` (types, `check:rtl`, lint, 347 unit tests) and `npm run e2e` (65 tests, both languages, 360 px and 1440 px) after every step |
| Contrast, names, landmarks | The axe sweep inside the suite: 23 states at two widths. It gains one run in dark mode at 1440 px, because dark is where a contrast mistake hides and nothing checks it today |
| The new pieces | Unit tests for what has a rule: an avatar's initials and tint, the waiting pill's minutes |
| That it looks right | Screenshots of the running app after each step: a desk in English, a phone in Arabic, and dark. Shown to the owner |

---

## 8. The order

Each step is its own commits, and the app works after each.

1. **Foundation.** The names for every colour, the typeface, the corners. Every colour written by
   hand is replaced by its name in one pass, so the whole app changes colour and face at once and
   nothing is left on the old gold. Nothing moves.
2. **Shell.** The rail, the phone's top row and floating bar, the account menu — and with them
   what they are the first to be drawn with: `Icon`, `Avatar`, and the two classes a rail needs.
   (Planning step 1 found that nothing in it would use them.)
3. **Inbox.** List, conversation, lead strip, draft, composer, customer panel — and the canvas
   colour and the rest of the shared classes, because this is the first screen that puts white
   panels on mint. Each later screen moves onto the canvas as it is redrawn.
4. **Customers, Pipeline, Tasks, My day.**
5. **Dashboard, Settings, sign-in.**
6. **The pass.** Every screen in Arabic and in dark, the dark sweep, [07](07-frontend.md) §5
   rewritten to describe what exists, the full check.

---

## 9. What could go wrong

- **The lead strip says words the customer panel also says.** A test that looks for a car's name
  without saying where would find two. Such a test is narrowed to `[data-customer-panel]`; the strip
  is not removed to please it.
- **The font needs the network once.** Next fetches Readex Pro when it builds or first serves in
  development. Vercel and GitHub have it. A machine that does not would fail to build; the answer
  then is the font's files in the repository through `next/font/local` (its licence allows it).
- **Ninety-five files.** No step is finished until both suites pass, and the mechanical pass of
  step 1 is done by a script whose every change is read.
- **The marketing screens are not looked at one by one.** They are checked for one thing: that
  nothing on them became unreadable.
