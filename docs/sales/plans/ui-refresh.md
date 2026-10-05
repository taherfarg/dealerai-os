# Sales — the new look Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** the app looks like direction B of [11](../11-ui-refresh.md) on every Sales screen, in
English and in Arabic, in light and in dark — and does exactly what it did before.

**How this plan is split.** [11](../11-ui-refresh.md) §8 is six steps that each leave a working
app, so this is six parts. Step 1 is planned in full below. Each later step is written when it is
reached, appended to this file under its own heading, with its own exit run — this project's
convention from [09](../09-implementation-plan.md).

| Step | What | Exit |
|---|---|---|
| **1** | Foundation: every colour behind a name, the typeface, the corners | No colour in the app is written by hand; the palette and the face are B's on every screen; nothing has moved; both suites pass |
| **2** | Shell: the rail, the phone's top row and floating bar, the account menu — with the icons, the avatar and the shared button styles they are drawn with | The frame of every page is B's, in both languages |
| **3** | Inbox: list, conversation, lead strip, draft, composer, customer panel | The mock-up, in the running app |
| **4** | Customers, Pipeline, Tasks, My day | |
| **5** | Dashboard, Settings, sign-in | |
| **6** | The pass: every screen in Arabic and in dark, the dark run of the sweep, [07](../07-frontend.md) §5 rewritten | Staging can go ahead |

---

# Step 1 — Foundation

**Goal:** after this step no page or component writes a colour of its own. Every one has a name in
`globals.css` with a value for light and a value for dark; the values are direction B's; the
typeface is Readex Pro in both languages; corners are softer. Nothing has moved, nothing has
changed size on purpose, and every test that passed still passes.

**How this step was planned.** By counting, and by a dry run.

| What was looked at | What it found |
|---|---|
| Every colour class in `apps/web/app` and `apps/web/components` | 311 written by hand, in about fifty spellings, across 59 files and one test. `border-black/10` alone is 35 of them, nearly every one with `dark:border-white/15` beside it |
| The 23 `text-black` and the 10 `text-white` | Every `text-black` sits on `bg-accent` (the gold), and every `text-white` on `bg-brand` (the navy) or on the one filled red button. So "black" and "white" here always meant "the text on the accent" |
| The pass itself, run without writing | 306 changes in 59 files, and one colour left by hand on purpose: the black that dims the page behind a dialog |
| The new palette's contrast, pair by pair, with WCAG's own arithmetic | The lowest is white on the accent at 5.34 to 1; everything else that carries text is above 5.3, in both modes |
| A message of ours that failed | Its *Not delivered* line is red, inside the sent bubble. On the gold that was 3.2 to 1; on the green it would be 1.4. Nothing seeds a failed message, so the sweep would never have seen it |
| The unit tests that name a class | One names a colour: `MessageBubble.test.tsx` expects `text-black/70` on a sent bubble |
| Next's own guide to fonts (`node_modules/next/dist/docs/…/font.md`) | `next/font/google`, a `variable`, and that variable's class on `<html>`. Readex Pro is in Next's list with `latin` and `arabic` subsets and a variable weight |
| What imports `app/layout.tsx` in a test | Nothing. `next/font` exists only inside Next's compiler, so it stays out of anything a test imports |
| Prettier's configuration | `printWidth` only: class order is not sorted by a tool, so a word is replaced where it stands |

Two findings changed the shape of the step.

**The shared classes, the icons and the avatar are not in it.** [11](../11-ui-refresh.md) §3.4 to
§3.6 describe them as part of the foundation, and nothing in this step would draw with them.
Each is written in the step that first uses it, which for all three is the shell. §8 of that page
is corrected with this plan.

**The canvas colour waits for the shell too.** `ground` is the mint behind white panels. Today's
pages draw straight onto the page, with no panels to sit on it, so the page stays `background`
until step 2 gives it a frame.

**Architecture:** three ideas.
(1) *A name for every colour, and a test that holds the names to their word* — eighteen variables
in `globals.css`, each with a light and a dark value, each mapped into Tailwind; and
`palette.test.ts`, which reads that file and fails if a pair that carries text drops under 4.5 to
1 in either mode. Dark mode stops being a second class written beside the first: the name carries
both.
(2) *A net, so it stays that way* — `npm run check:colours`, beside `check:rtl` and made the same
way, refuses a colour written by hand. It is red before the pass and green after it, and it is in
`npm run check` for every step that follows.
(3) *The pass is a script, run once and thrown away* — it says what it will change before it
changes it, each special case is written into it as a whole phrase with its reason, and what it
did is read as a diff before it is committed.

**Tech stack:** Tailwind 4 (`@theme`) · `next/font/google` (already part of Next) · vitest · Node.
No new package.

**Before you start:**

- `git status --short` shows nothing but `apps/web/AGENTS.md` and `apps/web/CLAUDE.md`. Anything
  else in the tree may be Codex's: ask before going on.
- Read `node_modules/next/dist/docs/01-app/03-api-reference/02-components/font.md`, the section
  *With Tailwind CSS*, before F2. `apps/web/AGENTS.md` asks for exactly this.
- For the suite (F4): Docker Desktop running and the database up. On this machine the container is
  on 54432, so the suite is run with `E2E_DB_PORT=54432`. **Stop any `next dev` in this checkout
  first** — Next 16 refuses a second one in the same folder.
