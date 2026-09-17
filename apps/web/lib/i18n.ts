import { ar } from "@/messages/ar";
import { en } from "@/messages/en";

export const LOCALES = ["en", "ar"] as const;
export type Locale = (typeof LOCALES)[number];

export const RTL_LOCALES = new Set<Locale>(["ar"]);

export function dirFor(locale: Locale): "ltr" | "rtl" {
  return RTL_LOCALES.has(locale) ? "rtl" : "ltr";
}

/**
 * The UI message catalogue, one file per language under messages/.
 *
 * A full i18n library buys plurals, dates and namespacing we do not need yet.
 * The product's real multilingual work is in customer conversations and AI
 * drafts, which never touch this file. messages/ar.ts `satisfies` the English
 * keys, so a missing translation fails the typecheck.
 */
const MESSAGES = { en, ar } as const;

export type MessageKey = keyof typeof en;

export function t(locale: Locale, key: MessageKey): string {
  return MESSAGES[locale][key] ?? en[key] ?? key;
}
