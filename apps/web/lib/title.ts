/**
 * The tab title with the unread count on the front.
 *
 * Applying it to its own output has to give the same string back: the count is
 * re-applied whenever anything else writes the title, so a version that kept
 * stacking prefixes would loop.
 */
export function titleWithUnread(unread: number, current: string): string {
  const base = current.replace(/^\(\d+\) /, "");
  return unread ? `(${unread}) ${base}` : base;
}
