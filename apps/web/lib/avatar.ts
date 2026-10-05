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
