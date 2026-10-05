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

---

## Step 1 review — 2026-10-05

**Built as planned, in three commits:** `bca3902` (every colour behind a name), `5e5d3be` (the
typeface and the corners), `f53a7c7` (the installed app's colour).

**The numbers.**

| What | Before | After |
|---|---|---|
| Colours written by hand in pages and components | 311 | 0, and one allowed on purpose: `backdrop:bg-black/40` |
| Names in `globals.css` | 9 | 18, each with a light and a dark value, each mapped into Tailwind |
| Lowest contrast of a pair that carries text | not held by anything | 5.34 to 1 in both modes (white on the accent), held by `palette.test.ts` |
| Unit tests | 347 in 59 files | 353 in 60 |
| End-to-end | 65 | 65 passed in 4.3 minutes, with no test changed |
| Requests a browser makes to Google for the font | — | 0: Next serves it from the app's own address |

`npm run check:web` is green, `next build` compiles with the font, and `check:colours` runs in
`npm run check` and in CI.

**What the suite and the screenshots found.** Nothing to fix. Readex Pro is wider than the
system's face and no row outgrew 360 px in either language; the sweep refused no pair of colours.
Fourteen screens were photographed — a desk in English, a phone in Arabic, light and dark, the two
marketing screens among them — and nothing on any of them is unreadable.

**What differs from the plan.**

- *Reading the pass* (F1 step 13) was done by a script, not by eye over 440 changed lines: each
  file before and after, with every colour word taken out of both, compared whole. It named the
  three files changed by hand and three more whose only difference was a Windows line ending. The
  special cases — the note, the note switch, the hot lead, the filled red button, the status dots —
  were then read in place.
- *The app was looked at before F1 was committed,* not after: a palette is easier to take back
  before it is a commit.
- *The photographs are taken by Playwright* from the developer's own server, with a script kept
  outside the repository. The app's built-in browser pane cannot show 1440 px at a size that can
  be read.

**Known, and left for the step that owns it.**

| What | Step |
|---|---|
| A customer's message is still white on white, with no bubble | 3 |
| A phone's header is still three rows, and the composer can fall below the screen under a long draft | 2 and 3 |
| The flag is still two letters on Windows; the bell is still an emoji; selects are the browser's own | 2 and 3 |
| The dashboard's tiles still mark their state with a coloured edge | 5 |
| Dark mode has no run of the sweep; `palette.test.ts` holds it pair by pair | 6 |
| Real phones and a screen reader | Staging |

---

# Step 2 — The shell

**Goal:** the frame of every page is direction B's. On a desk, a white rail 88 px wide with each
destination as an icon over its word; on a phone, one row at the top in place of three and a
floating bar of icons at the foot. The bell is a drawing, not an emoji. The language, the
workspace and the way out live in one menu under the person's own avatar.

**How this step was planned.** By reading what the shell is made of and what holds it in place.

| What was read | What it found |
|---|---|
| `Shell.tsx` | One `<aside>` that is a column on a desk and a block on a phone, and a second `<nav>` for the phone's bar. Keeping one `<aside>` with two shapes means one bell and one account button, not two of each hidden by CSS |
| `NavLinks.tsx` | Used twice: by the shell, and by Settings for its sections. So the icon is optional: with one, a link is drawn the shell's way; without, it is the row it was |
| `NotificationsBell.tsx` | Its list is positioned inside the sidebar. A rail that scrolls inside itself would cut it off, so the list becomes `fixed` on a desk as it already is on a phone |
| `LocaleToggle.tsx` | A server component. It goes into the menu as a child handed down by the shell, which is one too |
| `Shell.test.tsx`, `NotificationsBell.test.tsx`, `shell.e2e.ts`, `fixtures.ts` | Two navigations with one name; the skip link first; the bell's count inside its button; links found by their word inside the navigation called *Main*. All of it stays true |
| The bars that stick above a phone's navigation (`HandOverBar`, `AiSettings`, `RoutingForm`, the tasks' undo) | They assume a bar 64 px high at the very bottom. A floating bar with two-line Arabic labels reaches 92 px |
| The seven avatar tints of [11](../11-ui-refresh.md) §3.6 | 6.3 to 1 or better in light, 8.5 or better in dark |

One finding changed the step. **The canvas colour is still not in it.** A page drawn straight onto
mint, with its panels in a soft fill two shades away, loses its panels. `ground` arrives with the
first screen that puts white panels on it — the inbox, step 3 — and each later screen moves onto
it as it is redrawn.

**Architecture:** the rail and the top row are the same element, shaped by breakpoint. The shell
draws with three new things, each written here because here is where it is first used: `Icon`
(one file, the drawings named by what they mean), `Avatar` (initials on a tint chosen from the
name, by two pure functions with tests), and two classes in `globals.css`, `icon-btn` and
`badge`. The account menu is a dialog through `Modal.tsx`; what goes in it is the shell's to say.

**Tech stack:** nothing new.

## What Step 2 does not build

| Item | Why, and when |
|---|---|
| `ground`, `btn`, `field`, `pill`, `card` | Nothing in the shell draws with them. Step 3 |
| A flag on an avatar, and avatar sizes | The shell's only avatar is the person signed in. Step 3, with customers |
| Hiding the phone's bar inside a conversation | It would change how the tests move between screens. If wanted, its own decision |

## File structure