- Commit by explicit path, each message ending with this session's `Co-Authored-By` line. Nothing
  is pushed unless asked for.

## What Step 1 does not build

| Item | Why, and when |
|---|---|
| `btn`, `field`, `pill`, `badge`, `card`; `Icon`; `Avatar` | Nothing here draws with them. Step 2, with the shell that does |
| `ground`, the canvas behind panels | It needs panels. Step 2 |
| Moving or reshaping anything | This step is colour, face and corner. A control is where it was. The hundred hand-written buttons keep their classes and change their colour words only |
| The dark run of the axe sweep | Step 6, as [11](../11-ui-refresh.md) §7 says. Until then dark is held by `palette.test.ts`, pair by pair |
| The font's files in the repository (`next/font/local`) | Only if a build ever has no network ([11](../11-ui-refresh.md) §9) |
| A colour per dealership | Not in this work at all ([11](../11-ui-refresh.md) §1) |

## File structure

| File | Responsibility |
|---|---|
| `apps/web/app/globals.css` | **Modify.** The eighteen names, light and dark; their Tailwind mapping; the focus ring; then the face and the corners |
| `apps/web/app/palette.test.ts` | **Create.** Every name has both values, every name is mapped, every pair can be read |
| `apps/web/scripts/check-colours.mjs` | **Create.** The net: no colour written by hand |
| `apps/web/package.json`, `.github/workflows/ci.yml` | **Modify.** `check:colours`; `check` runs it, and so does CI, which runs the pieces one by one |
| 59 files under `apps/web/app` and `apps/web/components` | **Modify,** by the pass: colour words only |
| `apps/web/components/inbox/MessageBubble.tsx`, `MessageBubble.test.tsx` | **Modify.** The one test that names a colour; and a message of ours that failed is no longer drawn green |
| `apps/web/components/inbox/WaitingTimer.tsx` | **Modify.** A comment that explained an old colour |
| `apps/web/app/fonts.ts` | **Create.** Readex Pro, as a CSS variable |
| `apps/web/app/layout.tsx` | **Modify.** That variable on `<html>` |
| `apps/web/app/manifest.ts`, `icon.tsx`, `apple-icon.tsx`, `manifest.test.ts` | **Modify.** The installed app's colour, held to the palette's by a test |
| `docs/sales/11-ui-refresh.md`, this file | **Modify.** Where it stands; the review |

---

## Task F1: Every colour behind a name

**Files:**
- Create: `apps/web/app/palette.test.ts`
- Create: `apps/web/scripts/check-colours.mjs`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/package.json`, `.github/workflows/ci.yml`
- Modify: 59 files under `apps/web/app` and `apps/web/components` (by the pass)
- Modify: `apps/web/components/inbox/MessageBubble.tsx`, `WaitingTimer.tsx` (by hand, after it)
- Test: `apps/web/components/inbox/MessageBubble.test.tsx`

One commit: the names, the values and the pass are one change. A palette that is green while
buttons still say `text-black` is black on green at 3.9 to 1, so there is no good place to stop
half way.

- [ ] **Step 1: Write the failing test** — `apps/web/app/palette.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// __dirname, not import.meta.url: under jsdom that is not a file: address.
const CSS = readFileSync(resolve(__dirname, "./globals.css"), "utf-8");
const DARK = "@media (prefers-color-scheme: dark)";

