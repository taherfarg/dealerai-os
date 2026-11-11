import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// __dirname, not import.meta.url: under jsdom that is not a file: address.
const CSS = readFileSync(resolve(__dirname, "./globals.css"), "utf-8");
const DARK = "@media (prefers-color-scheme: dark)";

/** `--name: #rrggbb`, as written, by name. */
function values(css: string): Record<string, string> {
  return Object.fromEntries(
    [...css.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})\b/g)].map(
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
  ["foreground", "ground"],
  ["foreground", "surface"],
  ["foreground", "accent-soft"],
  ["foreground", "warning-soft"],
  ["foreground", "info-soft"],
  ["foreground", "danger-soft"],
  ["muted", "background"],
  ["muted", "ground"],
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
  // An avatar's initials on its own tint.
  ...Array.from({ length: 7 }, (_, n) => [`tint-${n}-ink`, `tint-${n}`] as const),
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