| File | Responsibility |
|---|---|
| `apps/web/app/globals.css`, `palette.test.ts` | **Modify.** Seven avatar tints, light and dark, held to 4.5 to 1; `icon-btn`; `badge` |
| `apps/web/components/Icon.tsx`, `Icon.test.tsx` | **Create.** The drawings |
| `apps/web/lib/avatar.ts`, `avatar.test.ts`, `apps/web/components/Avatar.tsx` | **Create.** Initials and tint from a name; the circle |
| `apps/web/components/NavLinks.tsx` | **Modify.** An optional icon: the drawing over the word |
| `apps/web/components/NotificationsBell.tsx` | **Modify.** A drawn bell; a list that is not cut off by the rail |
| `apps/web/components/AccountMenu.tsx`, `AccountMenu.test.tsx` | **Create.** The avatar, and the dialog it opens |
| `apps/web/components/AvailabilitySwitch.tsx` | **Modify.** A compact shape for the rail |
| `apps/web/messages/en.ts`, `ar.ts` | **Modify.** `account.title`, `account.language`, `common.close` |
| `apps/web/components/Shell.tsx`, `Shell.test.tsx` | **Modify.** The rail, the top row, the floating bar |
| `apps/web/components/crm/HandOverBar.tsx`, `settings/AiSettings.tsx`, `settings/RoutingForm.tsx`, `app/[tenant]/tasks/page.tsx` | **Modify.** Clear of the floating bar |

---

## Task S1: The avatar's colours, and two classes

**Files:** `apps/web/app/palette.test.ts`, `apps/web/app/globals.css`

- [ ] **Step 1: The test first.** In `palette.test.ts`, names may now carry a digit — the pattern
  in `values()` becomes `/--([a-z0-9-]+):\s*(#[0-9a-f]{6})\b/g` — and `PAIRS` gains, as its last
  entry:

```ts
  // An avatar's initials on its own tint.
  ...Array.from({ length: 7 }, (_, n) => [`tint-${n}-ink`, `tint-${n}`] as const),
```

Run `npx vitest run app/palette.test.ts`: 2 failed, with `tint-0-ink on tint-0: no such name`.

- [ ] **Step 2: The tints.** In `globals.css`, the fourteen values of
  [11](../11-ui-refresh.md) §3.6 as `--tint-0` and `--tint-0-ink` to `--tint-6` and
  `--tint-6-ink`, at the end of the light `:root` block and again, with their dark values, at the
  end of the dark one; fourteen mapping lines of the one shape in `@theme inline`
  (`--color-tint-0: var(--tint-0);`); and after the radii:

```css
@layer components {
  /* A round button that holds one icon and has a name ([11] § 3.4). */
  .icon-btn {
    position: relative;
    display: inline-grid;
    place-items: center;
    min-width: 2.75rem;
    min-height: 2.75rem;
    border-radius: 9999px;
  }
  .icon-btn:hover {
    background: var(--surface);
  }

  /* A count, on the corner of what it counts. */
  .badge {
    display: inline-grid;
    place-items: center;
    min-width: 1.125rem;
    height: 1.125rem;
    padding-inline: 0.3125rem;
    border-radius: 9999px;
    background: var(--accent);
    color: var(--on-accent);
    font-size: 0.6875rem;
    font-weight: 600;
    line-height: 1;
  }
}
```

- [ ] **Step 3:** `npx vitest run app/palette.test.ts` — 4 passed. `npm run check:rtl` — ok.

## Task S2: The drawings

**Files:** `apps/web/components/Icon.tsx`, `Icon.test.tsx`

- [ ] **Step 1: The test** — `Icon.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./Icon";

describe("Icon", () => {
  it("is never read out: the control it sits in has the name", () => {
    const { container } = render(<Icon name="bell" />);
    const drawing = container.querySelector("svg");
    expect(drawing?.getAttribute("aria-hidden")).toBe("true");
    expect(drawing?.querySelector("path")).not.toBeNull();
  });
});
```

Fails: there is no `./Icon`.

- [ ] **Step 2: `Icon.tsx`** — a table `DRAWINGS` of JSX keyed by what each drawing means
  (`inbox`, `today`, `customers`, `pipeline`, `tasks`, `dashboard`, `inventory`, `approvals`,
  `settings`, `command`, `content`, `bell`, `person`, `close`), `export type IconName = keyof
  typeof DRAWINGS`, and:

```tsx
export function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
    >
      {DRAWINGS[name]}
    </svg>
  );
}
```

The fourteen drawings are the mock-up's ([the canvas](https://claude.ai/artifact/Firg3c1Vh1rM44xuV4ZWYm)),
path for path. A drawing joins the table in the step that first uses it.

- [ ] **Step 3:** the test passes.

## Task S3: A person, as a circle

**Files:** `apps/web/lib/avatar.ts`, `avatar.test.ts`, `apps/web/components/Avatar.tsx`

- [ ] **Step 1: The rules, as tests** — `lib/avatar.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { TINTS, initials, tint } from "./avatar";

describe("initials", () => {
  it("takes the first letter of the first word and of the last", () => {
    expect(initials("Omar Al Mazrouei")).toBe("OM");
    expect(initials("  james   whitfield ")).toBe("JW");
  });

  it("takes one letter from one word", () => {
    expect(initials("Sara")).toBe("S");
  });

  it("takes one letter from an Arabic name: two would join and read as a word", () => {
    expect(initials("عمر المزروعي")).toBe("ع");
  });

  it("has nothing to say for nobody", () => {
    expect(initials(null)).toBe("");
    expect(initials("   ")).toBe("");
  });
});

describe("tint", () => {
  it("is the same for the same person, however the name was typed", () => {
    expect(tint("Omar Al Mazrouei")).toBe(tint("  omar al mazrouei "));
  });

  it("is always one of the seven", () => {
    for (const name of ["Omar Al Mazrouei", "Mona Fathy", "عمر", "", null]) {
      const chosen = tint(name);
      expect(Number.isInteger(chosen) && chosen >= 0 && chosen < TINTS).toBe(true);
    }
  });
});
```