/** `--name: #rrggbb`, as written, by name. */
function values(css: string): Record<string, string> {
  return Object.fromEntries(
    [...css.matchAll(/--([a-z-]+):\s*(#[0-9a-f]{6})\b/g)].map(
      (found) => [found[1], found[2]] as const,
    ),
  );
}

const light = values(CSS.slice(0, CSS.indexOf(DARK)));
const dark = values(CSS.slice(CSS.indexOf(DARK), CSS.indexOf("@theme")));

/** WCAG 2's relative luminance of `#rrggbb`. */
function luminance(hex: string): number {
  const channel = (at: number) => {
    const part = parseInt(hex.slice(at, at + 2), 16) / 255;
    return part <= 0.03928 ? part / 12.92 : ((part + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(one: string, other: string): number {
  const a = luminance(one);
  const b = luminance(other);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/**
 * What is read, and what it is read on: every way the app puts them together.
 * A new pairing in a component is a new line here.
 */
const PAIRS: readonly (readonly [text: string, fill: string])[] = [
  ["foreground", "background"],
  ["foreground", "surface"],
  ["foreground", "accent-soft"],
  ["foreground", "warning-soft"],
  ["foreground", "info-soft"],
  ["foreground", "danger-soft"],
  ["muted", "background"],
  ["muted", "surface"],
  ["muted", "accent-soft"],
  ["muted", "warning-soft"],
  ["muted", "info-soft"],
  ["muted", "danger-soft"],
  ["on-accent", "accent"],
  ["accent-ink", "background"],
  ["accent-ink", "surface"],
  ["accent-ink", "accent-soft"],
  ["danger", "background"],
  ["danger", "surface"],
  ["danger", "danger-soft"],
  // A filled button that destroys, and the note switch when it is on.
  ["background", "danger"],
  ["background", "warning"],
  ["warning", "background"],
  ["warning", "surface"],
  ["warning", "warning-soft"],
  ["info", "background"],
  ["info", "surface"],
  ["info", "info-soft"],
  ["hot", "background"],
  ["hot", "hot-soft"],
];

/** The pairs somebody could not read, said so a person can fix them. */
function unreadable(mode: Record<string, string>): string[] {
  return PAIRS.flatMap(([text, fill]) => {
    if (!mode[text] || !mode[fill]) return [`${text} on ${fill}: no such name`];
    const ratio = contrast(mode[text], mode[fill]);
    return ratio < 4.5 ? [`${text} on ${fill}: ${ratio.toFixed(2)} to 1`] : [];
  });
}

describe("the palette", () => {
  it("gives every name a value in light and in dark", () => {
    expect(Object.keys(light).length).toBeGreaterThan(0);
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort());
  });

  it("maps every name into Tailwind, so its classes exist", () => {
    // A name with no `--color-` line makes classes that paint nothing, and say nothing.
    const unmapped = Object.keys(light).filter(
      (name) => !CSS.includes(`--color-${name}: var(--${name});`),
    );
    expect(unmapped).toEqual([]);
  });

  it("can be read in light", () => {
    expect(unreadable(light)).toEqual([]);
  });

  it("can be read in dark", () => {
    expect(unreadable(dark)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run, from `apps/web`: `npx vitest run app/palette.test.ts`
Expected: 2 failed, 2 passed. *can be read in light* and *can be read in dark* fail, and their
lists include `on-accent on accent: no such name`. The two others pass: today's nine names do have
both values and are mapped.

- [ ] **Step 3: The names** — in `apps/web/app/globals.css`, replace everything from `:root {`
  down to and including the `:focus-visible` rule (lines 10 to 64) with this. The first comment of
  the file, and the two rules after the focus ring, stay as they are.

```css
/*
 * Every colour has a name here, with one value for light and one for dark
 * ([11] § 3.1). No component writes a colour of its own: `npm run
 * check:colours` refuses it, and app/palette.test.ts holds every pair that
 * carries text to 4.5 to 1 in both.
 */
:root {
  /* The browser's own parts follow the mode too: a select's list, a date's
     calendar, a scrollbar. */
  color-scheme: light dark;

  --background: #ffffff;
  --surface: #f1f5f2;
  --border: #e1e8e3;
  --border-strong: #cfd9d2;
  --foreground: #14201a;
  --muted: #53615a;
  --accent: #0f7a55;
  --on-accent: #ffffff;
  --accent-ink: #0b5c40;
  --accent-soft: #dff3e8;
  --danger: #a51d12;
  --danger-soft: #fde7e4;
  --warning: #7a4a00;
  --warning-soft: #fff0cf;
  --info: #0c4a80;
  --info-soft: #d7ebff;
  --hot: #8a3b0c;
  --hot-soft: #ffe2cf;
}

@media (prefers-color-scheme: dark) {
  :root {
    --background: #141c18;
    --surface: #1c2620;
    --border: #27332c;
    --border-strong: #35443b;
    --foreground: #e8efe9;
    --muted: #9fb0a6;
    /* The same green in both: white has to stay readable on it. What changes
       is accent-ink, the green that is text. */
    --accent: #0f7a55;
    --on-accent: #ffffff;
    --accent-ink: #6fdcb3;
    --accent-soft: #12382b;
    --danger: #ff9d94;
    --danger-soft: #3b1512;
    --warning: #f5c873;
    --warning-soft: #3a2a08;
    --info: #9ccbf5;
    --info-soft: #0e2a44;
    --hot: #ffb48a;
    --hot-soft: #3d1d0a;
  }
}

@theme inline {
  --color-background: var(--background);
  --color-surface: var(--surface);
  --color-border: var(--border);
  --color-border-strong: var(--border-strong);
  --color-foreground: var(--foreground);
  --color-muted: var(--muted);
  --color-accent: var(--accent);
  --color-on-accent: var(--on-accent);
  --color-accent-ink: var(--accent-ink);
  --color-accent-soft: var(--accent-soft);
  --color-danger: var(--danger);
  --color-danger-soft: var(--danger-soft);
  --color-warning: var(--warning);
  --color-warning-soft: var(--warning-soft);
  --color-info: var(--info);
  --color-info-soft: var(--info-soft);
  --color-hot: var(--hot);
  --color-hot-soft: var(--hot-soft);
  /* What went well is said in the accent's own green. */
  --color-success: var(--accent-ink);
}

body {
  background: var(--background);
  color: var(--foreground);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}

/* Arabic needs a face that actually has the glyphs, and a little more leading. */
[dir="rtl"] body {
  font-family: "Segoe UI", "Noto Sans Arabic", "IBM Plex Sans Arabic", system-ui, sans-serif;
  line-height: 1.75;
}

/* One focus ring, the accent's, wherever the keyboard is ([07] § 10). */
:focus-visible {
  outline: 2px solid var(--accent-ink);
  outline-offset: 2px;
}
```

`brand` is gone with the navy. `success` is a name without a value of its own.

- [ ] **Step 4: Run the test again**

Run: `npx vitest run app/palette.test.ts`
Expected: 4 passed.

- [ ] **Step 5: The net** — `apps/web/scripts/check-colours.mjs`:

```js
/**
 * Fails if a component writes a colour by hand.
 *
 * Every colour in this app has a name in app/globals.css, with one value for
 * light and one for dark, and app/palette.test.ts holds each pair that carries
 * text to a contrast it can be read at. `text-red-600 dark:text-red-400` goes
 * round all of that: it looks right today, and it is exactly what a change of
 * palette leaves behind.
 *
 * The same idea as check-logical-css.mjs: a screenshot proves one page once.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

// fileURLToPath, not .pathname: the repo path contains a space.
const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SCAN = ["app", "components"];

const HUES =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
// The utilities that paint. `border-s-…` and its siblings colour one side.
const PAINTS =
  "bg|text|border(?:-[sebtxylr])?|ring|outline|divide|accent|fill|stroke|placeholder|from|to|via|shadow|decoration|caret";
// Black, white, a hue with its number, or a colour spelled out in brackets —
// with any variants in front (dark:, hover:) and any opacity behind.
const BY_HAND = new RegExp(
  `(?<![\\w-])(?:[a-z-]+:)*(?:${PAINTS})-(?:black|white|(?:${HUES})-\\d{2,3}|\\[#[0-9a-fA-F]+\\])(?:/\\d+)?(?![\\w-])`,
  "g",
);

// What dims the page behind a dialog is black in light and in dark.
const ALLOWED = new Set(["backdrop:bg-black/40"]);

// The net has to hold before it is trusted.
for (const [sample, caught] of [
  ["text-red-600", true],
  ["dark:border-white/15", true],
  ["border-s-green-500", true],
  ["bg-black/5", true],
  ["text-black", true],
  ["hover:bg-[#0a2540]", true],
  ["text-danger", false],
  ["border-border-strong", false],
  ["bg-accent/20", false],
  ["text-balance", false],
  ["whitespace-pre-wrap", false],
]) {
  if ((sample.match(BY_HAND) !== null) !== caught) {
    throw new Error(`check-colours: ${sample} should ${caught ? "" : "not "}be refused`);
  }
}

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.tsx?$/.test(p)) yield p;
  }
}

const problems = [];
for (const base of SCAN) {
  for (const file of walk(join(ROOT, base))) {
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, i) => {
        // Comments explain the rule; they are not violations of it.
        if (/^\s*(\/\/|\*|\/\*)/.test(line)) return;
        for (const m of line.matchAll(BY_HAND)) {
          if (!ALLOWED.has(m[0])) problems.push(`${relative(ROOT, file)}:${i + 1}  ${m[0]}`);
        }
      });
  }
}

if (problems.length) {
  console.error("Colours written by hand — give them a name in app/globals.css:\n");
  for (const p of problems) console.error("  " + p);
  console.error(`\n${problems.length} problem(s).`);
  process.exit(1);
}
console.log("colours: ok — every colour has a name");
```

And in `apps/web/package.json`, the two lines after `"typecheck"` become three:

```json
    "check:rtl": "node scripts/check-logical-css.mjs",
    "check:colours": "node scripts/check-colours.mjs",
    "check": "npm run typecheck && npm run check:rtl && npm run check:colours && npm run lint && npm run test",
```

CI does not run `check`: it runs the pieces one by one. In `.github/workflows/ci.yml`, in the
step named *Check web*, one line is added after `npm run check:rtl`:

```yaml
          npm run check:rtl
          npm run check:colours
```

- [ ] **Step 6: Run the net and watch it fail**

Run, from `apps/web`: `npm run check:colours`
Expected: FAIL, ending `311 problem(s).`

- [ ] **Step 7: The one test that names a colour, first** — in
  `apps/web/components/inbox/MessageBubble.test.tsx`, the test that begins *writes a sent
  message's time and ticks* becomes:

```tsx
  it("writes a sent message's time and ticks so they can be read on the green", () => {
    // Grey on the accent cannot be read at all. The bubble's own white is 5.3 to 1.
    show({ direction: "out", origin: "inbox", status: "read" });
    const meta = screen.getByText("✓✓").parentElement as HTMLElement;
    expect(meta.className).not.toContain("text-muted");
    expect(meta.className).toContain("text-on-accent");
  });
```

Run: `npx vitest run components/inbox/MessageBubble.test.tsx`
Expected: 1 failed — `expected 'text-black/70 mt-1 flex items-center gap-2 text-[11px]' to contain 'text-on-accent'`.

- [ ] **Step 8: The pass** — save this as `recolour.mjs` in a scratch folder **outside the
  repository**. It is run once and not kept; the net of step 5 is what stays.

```js
// The one pass of docs/sales/11-ui-refresh.md § 8, step 1: every colour a
// component wrote by hand, to its name in app/globals.css.
//
//   node recolour.mjs <path to apps/web>            says what it would change
//   node recolour.mjs <path to apps/web> --write    changes it
//
// Run once and thrown away: scripts/check-colours.mjs is what stays.
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = process.argv[2];
const WRITE = process.argv.includes("--write");

// Whole phrases first: the places where the colours meant something the
// word-by-word rules below would get wrong. [file, from, to] — each exactly once.
const PHRASES = [
  // A hot lead is its own colour, not an error's.
  ["components/crm/CustomerRow.tsx", 'hot: "bg-red-500/15 text-red-700 dark:text-red-300"', 'hot: "bg-hot-soft text-hot"'],
  ["components/crm/LeadCard.tsx", 'hot: "bg-red-500/15 text-red-700 dark:text-red-300"', 'hot: "bg-hot-soft text-hot"'],
  // An internal note: the warning's soft fill, the page's own text on it.
  [
    "components/inbox/MessageBubble.tsx",
    "border border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-100",
    "border border-warning/40 bg-warning-soft text-foreground",
  ],
  ["components/inbox/Composer.tsx", '"bg-amber-50 dark:bg-amber-950/30"', '"bg-warning-soft"'],
  // The note switch, on: filled, because the bar it sits in has just turned soft.
  ["components/inbox/Composer.tsx", '"bg-amber-200 font-medium dark:bg-amber-800"', '"bg-warning font-medium text-background"'],
  [
    "components/inbox/DraftPanel.tsx",
    '"bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100"',
    '"bg-warning-soft text-warning"',
  ],
  [
    "components/inbox/DraftPanel.tsx",
    "bg-amber-100 p-2 text-sm text-amber-950 dark:bg-amber-900/40 dark:text-amber-100",
    "bg-warning-soft p-2 text-sm text-foreground",
  ],
  ["components/inbox/DraftPanel.tsx", "rounded bg-black/5 p-2 dark:bg-white/5", "rounded bg-surface p-2"],
  // A filled button that destroys: the page's own colour on the danger's.
  [
    "components/crm/EraseDialog.tsx",
    "bg-red-600 px-4 text-sm font-medium text-white",
    "bg-danger px-4 text-sm font-medium text-background",
  ],
];

// What dark mode said for itself. The name says it now, so the word goes.
const GONE = [
  "dark:border-white/10",
  "dark:border-white/15",
  "dark:border-white/20",
  "dark:divide-white/10",
  "dark:text-red-400",
  "dark:text-red-300",
  "dark:text-amber-400",
  "dark:text-amber-200",
  "dark:text-blue-300",
  "dark:text-blue-200",
  "dark:text-green-400",
];

// Word for word. A variant in front (hover:, sm:) is kept.
const WORDS = [
  ["border-black/5", "border-border"],
  ["border-black/10", "border-border"],
  ["border-black/15", "border-border-strong"],
  ["divide-black/5", "divide-border"],
  ["text-red-600", "text-danger"],
  ["text-red-700", "text-danger"],
  ["bg-red-500/15", "bg-danger-soft"],
  ["bg-red-500/10", "bg-danger-soft"],
  ["bg-red-500", "bg-danger"],
  ["border-s-red-500", "border-s-danger"],
  ["text-amber-700", "text-warning"],
  ["text-amber-800", "text-warning"],
  ["bg-amber-500/15", "bg-warning-soft"],
  ["bg-amber-500/10", "bg-warning-soft"],
  ["bg-amber-500", "bg-warning"],
  ["border-s-amber-500", "border-s-warning"],
  ["text-blue-700", "text-info"],
  ["bg-blue-500/15", "bg-info-soft"],
  ["bg-blue-500/10", "bg-info-soft"],
  ["bg-blue-500/5", "bg-info-soft"],
  ["border-blue-500/20", "border-info/20"],
  ["text-green-700", "text-success"],
  ["bg-green-500", "bg-success"],
  ["border-s-green-500", "border-s-success"],
  // Black was written on gold and white on navy. Both are the accent now.
  ["text-black/70", "text-on-accent"],
  ["text-black", "text-on-accent"],
  ["text-white", "text-on-accent"],
  ["bg-brand", "bg-accent"],
  ["text-brand", "text-accent-ink"],
  ["outline-brand", "outline-accent-ink"],
];

const escape = (word) => word.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
const whole = (word) => new RegExp(`(?<![\\w/-])${escape(word)}(?![\\w/-])`, "g");

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.tsx?$/.test(p) && !/\.test\.tsx?$/.test(p)) yield p;
  }
}

// What scripts/check-colours.mjs refuses, to say here what the pass left behind.
const HUES =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const PAINTS = "bg|text|border(?:-[sebtxylr])?|ring|outline|divide|accent|fill|stroke|placeholder|from|to|via|shadow|decoration|caret";
const BY_HAND = new RegExp(
  `(?<![\\w-])(?:[a-z-]+:)*(?:${PAINTS})-(?:black|white|(?:${HUES})-\\d{2,3}|\\[#[0-9a-fA-F]+\\])(?:/\\d+)?(?![\\w-])`,
  "g",
);

const counts = new Map();
const count = (key, n) => n && counts.set(key, (counts.get(key) ?? 0) + n);
const touched = [];
const problems = [];
const left = [];

for (const base of ["app", "components"]) {
  for (const file of walk(join(ROOT, base))) {
    const rel = relative(ROOT, file).replaceAll("\\", "/");
    const before = readFileSync(file, "utf8");
    let text = before;

    for (const [where, from, to] of PHRASES) {
      if (where !== rel) continue;
      const found = text.split(from).length - 1;
      if (found !== 1) problems.push(`${rel}: expected once, found ${found} times: ${from}`);
      text = text.replaceAll(from, to);
      count(`phrase  ${rel}`, found);
    }
    for (const word of GONE) {
      const re = new RegExp(`\\s${escape(word)}(?![\\w/-])`, "g");
      count(`gone    ${word}`, (text.match(re) ?? []).length);
      text = text.replace(re, "");
    }
    for (const [from, to] of WORDS) {
      const re = whole(from);
      count(`word    ${from} -> ${to}`, (text.match(re) ?? []).length);
      text = text.replace(re, to);
    }

    for (const m of text.matchAll(BY_HAND)) left.push(`${rel}  ${m[0]}`);
    if (text !== before) {
      touched.push(rel);
      if (WRITE) writeFileSync(file, text);
    }
  }
}

for (const [key, n] of counts) console.log(`${String(n).padStart(4)}  ${key}`);
const total = [...counts.values()].reduce((a, b) => a + b, 0);
console.log(`\n${total} changes in ${touched.length} files${WRITE ? ", written" : " (nothing written: add --write)"}`);
console.log(`still by hand afterwards: ${left.length ? "\n  " + left.join("\n  ") : "nothing"}`);
if (problems.length) {
  console.error("\nNot as expected:\n  " + problems.join("\n  "));
  process.exit(1);
}
```

Run it dry, from the repository root: `node <scratch>/recolour.mjs apps/web`
Expected, at the end:

```
306 changes in 59 files (nothing written: add --write)
still by hand afterwards: 
  components/Modal.tsx  backdrop:bg-black/40
```

Any other number, or a *Not as expected* line, means the tree has changed since this plan was
written: stop and read what moved before going on. Then, for real:
`node <scratch>/recolour.mjs apps/web --write`

- [ ] **Step 9: A comment that explained an old colour.** The pass changes words, not sentences.
  In `apps/web/components/inbox/WaitingTimer.tsx`, the line `// amber-700, not 600: on white that
  is 5 to 1, where 600 is 3.2.` goes: the palette's test holds that now. The map reads:

```tsx
const TONE: Record<"ok" | "due_soon" | "breached", string> = {
  ok: "text-muted",
  due_soon: "text-warning",
  breached: "text-danger",
};
```

- [ ] **Step 10: A message that failed, first as a test** — in
  `apps/web/components/inbox/MessageBubble.test.tsx`, after *says a message was not delivered, and
  offers to try again*:

```tsx
  it("does not draw a message that failed the way it draws one that went", () => {
    // Red on the green of a sent bubble is 1.4 to 1: the one line that matters
    // on a failed message could not be read. The bubble itself says it failed.
    show({
      direction: "out",
      origin: "inbox",
      status: "failed",
      error: { code: "131047", message: "Window closed" },
    });
    const bubble = screen.getByText(/not delivered/i).parentElement as HTMLElement;
    expect(bubble.className).toContain("bg-danger-soft");
    expect(bubble.className).not.toContain("bg-accent");
    // What is said quietly inside it is the grey that can be read on that.
    expect((bubble.querySelector("time")?.parentElement as HTMLElement).className).toContain(
      "text-muted",
    );
  });
```

Run: `npx vitest run components/inbox/MessageBubble.test.tsx`
Expected: 1 failed — `expected 'max-w-[80%] rounded-lg px-3 py-2 text-sm bg-accent text-on-accent' to contain 'bg-danger-soft'`.

- [ ] **Step 11: The bubble says it failed** — in `apps/web/components/inbox/MessageBubble.tsx`,
  the lines from `const note` down to `const quiet` become:

```tsx
  const note = message.kind === "note";
  const ours = message.direction === "out";
  const failed = message.status === "failed";
  // A message of ours is the accent's green — unless it did not go. Red on
  // that green is 1.4 to 1, and a message that failed must never pass for one
  // that was sent.
  const sent = ours && !note && !failed;
  // What is said quietly inside a bubble. Grey on the green of a sent message
  // cannot be read; the bubble's own white is 5.3 to 1.
  const quiet = sent ? "text-on-accent" : "text-muted";
```

and the bubble's own classes, a few lines below:

```tsx
        className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
          note
            ? "w-full border border-warning/40 bg-warning-soft text-foreground"
            : sent
              ? "bg-accent text-on-accent"
              : failed
                ? "bg-danger-soft text-foreground"
                : "bg-background"
        }`}
```

Run: `npx vitest run components/inbox/MessageBubble.test.tsx`
Expected: all passed, the test of step 7 among them.

- [ ] **Step 12: Everything, green**

Run, from `apps/web`:
- `npm run check:colours` — expected `colours: ok — every colour has a name`
- `npm run check:rtl` — expected `logical-css: ok — no physical direction classes`
- `npm run typecheck` — expected: no errors
- `npm run lint` — expected: no problems
- `npx vitest run` — expected `Test Files  60 passed (60)` and `Tests  352 passed (352)`

- [ ] **Step 13: Read what the pass did.** [11](../11-ui-refresh.md) §9 promises it.

Run, from the repository root:
`git diff --stat -- apps/web | tail -1` — expected `62 files changed`.
`git diff -U0 -- apps/web/app apps/web/components | grep -E "^[+-]" | grep -vE "^(\+\+\+|---)"`
— outside `MessageBubble`, every pair of lines differs in colour words only. A line that lost or
gained anything else is put back by hand.

And one question asked of the result, because no test can ask it: **is any coloured text now
sitting on the accent?** `grep -rn "bg-accent" apps/web/app apps/web/components` — every line is a
button, a count, or one of the two bubbles, and each carries `text-on-accent` and nothing else
that is coloured.

- [ ] **Step 14: Commit**

```bash
git add -u apps/web/app apps/web/components apps/web/package.json .github/workflows/ci.yml
git add apps/web/app/palette.test.ts apps/web/scripts/check-colours.mjs
git status --short   # nothing left but apps/web/AGENTS.md and apps/web/CLAUDE.md
git commit -F - <<'EOF'
feat(web): every colour behind a name, and the names are the new look's

311 colours were written by hand in the pages and components, most of them
twice: once for light and once more for dark. Each is now a name in
globals.css with a value for both, and the values are direction B's
(docs/sales/11-ui-refresh.md § 3.1). The gold and the navy are gone.

palette.test.ts holds every pair that carries text to 4.5 to 1 in light and
in dark, and `npm run check:colours` refuses a colour written by hand from
here on. One is left on purpose: the black that dims the page behind a
dialog.

A message of ours that failed is no longer drawn as one that went: its "Not
delivered" line is red, and red on the new green could not be read.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Task F2: One face, and softer corners

**Files:**
- Create: `apps/web/app/fonts.ts`
- Modify: `apps/web/app/layout.tsx`
- Modify: `apps/web/app/globals.css`

There is no unit test here on purpose: `next/font` is not a function a test can call, it is
something Next's compiler does to the file. The proof is the running page (step 5).

- [ ] **Step 1: Read Next's guide** —
  `node_modules/next/dist/docs/01-app/03-api-reference/02-components/font.md`, *With Tailwind
  CSS* and *Using a font definitions file*. If it says something this task does not, the guide
  wins and the review says what changed.

- [ ] **Step 2: The face** — `apps/web/app/fonts.ts`:

```ts
import { Readex_Pro } from "next/font/google";

/**
 * One family for Latin and Arabic ([11] § 3.2). Next fetches it when it builds
 * and serves it from the app's own address: a browser never asks Google for
 * anything.
 *
 * In a file of its own so that nothing a test imports reaches `next/font`,
 * which only exists inside Next's compiler.
 */
export const readex = Readex_Pro({
  subsets: ["latin", "arabic"],
  display: "swap",
  variable: "--font-readex",
});
```

- [ ] **Step 3: On the page** — in `apps/web/app/layout.tsx`, add the import beside the others
  and the class on `<html>`:

```tsx
import { readex } from "./fonts";
```

```tsx
    <html lang={locale} dir={dirFor(locale)} className={readex.variable}>
```

- [ ] **Step 4: In the stylesheet** — in `apps/web/app/globals.css`, the `body` rule and the
  Arabic rule under it become:

```css
body {
  background: var(--background);
  color: var(--foreground);
  /* One family for Latin and Arabic, set on <html> by app/fonts.ts. */
  font-family: var(--font-readex), system-ui, -apple-system, "Segoe UI", sans-serif;
}

/* Arabic wants a little more leading than Latin does. */
[dir="rtl"] body {
  line-height: 1.75;
}
```

and, directly after the `@theme inline { … }` block, a second block:

```css
/* Softer corners everywhere at once: what a component writes as rounded-md
   and rounded-lg ([11] § 3.3). Pills and bubbles come with their screens. */
@theme {
  --radius-md: 0.75rem;
  --radius-lg: 1.125rem;
}
```

- [ ] **Step 5: See it** — start the API and `next dev` (in this session, the `api-54432` and
  `web` previews), sign in as Sara Mansour, open the inbox, and ask the page:

```js
({
  face: getComputedStyle(document.body).fontFamily,
  loaded: [...document.fonts].some((f) => f.family.includes("Readex") && f.status === "loaded"),
  fromGoogle: performance.getEntriesByType("resource").filter((r) => /fonts\.(googleapis|gstatic)\.com/.test(r.name)).length,
  corner: getComputedStyle(document.querySelector(".rounded-md")).borderRadius,
  dir: document.documentElement.dir,
})
```

Expected: `face` begins with a Readex Pro family; `loaded` is `true`; `fromGoogle` is `0`;
`corner` is `12px`; `dir` is `ltr`. Then the same in Arabic (the `ar` button, or the `locale`
cookie set to `ar` and a reload): `dir` is `rtl`, and `face` and `loaded` are as before — one
family, not two.

- [ ] **Step 6: The checks** — from `apps/web`: `npm run typecheck`, `npm run check:rtl`,
  `npx vitest run`. Expected: clean, `ok`, and `352 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/web/app/fonts.ts apps/web/app/layout.tsx apps/web/app/globals.css
git commit -m "feat(web): one typeface for Latin and Arabic, and softer corners"
```

---

## Task F3: The installed app wears the same colour

The icon is drawn in code and the manifest is not CSS: neither can read a variable. A test is what
keeps them in step with the palette.

**Files:**
- Modify: `apps/web/app/manifest.test.ts`
- Modify: `apps/web/app/manifest.ts`, `apps/web/app/icon.tsx`, `apps/web/app/apple-icon.tsx`

- [ ] **Step 1: Write the failing test** — in `apps/web/app/manifest.test.ts`, two imports at the
  top and one test inside `describe("manifest", …)`:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
```

```ts
  it("wears the app's own colour", () => {
    // Neither the manifest nor an icon drawn in code can read a CSS variable.
    // This is what keeps them in step with the palette.
    const here = (file: string) => readFileSync(resolve(__dirname, file), "utf-8");
    const accent = /--accent:\s*(#[0-9a-f]{6})/.exec(here("./globals.css"))?.[1];
    expect(accent).toBeTruthy();
    expect(manifest().theme_color).toBe(accent);
    expect(manifest().background_color).toBe(accent);
    for (const icon of ["./icon.tsx", "./apple-icon.tsx"]) {
      expect(here(icon)).toContain(`background: "${accent}"`);
    }
  });
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npx vitest run app/manifest.test.ts`
Expected: 1 failed — `expected '#0a2540' to be '#0f7a55'`.

- [ ] **Step 3: The colour** — `#0a2540` becomes `#0f7a55` in four places: `background_color` and
  `theme_color` in `app/manifest.ts`, and `background` in `app/icon.tsx` and in
  `app/apple-icon.tsx`. In `icon.tsx` the comment's last words, *in step with the brand colour*,
  become *in step with the accent — `manifest.test.ts` sees to it*.

- [ ] **Step 4: Run it again**

Run: `npx vitest run app/manifest.test.ts`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/web/app/manifest.test.ts apps/web/app/manifest.ts apps/web/app/icon.tsx apps/web/app/apple-icon.tsx
git commit -m "feat(web): the installed app wears the app's own colour"
```

---

## Task F4: The whole check, the suite, and the look

- [ ] **Step 1: The whole check** — from the repository root: `npm run check:web`.
  Expected: types clean, `logical-css: ok`, `colours: ok`, lint clean, `Tests  353 passed (353)`.
  Then what CI runs after those and a laptop usually does not: with no `next dev` running, from
  `apps/web`, `npm run build`. Expected: it compiles, and it is the first time Next fetches the
  font for a build. A failure to reach Google's font files here is [11](../11-ui-refresh.md) §9's
  second risk, met early.

- [ ] **Step 2: The suite** — with no `next dev` running in this checkout:
  `E2E_DB_PORT=54432 npm run e2e`. Expected: `65 passed`.

  Two things this step can find, and what is done about each:
  - **A row that no longer fits at 360 px** (`fits()`): Readex Pro is wider than the system's
    face. It is fixed where it is, with a wrap or a smaller gap — never by making the text smaller
    or by taking a word out.
  - **A contrast the sweep refuses:** the pairing is fixed in `globals.css` or in the component,
    and the pair goes into `PAIRS` in `palette.test.ts`, so the next person is told by a unit test
    and not by a browser.

  Each is one line in the review.

- [ ] **Step 3: The look** — the running app, photographed:

  | Screen | How |
  |---|---|
  | Inbox with Omar Al Mazrouei's conversation open | A desk, English, light |
  | The same | A desk, English, dark |
  | Pipeline, Dashboard | A desk, English, light |
  | Inbox, then the conversation | A phone (375 px), Arabic, light |
  | Command Center, Inventory | A desk, light and dark: is anything unreadable |

  What is looked for: no gold and no navy anywhere; text that can be read on everything it sits
  on; the Arabic in the same family as the Latin; nothing that moved.

- [ ] **Step 4: Where it stands** — the first paragraph of [11](../11-ui-refresh.md) says step 1
  is done; `## Step 1 review` is appended here: what the suite and the screenshots found, what
  differs from this plan, what is known and left, and the numbers.

- [ ] **Step 5: Commit** — the two documents, by path. The screenshots are shown to the owner, not
  committed.

## Spec coverage (Step 1)

| Requirement | Task |
|---|---|
| [11](../11-ui-refresh.md) §3.1 — every colour a variable, light and dark, mapped into Tailwind | F1, steps 3 and 4. `ground` waits for step 2 |
| §3.1 — the old gold and navy go | F1 (the pass), F3 (the icon and the manifest) |
| §3.1 — every pair that carries text was worked out; the sweep is the judge | F1 (`palette.test.ts`), F4 step 2 |
| §3.2 — Readex Pro through `next/font`, one family, the Arabic leading stays | F2 |
| §3.2 — sizes of messages and lists | Steps 3 and 4, with the screens that set them |
| §3.3 — corners | F2 for `rounded-md` and `rounded-lg`. Pills and bubbles: steps 2 and 3 |
| §3.4 to §3.6 — shared classes, icons, avatars | Step 2 (see *What Step 1 does not build*) |
| §2 — roles, names, hooks, structure unchanged | Nothing in this step touches them; F4 step 2 proves it |
| §2 — the one class a test names that changes, with its reason | F1, steps 7 and 11 |
| §5.1 — a message of ours that failed is `danger-soft`, not green | F1, steps 10 and 11. Here and not in step 3, because it is the palette that breaks it |
| §6 — dark mode is the second column | F1; held by `palette.test.ts` until the dark sweep of step 6 |
| §7 — unit tests for what has a rule | `palette.test.ts`, `manifest.test.ts` |
| §7 — screenshots after each step, shown to the owner | F4, step 3 |
| §8.1 — nothing left on the old gold | F1 step 10 (`check:colours`), F4 step 3 |
| §9 — the pass is a script whose every change is read | F1, steps 8 and 11 |
| §9 — the font needs the network once | F2, step 5 (`fromGoogle` is 0 for the browser; the fetch is Next's, at build) |
| §9 — the marketing screens: nothing unreadable | F4, step 3 |

## Execution (Step 1)

Inline in this session, as S7's parts were — no subagents unless asked. One checkpoint: after F1,
before the face changes, because F1 is the commit that touches sixty files.
