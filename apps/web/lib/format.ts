/**
 * Money and time for display. Latin digits in both languages: prices and phone
 * numbers are read the same way everywhere in the UAE, and a price that changes
 * digit shape between languages invites a double-take on the one number that
 * must not be misread.
 */
export type Money = { amount_minor: number; currency: string };

export function formatMoney(money: Money): string {
  const major = money.amount_minor / 100;
  const digits = Number.isInteger(major) ? 0 : 2;
  const amount = major.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${money.currency} ${amount}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = Math.round(seconds % 60);
    return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

/** Compact age for lists: "<1m", "3m", "2h", "5d", then a date. */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "<1m";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)}d`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** How long until a moment in the future: "20h", "3m", or "0m" once it has passed. */
export function formatUntil(iso: string, now: Date = new Date()): string {
  const seconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  return seconds <= 0 ? "0m" : formatDuration(seconds);
}

/** A date and time in the tenant's timezone, never the viewer's. */
export function formatDateTime(iso: string, timeZone: string, locale: "en" | "ar" = "en"): string {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-AE-u-nu-latn" : "en-GB", {
    timeZone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function countryFlag(iso2: string | null): string {
  if (!iso2 || !/^[A-Za-z]{2}$/.test(iso2)) return "";
  return String.fromCodePoint(
    ...[...iso2.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65),
  );
}
