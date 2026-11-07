/**
 * Calendar dates as "YYYY-MM-DD" strings, done in UTC so no browser timezone
 * or daylight-saving change can move a day. The dealer's own clock is the
 * API's business: it takes a day and a time and owns the zone.
 */

const at = (iso: string) => new Date(`${iso}T00:00:00Z`);
const iso = (d: Date) => d.toISOString().slice(0, 10);

export function addDays(day: string, n: number): string {
  const d = at(day);
  d.setUTCDate(d.getUTCDate() + n);
  return iso(d);
}

/** The Monday on or before `day` — the UAE's working week starts there. */
export function weekStart(day: string): string {
  const weekday = (at(day).getUTCDay() + 6) % 7; // Monday 0 … Sunday 6
  return addDays(day, -weekday);
}

export function monthStart(day: string): string {
  return `${day.slice(0, 7)}-01`;
}

/** The first and last day a view shows. A month is drawn from the Monday of
 *  its first week, so its grid lines up with the week view's columns. */
export function span(view: "week" | "month", day: string): [string, string] {
  if (view === "week") {
    const start = weekStart(day);
    return [start, addDays(start, 6)];
  }
  const first = monthStart(day);
  const next = monthStart(addDays(first, 31));
  return [weekStart(first), addDays(next, -1)];
}

/** Where the arrows go: a week or a month on, or back. */
export function step(view: "week" | "month", day: string, direction: 1 | -1): string {
  if (view === "week") return addDays(weekStart(day), 7 * direction);
  const first = monthStart(day);
  return direction === 1 ? monthStart(addDays(first, 31)) : monthStart(addDays(first, -1));
}

export function today(): string {
  return iso(new Date(Date.now() - new Date().getTimezoneOffset() * 60_000));
}
