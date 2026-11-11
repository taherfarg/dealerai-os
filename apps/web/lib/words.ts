import { en } from "@/messages/en";
import type { Locale, MessageKey } from "./i18n";

type T = (key: MessageKey) => string;

/**
 * A value the API stores as a code — a status, a source, a category — as a
 * word. One that has no word yet is shown as it is, or as the words the API
 * sent with it: a new status from Meta must not become a blank.
 */
export function word(t: T, group: string, value: string, fallback: string = value): string {
  const key = `${group}.${value.toLowerCase()}`;
  return key in en ? t(key as MessageKey) : fallback;
}

const NOUNS = {
  people: { en: ["person", "people"], ar: ["شخص واحد", "شخصان", "أشخاص", "شخصًا", "شخص"] },
  days: { en: ["day", "days"], ar: ["يوم واحد", "يومان", "أيام", "يومًا", "يوم"] },
  passages: { en: ["passage", "passages"], ar: ["مقطع واحد", "مقطعان", "مقاطع", "مقطعًا", "مقطع"] },
} as const;

/**
 * A count with its noun. Arabic has a form for one, for two, for three to ten,
 * for eleven to ninety-nine, and for the hundreds; `Intl.PluralRules` knows
 * which. Nought takes the last, as CLDR writes it.
 */
export function counted(locale: Locale, n: number, noun: keyof typeof NOUNS): string {
  if (locale === "en") return `${n} ${NOUNS[noun].en[n === 1 ? 0 : 1]}`;
  const [one, two, few, many, other] = NOUNS[noun].ar;
  const form = new Intl.PluralRules("ar").select(n);
  if (form === "one") return one;
  if (form === "two") return two;
  return `${n} ${form === "few" ? few : form === "many" ? many : other}`;
}

/**
 * A line the thread writes about itself — assigned, closed, a lead moved — in
 * the reader's language. The API keeps what kind of thing happened and, where
 * there is one, the name it happened to; an event with no words here, or one
 * written before names were kept apart, is shown as the sentence it came with.
 */
export function eventText(t: T, event: Record<string, unknown> | null | undefined): string {
  const written = typeof event?.text === "string" ? event.text : "";
  const key = `event.${String(event?.type ?? "")}`;
  if (!(key in en)) return written;
  const said = t(key as MessageKey);
  if (!said.includes("{name}")) return said;
  return typeof event?.name === "string" ? said.replace("{name}", event.name) : written;
}

/**
 * Why a draft was not shown. The API writes each refusal as `check: detail`;
 * the detail is for the model's second attempt and the log, and what a
 * salesperson needs is which check it was — once each.
 */
export function blockedReasons(t: T, raw: string): string {
  const said = raw.split("; ").map((part) => {
    const check = part.split(": ", 1)[0];
    return word(t, "draft.blocked", check, part);
  });
  return [...new Set(said)].join(" · ");
}