- [ ] **Step 2: `lib/avatar.ts`:**

```ts
/** Arabic and the scripts written like it: letters that join. */
const JOINS = /[؀-ۿݐ-ݿࢠ-ࣿ]/;

/** The letters that stand for a name ([11] § 3.6). */
export function initials(name: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "";
  const first = [...words[0]][0];
  // Two Arabic initials join and read as the start of a word. One, then.
  if (words.length === 1 || JOINS.test(first)) return first.toUpperCase();
  return (first + [...words[words.length - 1]][0]).toUpperCase();
}

/** How many tints `globals.css` has. */
export const TINTS = 7;

/** The same person is always the same colour. */
export function tint(name: string | null | undefined): number {
  let sum = 0;
  for (const letter of (name ?? "").trim().toLowerCase()) {
    sum = (sum * 31 + (letter.codePointAt(0) ?? 0)) % 9973;
  }
  return sum % TINTS;
}
```

- [ ] **Step 3: `components/Avatar.tsx`** — a `<span aria-hidden="true">`, round, 36 px, in
  `bg-tint-N text-tint-N-ink` for `N = tint(name)` (each of the seven class pairs written out
  whole in a table, because Tailwind finds classes by reading the file), holding `initials(name)`
  or, when there are none, `<Icon name="person" />`. Hidden from a screen reader: the name is
  beside it, or is the name of the control it sits in.

- [ ] **Step 4:** `npx vitest run lib/avatar.test.ts` — 6 passed.

## Task S4: The navigation, drawn

**Files:** `apps/web/components/NavLinks.tsx`

- [ ] **Step 1:** `NavItem` gains `icon?: IconName`. A link with one is the drawing over its
  word, on `accent-soft` when it is the page; a link without one — Settings' sections — is the row
  it was, with its chosen state on `surface`, which can be seen on a white page where `background`
  could not. The count is `badge` in both.

