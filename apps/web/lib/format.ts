import type { Locale } from "./i18n";

/**
 * Money and time for display. Latin digits in both languages: prices and phone
 * numbers are read the same way everywhere in the UAE, and a price that changes
 * digit shape between languages invites a double-take on the one number that
 * must not be misread.
 *
 * The words around the digits are the reader's. Every time formatter takes the
 * language, and takes it as a required argument: an optional one leaves English
 * wherever nobody looked.
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

const DATE_LOCALE = { en: "en-GB", ar: "ar-AE-u-nu-latn" } as const;

// Arabic abbreviates a unit to its first letter, as WhatsApp does: ثانية، دقيقة، ساعة، يوم.
// With a space, because a letter set against a digit reads as one token.
const UNITS = {
  en: { s: "s", m: "m", h: "h", d: "d", gap: "" },
  ar: { s: "ث", m: "د", h: "س", d: "ي", gap: " " },
} as const;

const AHEAD = { en: "in", ar: "بعد" } as const;

const WEEK = 7 * 86400;

const some = (n: number, unit: "s" | "m" | "h" | "d", locale: Locale) =>
  `${n}${UNITS[locale].gap}${UNITS[locale][unit]}`;

export function formatDuration(seconds: number, locale: Locale): string {
  if (seconds < 60) return some(Math.round(seconds), "s", locale);
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = Math.round(seconds % 60);
    return rest ? `${some(minutes, "m", locale)} ${some(rest, "s", locale)}` : some(minutes, "m", locale);
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${some(hours, "h", locale)} ${some(rest, "m", locale)}` : some(hours, "h", locale);
}

/** Between a minute and a week, in its largest unit: "3m", "2h", "5d". */
function span(seconds: number, locale: Locale): string {
  if (seconds < 3600) return some(Math.floor(seconds / 60), "m", locale);
  if (seconds < 86400) return some(Math.floor(seconds / 3600), "h", locale);
  return some(Math.floor(seconds / 86400), "d", locale);
}

const shortDate = (iso: string, locale: Locale) =>
  new Date(iso).toLocaleDateString(DATE_LOCALE[locale], { day: "numeric", month: "short" });

/** Compact age for lists: "<1m", "3m", "2h", "5d", then a date. */
export function formatRelative(iso: string, locale: Locale, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  // Not "<1 د": a sign beside Arabic is mirrored, and reads as more than a minute.
  if (seconds < 60) return locale === "ar" ? "الآن" : "<1m";
  return seconds < WEEK ? span(seconds, locale) : shortDate(iso, locale);
}

/**
 * When something is due: an age once it has passed, and how far ahead while it
 * has not — "in 3h". Its own function, because an age must never run ahead: a
 * message from a phone whose clock is two minutes fast was not sent "in 2m".
 */
export function formatDue(iso: string, locale: Locale, now: Date = new Date()): string {
  const ahead = (new Date(iso).getTime() - now.getTime()) / 1000;
  if (ahead < 60) return formatRelative(iso, locale, now);
  return ahead < WEEK ? `${AHEAD[locale]} ${span(ahead, locale)}` : shortDate(iso, locale);
}

/** How long until a moment in the future: "20h", "3m", or "0m" once it has passed. */
export function formatUntil(iso: string, locale: Locale, now: Date = new Date()): string {
  const seconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  return seconds <= 0 ? some(0, "m", locale) : formatDuration(seconds, locale);
}

/** A date and time in the tenant's timezone, never the viewer's. */
export function formatDateTime(iso: string, timeZone: string, locale: Locale): string {
  return new Intl.DateTimeFormat(DATE_LOCALE[locale], {
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

/** A country as a word, in the reader's language. `Intl` knows them all. */
export function countryName(iso2: string | null, locale: Locale): string {
  if (!iso2 || !/^[A-Za-z]{2}$/.test(iso2)) return "";
  try {
    return (
      new Intl.DisplayNames([DATE_LOCALE[locale]], { type: "region" }).of(iso2.toUpperCase()) ?? ""
    );
  } catch {
    return "";
  }
}
