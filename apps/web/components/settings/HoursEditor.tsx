"use client";

import type { SalesSettings } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

export type Hours = NonNullable<SalesSettings["business_hours"]>;
type Day = Hours[string];

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
/** What switching hours on starts from: a showroom week, Sunday off. */
const SHOWROOM_DAY: Day = { open: "09:00", close: "21:00" };

/** The API says "09:00:00", the input says "09:00": the same minute. */
const minute = (value: string) => value.slice(0, 5);

/** Days that close before they open — which the API refuses, and which would
 *  make every reply on that day late for ever. */
export function badDays(hours: Hours): string[] {
  return Object.entries(hours)
    .filter(([, day]) => minute(day.close) <= minute(day.open))
    .map(([name]) => name);
}

/**
 * Opening hours, which is what a response target counts in. No hours at all
 * means always open — said on screen, because an empty week reads like a
 * closed one.
 */
export function HoursEditor({
  value,
  onChange,
}: {
  value: Hours;
  onChange: (next: Hours) => void;
}) {
  const t = useT();
  const keeps = Object.keys(value).length > 0;
  const bad = new Set(badDays(value));
  const setDay = (day: string, next: Day | null) => {
    const copy = { ...value };
    if (next) copy[day] = next;
    else delete copy[day];
    onChange(copy);
  };

  return (
    <fieldset>
      <legend className="text-sm font-semibold">{t("routing.hours")}</legend>
      <label className="mt-1 flex min-h-11 items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={keeps}
          onChange={(event) =>
            onChange(
              event.target.checked
                ? Object.fromEntries(DAYS.slice(0, 6).map((day) => [day, SHOWROOM_DAY]))
                : {},
            )
          }
        />
        {t("routing.keepsHours")}
      </label>
      {!keeps && <p className="text-muted text-xs">{t("routing.alwaysOpen")}</p>}
      {keeps && (
        <ul className="mt-1">
          {DAYS.map((day) => {
            const hours = value[day];
            const name = t(`day.${day}` as MessageKey);
            return (
              <li key={day} className="flex flex-wrap items-center gap-2 py-1 text-sm">
                <label className="flex min-h-11 w-32 items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(hours)}
                    onChange={(event) => setDay(day, event.target.checked ? SHOWROOM_DAY : null)}
                  />
                  {name}
                </label>
                {hours ? (
                  <>
                    <input
                      type="time"
                      aria-label={`${name} ${t("routing.opens")}`}
                      value={minute(hours.open)}
                      aria-invalid={bad.has(day)}
                      onChange={(event) => setDay(day, { ...hours, open: event.target.value })}
                      className="min-h-11 rounded-md border border-border px-2"
                    />
                    <input
                      type="time"
                      aria-label={`${name} ${t("routing.closes")}`}
                      value={minute(hours.close)}
                      aria-invalid={bad.has(day)}
                      onChange={(event) => setDay(day, { ...hours, close: event.target.value })}
                      className="min-h-11 rounded-md border border-border px-2"
                    />
                    {bad.has(day) && (
                      <span role="alert" className="text-xs text-danger">
                        {t("routing.closeAfterOpen")}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-muted">{t("routing.closedDay")}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}