```tsx
        return item.icon ? (
          // In the shell: the drawing over its word ([11] § 4).
          <Link
            key={item.key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 w-full flex-col items-center justify-center gap-0.5 rounded-2xl px-1 py-1.5 text-center text-[11px] leading-4 transition-colors rtl:text-xs ${
              active
                ? "bg-accent-soft text-accent-ink font-semibold"
                : "text-muted hover:bg-surface hover:text-foreground"
            }`}
          >
            <span className="relative">
              <Icon name={item.icon} size={22} />
              {badge > 0 && <span className="badge absolute -end-2.5 -top-1.5">{badge}</span>}
            </span>
            <span>{t(item.key)}</span>
          </Link>
        ) : (
          <Link
            key={item.key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center justify-between gap-2 rounded-md px-3 py-2 text-start text-sm transition-colors ${
              active ? "bg-surface font-medium" : "hover:bg-surface"
            }`}
          >
            <span>{t(item.key)}</span>
            {badge > 0 && <span className="badge">{badge}</span>}
          </Link>
        );
```

## Task S5: The bell

**Files:** `apps/web/components/NotificationsBell.tsx`

- [ ] **Step 1:** the button is `icon-btn` holding `<Icon name="bell" size={22} />` and, when
  there is something unread, `<span className="badge absolute end-0.5 top-0.5">`. The list is
  `fixed` at both sizes — under the top row on a phone, beside the rail's foot on a desk:

```tsx
          className="border-border bg-background fixed inset-x-3 top-14 z-20 max-h-96 overflow-y-auto rounded-lg border shadow-lg md:inset-x-auto md:start-24 md:top-auto md:bottom-3 md:w-80"
```

Its rows hover on `surface`. Its five unit tests pass unchanged.

## Task S6: The account menu

**Files:** `apps/web/components/AccountMenu.tsx`, `AccountMenu.test.tsx`,
`AvailabilitySwitch.tsx`, `apps/web/messages/en.ts`, `ar.ts`

- [ ] **Step 1: The words.** `account.title` — *Your account* / *حسابك*; `account.language` —
  *Language* / *اللغة*; `common.close` — *Close* / *إغلاق*. In both catalogues, by hand: prettier
  is never run on them.

- [ ] **Step 2: The test** — `AccountMenu.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountMenu } from "./AccountMenu";
import { LocaleProvider } from "@/lib/i18n-client";

vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { user: { id: "u1", name: "Sara Mansour" } } }),
}));

const show = () =>
  render(
    <LocaleProvider locale="en">
      <AccountMenu>
        <p>what the shell put inside</p>
      </AccountMenu>
    </LocaleProvider>,
  );

describe("AccountMenu", () => {
  it("is a button with a name, showing whose account it is", () => {
    show();
    expect(screen.getByRole("button", { name: "Your account" }).textContent).toBe("SM");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens a dialog with the person's name and what it was given, and closes again", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Your account" }));
    const dialog = screen.getByRole("dialog", { name: "Your account" });
    expect(dialog.textContent).toContain("Sara Mansour");
    expect(dialog.textContent).toContain("what the shell put inside");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
```

- [ ] **Step 3: `AccountMenu.tsx`** — a client component: a button, `icon-btn`, named
  `account.title`, holding the `Avatar` of `useMe().data?.user.name`; pressed, it renders
  `<Modal label={t("account.title")} onClose={…}>` with a first row — the avatar, the name as an
  `h2` with `dir="auto"`, and a close `icon-btn` named `common.close` — and under it its
  `children` in a column. What the children are is the shell's to say: some are drawn on the
  server, which a client component may be handed but may not import.

- [ ] **Step 4: `AvailabilitySwitch`** takes `compact`: in the rail it is its dot over its words,
  in the 11 px of the rail's labels, hovering on `surface`. Without it, it is the row it was.

## Task S7: The frame

**Files:** `apps/web/components/Shell.tsx`, `Shell.test.tsx`, and the four that sit above the
phone's bar

- [ ] **Step 1:** `Shell.test.tsx` mocks one more thing, `./AccountMenu`, as it mocks the others.

- [ ] **Step 2: `Shell.tsx`.** Every destination gets its `icon`. The frame:

```tsx
    <div className="grid min-h-screen grid-rows-[auto_1fr] md:grid-cols-[5.5rem_1fr] md:grid-rows-1">
      <a
        href="#page"
        className="bg-surface border-border sr-only rounded-md border px-3 py-2 text-sm focus:not-sr-only focus:fixed focus:start-2 focus:top-2 focus:z-50"
      >
        {t(locale, "nav.skip")}
      </a>
      {/* One element, two shapes ([11] § 4): a row across the top of a phone, a
          rail down the side of a desk. So there is one bell and one account. */}
      <aside className="border-border bg-background flex items-center gap-2 border-b px-3 py-1 md:sticky md:top-0 md:h-dvh md:flex-col md:gap-3 md:overflow-y-auto md:border-b-0 md:border-e md:px-2 md:py-3">
        <span
          role="img"
          aria-label="DealerAI"
          className="bg-accent text-on-accent grid size-9 shrink-0 place-items-center rounded-xl text-base font-semibold md:size-11 md:text-lg"
        >
          D
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium md:hidden">{tenant.name}</span>

        {/* The same list as the bar under a phone's page; CSS shows one. */}
        <nav
          aria-label={t(locale, "nav.main")}
          className="hidden w-full flex-col items-center gap-0.5 md:flex"
        >
          <NavLinks
            slug={tenant.slug}
            items={SALES}
            badges={{ "nav.approvals": pendingApprovals }}
          />
          <hr aria-hidden="true" className="border-border my-1.5 w-10" />
          <p className="sr-only">{t(locale, "nav.marketing")}</p>
          <NavLinks slug={tenant.slug} items={MARKETING} />
        </nav>

        <div className="flex shrink-0 items-center gap-1 md:mt-auto md:w-full md:flex-col">
          <div className="hidden w-full md:block">
            <AvailabilitySwitch compact />
          </div>
          <NotificationsBell />
          <AccountMenu>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm">{t(locale, "account.language")}</span>
              <LocaleToggle locale={locale} />
            </div>
            <WorkspaceSwitcher current={tenant} tenants={tenants} locale={locale} />
            {/* On a desk it is in the rail, where it is one press away. */}
            <div className="md:hidden">
              <AvailabilitySwitch />
            </div>
            <SignOutButton />
          </AccountMenu>
        </div>
      </aside>

      <main id="page" className="min-w-0 p-4 pb-28 md:p-8">
        {children}
      </main>

      <nav
        aria-label={t(locale, "nav.main")}
        className="border-border bg-background fixed inset-x-3 bottom-3 z-10 grid grid-cols-5 gap-1 rounded-3xl border p-1.5 shadow-lg md:hidden"
      >
        <NavLinks slug={tenant.slug} items={MOBILE} />
      </nav>
    </div>
```

- [ ] **Step 3: Clear of the bar.** A floating bar with two-line labels reaches 92 px from the
  foot of a phone. `sticky bottom-16` becomes `sticky bottom-28` in `HandOverBar.tsx`,
  `AiSettings.tsx` and `RoutingForm.tsx`, and the tasks' undo goes from `bottom-24` to
  `bottom-28`. Their `md:` values stay.

- [ ] **Step 4:** from `apps/web`, `npm run check`. Expected: green, with `Tests  362 passed` in 63
  files: 353, one for the icon, six for the avatar, two for the menu.

## Task S8: The whole check, the suite, and the look

- [ ] **Step 1:** `npm run check:web`, then `npm run build` in `apps/web`.
- [ ] **Step 2:** with no `next dev` running, `E2E_DB_PORT=54432 npm run e2e` — 65 passed. A test
  that cannot find something is read before it is touched: the shell is meant to keep every name
  and role it had.
- [ ] **Step 3:** the photographs — a desk and a phone, English and Arabic, light and dark.
- [ ] **Step 4:** `## Step 2 review`, here; where it stands, in [11](../11-ui-refresh.md).

## Spec coverage (Step 2)

| Requirement | Task |
|---|---|
| [11](../11-ui-refresh.md) §3.4 — `icon-btn`, `badge` | S1. The rest of the classes: step 3 |
| §3.5 — one file of drawings, always hidden, no emoji | S2, S5 |
| §3.6 — initials, one for Arabic, a tint from the name | S1, S3. The flag badge: step 3 |
| §4 — the rail, the top row, the floating bar | S4, S7 |
| §4 — the account menu; *Taking chats* in the rail on a desk and in the menu on a phone | S6, S7 |
| §4 — the skip link and the two navigations with one name stay | S7 step 1; `Shell.test.tsx`, `shell.e2e.ts` |
| §2 — nothing the tests hold on to changes | S8 step 2 |

## Execution (Step 2)

Inline, straight on from step 1: the owner said to go on.

---

## Step 2 review — 2026-10-05

**Built as planned, in two commits:** `5dd6701` (the drawings, the avatar, `icon-btn` and
`badge`) and `cabc7e0` (the shell).

| What | Before | After |
|---|---|---|
| A phone's header | Three rows: the name, the language and the bell, the workspace | One row, 53 px |
| The navigation | Words | A drawing over each word; the chosen one on `accent-soft` |
| Emoji drawing an icon | One, the bell | None |
| Unit tests | 353 in 60 files | 362 in 63 |
| End-to-end | 65 | 65 passed in 4.4 minutes, with no test changed |

`npm run check:web` is green and `next build` compiles.

**What the suite found.** Nothing. The shell kept every name and role the tests hold on to: two
navigations called *Main* with one shown, the skip link first, the bell's count inside its button.

**What differs from the plan.** The tasks were built together and committed as two, not seven: the
pieces, then the frame that uses them. The account menu was photographed open on a desk and on a
phone in Arabic, and the bell's list beside the rail's foot.

**Known, and left.**

| What | Step |
|---|---|
| Inside a conversation on a phone, the top row and the floating bar still take room the conversation wants | 3 |
| The page is still white from edge to edge: no canvas yet | 3 onwards |
| Settings' sections are rows of words | 5 |
| An iPhone's home indicator and the floating bar: to be looked at on a real phone | Staging |

---

# Step 3 — The inbox

**Goal:** the inbox is the mock-up, in the running app. The list and the conversation fill the
window as two panels; a conversation is bubbles on the mint canvas; the AI draft is a dashed
bubble on our side; the composer is one row; and on a phone an open conversation has the whole
screen.

**How this step was planned.** By reading the eight components and what finds them.

| What was read | What it found |
|---|---|
| The end-to-end tests' own locators | `page.locator("header")` must stay one element while the customer panel is shut; `a[href*="/pipeline?lead="]` must stay one link; *Send* is found by exact name; the waiting state by its `aria-label`. So the lead strip is a button, not a link, and no second `<header>` appears |
| `fixtures.ts`, `visit()` | Where the navigation does not have a destination, a test goes there by its address. So the phone's bar can be hidden inside a conversation without a test losing its way |
| `inbox/layout.tsx` | `h-full` with nothing definite above it. The inbox needs the window's height, which depends on a row the shell owns — so the shell says how tall that row is, in one CSS variable |
| `Thread.copilot.test.tsx` | It fakes the data hooks one by one. A thread that reads the customer's open lead needs one more faked |
| `WaitingTimer.tsx`, `lib/format.ts` | The timer looks again every thirty seconds and shows seconds. `formatDuration` is also the dashboard's, where seconds matter: the timer rounds what it gives it, and the formatter stays as it is |
| `CustomerName` | It draws the flag. Beside an avatar, the avatar carries it — so `CustomerName` is given no country there, and is otherwise unchanged |

**Decisions made here.**

- **On a phone an open conversation hides the shell's top row and its bar.** The way out is the
  back arrow, as in every messenger. It is what gives the composer its place at the foot of the
  screen ([11](../11-ui-refresh.md) §9's risk about a long draft goes with it).
- **The canvas is `ground`, here first.** The conversation is drawn on it; the list, the header
  and the composer are white panels.
- **`btn`, `field`, `pill` arrive**, and are used by every control this step touches. `card`
  still waits for step 4.

## What Step 3 does not build

| Item | Why, and when |
|---|---|
| The customer's own page, the pipeline, tasks | Step 4. `CustomerRow` and `LeadCard` keep their own band colours until then |
| The fields inside *What we know* | Their editing is its own small machine (`ProfileField`); only what surrounds them changes |
| Templates and quick replies, beyond their colours and buttons | They work, and nobody has looked at them in the mock-up |

## File structure

| File | Responsibility |
|---|---|
| `apps/web/app/globals.css`, `palette.test.ts` | **Modify.** `ground`; `btn`, `field`, `pill` and their tones |
| `apps/web/components/Icon.tsx` | **Modify.** `back`, `check`, `refresh`, `spark`, `send`, `clock`, `alert`, `note`, the two chevrons |
| `apps/web/components/Avatar.tsx` | **Modify.** Sizes; a customer's flag on its corner |
| `apps/web/lib/format.ts`, `format.test.ts` | **Modify.** `countryName`: a country as a word, in the reader's language |
| `apps/web/components/inbox/WaitingTimer.tsx`, `WaitingTimer.test.tsx` | **Modify, create.** A pill; minutes after the first minute |
| `apps/web/components/Shell.tsx`, `app/[tenant]/inbox/layout.tsx` | **Modify.** The window's height; no shell around a conversation on a phone |
| `apps/web/components/inbox/ConversationList.tsx`, `ConversationRow.tsx` | **Modify.** Pills for tabs, a soft search, rows with avatars |
| `apps/web/components/inbox/Thread.tsx`, `LeadStrip.tsx`, `Thread.copilot.test.tsx` | **Modify, create.** The header; the open lead in one line; the canvas |
| `apps/web/components/inbox/MessageBubble.tsx` | **Modify.** Bubbles with a corner on the side they speak from |
| `apps/web/components/inbox/DraftPanel.tsx`, `Composer.tsx` | **Modify.** The dashed bubble; one row to write in |
| `apps/web/components/crm/CustomerPanel.tsx`, `band.ts` | **Modify, create.** The panel; a band's pill, said once |

---

## Task I1: The canvas and the classes

- [ ] `palette.test.ts` gains `["foreground", "ground"]` and `["muted", "ground"]`, and fails.
- [ ] `globals.css`: `--ground` is `#edf3ef` in light and `#0c1210` in dark, mapped as the others
  are. In the components layer: `btn` (outlined, a pill, 44 px), `btn-primary` (the accent,
  darkening on hover), `btn-quiet` (no outline until hovered); `field` (a pill; a `textarea` gets
  a 22 px corner) and `field-soft`; `pill` and `pill-danger`, `pill-warning`, `pill-info`,
  `pill-accent`, `pill-hot`, each a soft fill with its own ink — pairs the palette's test already
  holds. The test passes.

## Task I2: What the pieces need

- [ ] **`countryName(code, locale)`** in `lib/format.ts`, test first:

```ts
describe("countryName", () => {
  it("says a country as a word, in the reader's language", () => {
    expect(countryName("ae", "en")).toBe("United Arab Emirates");
    expect(countryName("DZ", "ar")).toBe("الجزائر");
  });

  it("says nothing for what is not a country's code", () => {
    expect(countryName(null, "en")).toBe("");
    expect(countryName("Algeria", "en")).toBe("");
  });
});
```

```ts
/** A country as a word, in the reader's language. `Intl` knows them all. */
export function countryName(iso2: string | null, locale: Locale): string {
  if (!iso2 || !/^[a-z]{2}$/i.test(iso2)) return "";
  try {
    return new Intl.DisplayNames([DATE_LOCALE[locale]], { type: "region" }).of(iso2.toUpperCase()) ?? "";
  } catch {
    return "";
  }
}
```

- [ ] **`Avatar`** takes `size` (`sm` 28, `md` 36, `lg` 44, `xl` 56 px) and `country`. A country
  is `countryFlag(country)` in a small white badge on the corner at the end side: a picture where
  the system has flags, two letters where it has not.

- [ ] **`WaitingTimer`**, test first — `WaitingTimer.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WaitingTimer } from "./WaitingTimer";
import { LocaleProvider } from "@/lib/i18n-client";

const NOW = Date.parse("2026-10-05T10:00:00Z");
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();
const show = (seconds: number, state: "ok" | "due_soon" | "breached") =>
  render(
    <LocaleProvider locale="en">
      <WaitingTimer waitingSince={ago(seconds)} state={state} now={NOW} />
    </LocaleProvider>,
  );

describe("WaitingTimer", () => {
  it("counts in minutes once a minute has passed", () => {
    show(22 * 60 + 30, "breached");
    expect(screen.getByLabelText("Missed 22m")).toBeDefined();
  });

  it("counts the first minute in seconds", () => {
    show(45, "ok");
    expect(screen.getByLabelText("Waiting 45s")).toBeDefined();
  });

  it("says its state in a word and wears it: plain, then a warning, then danger", () => {
    expect(show(45, "ok").container.querySelector(".pill")?.className).toBe("pill ");
    expect(show(300, "due_soon").container.querySelector(".pill-warning")).not.toBeNull();
    expect(show(900, "breached").container.querySelector(".pill-danger")).not.toBeNull();
  });
});
```

The timer becomes `<span className={`pill ${TONE[state]}`} aria-label=…>` with a clock, or an
alert when missed, and `formatDuration(seconds < 60 ? seconds : Math.floor(seconds / 60) * 60,
locale)`.

## Task I3: The window

- [ ] **`Shell.tsx`** says how tall its top row is, and steps aside for a conversation on a phone.
  The root gains `group/shell [--shell-top:3.3125rem] has-[[data-thread]]:[--shell-top:0px]
  md:[--shell-top:0px]`; the `<aside>` gains `max-md:group-has-[[data-thread]]/shell:hidden`; the
  phone's `<nav>` gains `group-has-[[data-thread]]/shell:hidden`.
- [ ] **`inbox/layout.tsx`** takes the window: `-mx-4 -mt-4 -mb-28
  h-[calc(100dvh-var(--shell-top))] md:-m-8`, two columns from `lg` (`23.25rem` and the rest), the
  list a white panel, the conversation's side `bg-ground`.

## Task I4: The list

- [ ] **`ConversationList`**: the tabs are pills in a row that scrolls sideways before it would
  widen the page, the chosen one filled, each count in a small circle; the search is `field
  field-soft`; the rows scroll with room under the last one for the phone's bar.
- [ ] **`ConversationRow`**: the avatar with the flag, then the name and the age, one line of what
  was said, and the waiting pill, who has it and the unread `badge`. No rule between rows; the
  chosen one on `accent-soft`. *Unassigned* is `pill pill-accent`. Its eight tests pass unchanged.

## Task I5: The conversation

- [ ] **`LeadStrip.tsx`** — a button, never a link:

```tsx
/**
 * The customer's open lead, in one line under their name ([11] § 5.1). It reads
 * what the customer panel reads, so opening the panel asks for nothing new —
 * and it is a button that opens that panel, not a second link to the pipeline.
 */
export function LeadStrip({ contactId, onOpen }: { contactId: string; onOpen: () => void }) {
  const t = useT();
  const customer = useCustomer(contactId);
  const lead = customer.data?.leads.find((candidate) => candidate.stage.category === "open");
  if (!lead) return null;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="bg-background hover:bg-surface mx-3 mt-3 flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1 rounded-2xl px-4 py-2 text-start text-xs lg:mx-5"
    >
      <Icon name="inventory" size={16} className="text-muted" />
      <span className="text-muted">{t("customer.openLead")}</span>
      <Auto className="text-sm font-medium">{lead.vehicle?.label ?? lead.pipeline_name}</Auto>
      <Auto className="pill">{lead.stage.name}</Auto>
      {lead.band && <span className={`pill ${BAND_PILL[lead.band]}`}>{t(`band.${lead.band}`)}</span>}
      {lead.budget && <Ltr className="ms-auto text-sm font-semibold">{formatMoney(lead.budget)}</Ltr>}
    </button>
  );
}
```

- [ ] **`Thread.tsx`**: the header is a white panel — back (a drawn arrow inside the span that
  mirrors it), the avatar, the name as the `h1`, then *Assign to me*, *Customer* and *Close* as
  `btn`s; under the name the waiting pill, who has it and the window, all still inside the one
  `<header>`. On a phone *Customer* and *Close* are their drawings, their words kept for a screen
  reader. Then the strip; then the messages on `ground`; the customer panel a white column.
  `Thread.copilot.test.tsx` fakes `useCustomer` too.
- [ ] **`MessageBubble.tsx`**: a 22 px corner, tight on the side the bubble speaks from
  (`rounded-es-md` theirs, `rounded-ee-md` ours); theirs white with a soft shadow; 16 px on a
  phone and 15 on a desk. Its tests pass unchanged.

## Task I6: The draft and the composer

- [ ] **`DraftPanel.tsx`**: still a `<section>` named *AI draft*, outside the log. Inside it one
  bubble on our side: white, a dashed `accent` outline, the tight corner at the end. The label
  with its spark, confidence and intent as pills, *Collapse draft* as a chevron that keeps its
  name; sources as pills; *Send draft* `btn-primary`, the rest `btn` and `btn-quiet`. Its tests
  pass unchanged.
- [ ] **`Composer.tsx`**: one row — *Internal note* (a pill that fills with `warning` when on; its
  drawing alone on a phone), the box (`field`), and *Send*, a round accent button whose name is
  still *Send*. Its tests pass unchanged.

## Task I7: The customer panel

- [ ] **`band.ts`**: `BAND_PILL = { hot: "pill-hot", warm: "pill-warning", cold: "pill-info" }`.
- [ ] **`CustomerPanel.tsx`**: the avatar (large, with the flag), the name, the number, the
  country as a word, who has them; a drawn close button that keeps its name; tags as pills; the
  open lead as a card — still the one link to `/pipeline?lead=` — with its stage and band as pills
  and its price at the end.

## Task I8: The whole check, the suite, and the look

- [ ] `npm run check:web`; `npm run build`; `E2E_DB_PORT=54432 npm run e2e` — 65 passed. A test
  that now finds two of something is narrowed to where it meant to look
  ([11](../11-ui-refresh.md) §9); a test that finds none is read before anything is touched.
- [ ] The photographs: the inbox on a desk in English, light and dark, with the customer panel
  open in one; on a phone in Arabic, the list and the conversation.
- [ ] `## Step 3 review`, here; where it stands, in [11](../11-ui-refresh.md).

## Spec coverage (Step 3)

| Requirement | Task |
|---|---|
| [11](../11-ui-refresh.md) §3.1 `ground`; §3.4 `btn`, `field`, `pill` | I1 |
| §3.6 — the flag on the avatar's corner | I2 |
| §5.1 — the inbox fills the window | I3 |
| §5.1 — the list, the waiting pill and its three looks, minutes | I2, I4 |
| §5.1 — the header, the lead strip, messages | I5 |
| §5.1 — the draft, the composer | I6 |
| §5.1 — the customer panel, the country as a word | I2, I7 |
| §9 — the lead strip says words the panel also says | I5 (a button), I8 |

## Execution (Step 3)

Inline, straight on from step 2.

---

## Step 3 review — 2026-10-05

**Built as planned, in three commits:** `3d89d68` (the canvas and the classes), `ad972f2` (the
flag on the avatar, a country in words, the timer in minutes) and `8a5e0f3` (the inbox).

| What | Before | After |
|---|---|---|
| A customer's message | White on white, no bubble | A white bubble on the mint canvas |
| A conversation on a phone | Under a three-row header, over a bar, the composer sometimes below the screen | The whole screen, the composer at its foot |
| The waiting timer | Coloured text, with seconds that were already out of date | A pill with three looks; minutes after the first |
| The customer's open lead | Only inside the panel | One line under the name as well |
| Unit tests | 362 in 63 files | 367 in 64 |
| End-to-end | 65 | 65 passed in 4.4 minutes, with no test changed |

**What the suite found: one thing, and it was real.** The first run was 64 of 65. In Arabic at
360 px the sweep refused the conversation: *scrollable-region-focusable*. The messages now scroll
inside the conversation where the page used to scroll for them, and nothing in that area could
take the keyboard, so somebody without a pointer could not read a message that was out of sight.
The scrolling area takes focus now. No test was touched.

Nothing found two of anything: the lead strip is a button and hides while the panel is open, so the
panel's link to the pipeline is still the only one.

**What differs from the plan.**

- **The customer panel stands beside the whole conversation** — the draft and the composer too —
  where the plan left it beside the messages only. The first photograph showed the panel cut off
  half way down by the draft.
- **The composer's box is one line**, growing with what is typed where the browser can
  (`field-sizing`), and stays one line where it cannot.
- **Taking a conversation** (*Assign to me*) moved under the name, beside the word that says
  nobody has it: with an avatar in the row there was no room left for the name on a phone.
- **The template picker and the quick-reply menu** got their buttons, fields and corners; nothing
  else of theirs changed.
- **A long draft on a phone still takes most of the screen.** It is the thing to act on, and it
  folds away with its chevron; capping it would have put a scrolling box inside a scrolling box.

**Known, and left.**

| What | Step |
|---|---|
| `CustomerRow` and `LeadCard` still write their own band colours; `band.ts` waits for them | 4 |
| The fields inside *What we know* are as they were | 4, with the customer's own page |
| A sent message's ticks are still characters | When somebody minds |
| The flag is two letters wherever Windows draws it | Not ours to fix; a phone draws the flag |

---

# Step 4 — Every page on the canvas, and the customer screens

**Goal:** no page is a white rectangle from edge to edge any more, and no button or field in the
app is written out by hand. Customers, a customer's own page, the pipeline, tasks and My day are
drawn with the same avatars, pills and cards as the inbox.

**How this step was planned.** By counting again.

| What was looked at | What it found |
|---|---|
| Every class string with `min-h-11`, `bg-surface` or a bordered corner, outside what steps 2 and 3 redrew | 182 of them in 108 spellings. Forty spellings are plainly a field, a filled button or a quiet one, written out 105 times in 44 files |
| The pass for those, run without writing | 105 changes in 44 files. One string is a button in two files and an input in a third (`dev-login`): that file is put right by hand |
| How a page is put on the screen | Every page draws straight onto `<main>`, and its panels are the soft fill. Putting each page on the mint canvas panel by panel is a hundred small decisions; putting the page itself on one white sheet is one, and the soft panels inside it stay right |
| The inbox | It draws its own panels edge to edge, so it must not get the sheet. The sheet steps aside for it with `has-[>[data-inbox]]:contents` |
| The tests of `CustomerRow`, `LeadCard`, `StatTile` | None names a colour or a shape |

**Decisions made here.**

- **The page is a sheet.** On a desk `<main>` is the canvas and every page but the inbox sits on
  one white sheet with the 18 px corner. On a phone the sheet is the whole screen, as now: there
  is no room for a margin worth having.
- **A dialog is white**, like the sheet, and what a pointer is over is the soft fill — everywhere,
  in one word-for-word change.
- **`.card` is still not written.** The sheet is one element and says its own classes; nothing
  else needs the name yet.

## What Step 4 does not build

| Item | Why, and when |
|---|---|
| The dashboard's tiles, the settings' navigation, the sign-in pages' layout | Step 5. Their buttons and fields change here, with everybody else's |
| The fields inside *What we know* | Still their own small machine |
| Dragging a lead | It works as it did |

## File structure

| File | Responsibility |
|---|---|
| `apps/web/app/globals.css` | **Modify.** `btn-danger` |
| `apps/web/components/Shell.tsx`, `app/[tenant]/inbox/layout.tsx` | **Modify.** The sheet; the inbox outside it |
| `apps/web/components/Modal.tsx` | **Modify.** White |
| 44 files under `apps/web/app` and `apps/web/components` | **Modify,** by the pass: whole class strings to `field`, `btn`, `icon-btn` |
| `apps/web/components/crm/CustomerRow.tsx`, `LeadCard.tsx`, `BoardColumn.tsx` | **Modify.** Avatars, band pills, cards |
| `apps/web/app/[tenant]/customers/page.tsx`, `customers/[contactId]/page.tsx`, `pipeline/page.tsx` | **Modify.** The soft search; the customer's header |

---

## Task P1: The sheet

- [ ] `globals.css`: `.btn-danger` — the danger's own colour filled, the page's colour on it, a
  pair the palette's test already holds.
- [ ] `Shell.tsx`: `<main>` is `bg-ground min-w-0 md:p-4`, and inside it one element holds the
  page: `bg-background min-h-full p-4 pb-28 has-[>[data-inbox]]:contents md:rounded-[1.125rem]
  md:p-6`.
- [ ] `inbox/layout.tsx`: its root is `data-inbox`, and takes back only what `<main>` now gives:
  `md:-m-4`.
- [ ] `Modal.tsx`: `bg-surface` becomes `bg-background`.

## Task P2: The pass

- [ ] Saved outside the repository as `controls.mjs`, made as step 1's was: a list of whole class
  strings, each with what it becomes, run dry and then for real. What it turns into what:

| Written out as | Becomes |
|---|---|
| `min-h-11 rounded-md border border-border px-2 …` and its fourteen relatives | `field`, keeping any width, margin or text size of its own |
| `bg-accent min-h-11 rounded-md px-… font-medium text-on-accent …`, eight spellings | `btn btn-primary` |
| `min-h-11 rounded-md bg-danger … text-background …` | `btn btn-danger` |
| `hover:bg-background min-h-11 rounded-md px-3 …`, eight spellings; `"min-h-11 px-3"` and `"min-h-11 px-3 text-sm"` | `btn` or `btn btn-quiet` |
| `hover:bg-background min-h-11 min-w-11 rounded-md …` | `icon-btn` |
| `hover:bg-background`, wherever it is left | `hover:bg-surface` |

Expected, dry: `105 changes in 44 files`. Then `dev-login`'s two inputs, which the pass took for
buttons, are `field`.

## Task P3: The customer screens

- [ ] **`CustomerRow`**: the avatar with the flag, the name given no country; the band as `pill`
  from `band.ts`; *asked not to be messaged* as `pill pill-danger`.
- [ ] **`LeadCard`**: a white card with the 18 px corner on its soft column; a small avatar; the
  band and score as a pill. **`BoardColumn`**: the soft fill, the same corner.
- [ ] **Customers**: the search is `field field-soft`. **A customer's page**: a large avatar
  beside the name.

## Task P4: The whole check, the suite, and the look

- [ ] `npm run check:web`; `npm run build`; `E2E_DB_PORT=54432 npm run e2e` — 65 passed.
- [ ] The photographs: Customers, a customer, Pipeline, Tasks, My day — a desk in English, a phone
  in Arabic, one of them dark; and the dashboard and a settings form, to see what the pass did to
  screens this step did not otherwise touch.
- [ ] `## Step 4 review`, here; where it stands, in [11](../11-ui-refresh.md).

## Spec coverage (Step 4)

| Requirement | Task |
|---|---|
| [11](../11-ui-refresh.md) §3.4 — every repeated control behind one class | P2 |
| §5.2 — content on `ground`, with white cards | P1: one sheet a page, on a desk |
| §5.2 — Customers, the customer's page, Pipeline, Tasks, My day | P2, P3 |
| §5.4 — a dialog | P1 |

## Execution (Step 4)

Inline, straight on from step 3.
