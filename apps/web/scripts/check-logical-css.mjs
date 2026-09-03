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
];

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
