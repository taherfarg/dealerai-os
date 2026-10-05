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
