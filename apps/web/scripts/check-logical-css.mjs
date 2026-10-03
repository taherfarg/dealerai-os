/**
 * Fails if any component uses a physically-directional Tailwind class.
 *
 * RTL in this app works because every directional style is logical — ms/me,
 * ps/pe, border-s/border-e, text-start/text-end — so `dir="rtl"` mirrors the
 * whole layout with no per-component overrides. One `ml-4` breaks that
 * silently: it looks right in English and wrong in Arabic, and nobody notices
 * until a dealer in Dubai does.
 *
 * A screenshot proves one page once. This proves every page, forever.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

// fileURLToPath, not .pathname: the repo path contains a space, which arrives
// percent-encoded and produces a directory that does not exist.
const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SCAN = ["app", "components"];

// Word-boundary anchored so `text-start` and `border-solid` do not match.
const BANNED = [
  [/(?<![\w-])(ml|mr|pl|pr)-[\w.[\]/-]+/g, "use ms-/me-/ps-/pe- (logical) instead"],
  [/(?<![\w-])text-(left|right)(?![\w-])/g, "use text-start / text-end"],
  [/(?<![\w-])(left|right)-[\w.[\]/-]+/g, "use start-/end-"],
  [/(?<![\w-])border-(l|r)(?![\w-])/g, "use border-s / border-e"],
  [/(?<![\w-])rounded-(l|r|tl|tr|bl|br)-/g, "use logical rounded-s/-e/-ss/-se/-es/-ee"],
  // Logical in Tailwind 4, and still wrong: it puts a margin on each child, and
  // a child with a direction of its own has its own idea of which side that is.
  [/(?<![\w-])space-x-[\w.[\]/-]+/g, "use gap-* on the parent"],
];

// The net has to hold before it is trusted: each of these must be caught, and
// each of these let through.
for (const [sample, caught] of [
  ["ml-4", true],
  ["text-left", true],
  ["right-0", true],
  ["border-l", true],
  ["rounded-tl-md", true],
  ["space-x-4", true],
  ["ms-4", false],
  ["text-start", false],
  ["gap-x-4", false],
  ["border-solid", false],
]) {
  if (BANNED.some(([re]) => sample.match(re) !== null) !== caught) {
    throw new Error(`check-logical-css: ${sample} should ${caught ? "" : "not "}be refused`);
  }
}

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.(tsx?|css)$/.test(p)) yield p;
  }
}

const problems = [];
for (const base of SCAN) {
  for (const file of walk(join(ROOT, base))) {
    const text = readFileSync(file, "utf8");
    text.split("\n").forEach((line, i) => {
      // Comments explain the rule; they are not violations of it.
      if (/^\s*(\/\/|\*|\/\*)/.test(line)) return;
      for (const [re, hint] of BANNED) {
        for (const m of line.matchAll(re)) {
          problems.push(`${relative(ROOT, file)}:${i + 1}  ${m[0]}  -> ${hint}`);
        }
      }
    });
  }
}

if (problems.length) {
  console.error("Physical direction classes found — these break RTL:\n");
  for (const p of problems) console.error("  " + p);
  console.error(`\n${problems.length} problem(s).`);
  process.exit(1);
}
console.log("logical-css: ok — no physical direction classes");
