"use client";

import { Icon } from "@/components/Icon";
import { useNow } from "@/lib/clock";
import { formatDuration } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

export type SlaState = "ok" | "due_soon" | "breached" | null;

// Three states, three looks ([11] § 5.1): plain while the customer is within
// the target, a warning when it is near, danger when it is missed.
const TONE: Record<"ok" | "due_soon" | "breached", string> = {
  ok: "",
  due_soon: "pill-warning",
  breached: "pill-danger",
};

/**
 * How long this customer has been waiting.
 *
 * The state is said in words as well as colour: a colour-blind manager and a
 * screen reader both have to be able to tell a missed target from a fine one.
 */
export function WaitingTimer({
  waitingSince,
  state,
  now,
}: {
  waitingSince: string | null;
  state: SlaState;
  /** Fixed clock, for tests. */
  now?: number;
}) {
  const t = useT();
  const locale = useLocale();
  const clock = useNow(30_000, now);
  if (!waitingSince || !state) return null;
  const seconds = Math.max(0, (clock - new Date(waitingSince).getTime()) / 1000);
  // It looks again every thirty seconds, so past the first minute a count of
  // seconds is a number that is already wrong. Whole minutes, then.
  const waited = formatDuration(seconds < 60 ? seconds : Math.floor(seconds / 60) * 60, locale);
  const label = {
    ok: t("inbox.waiting"),
    due_soon: t("inbox.dueSoon"),
    breached: t("inbox.missed"),
  }[state];
  return (
    <span className={`pill ${TONE[state]}`} aria-label={`${label} ${waited}`}>
      <Icon name={state === "breached" ? "alert" : "clock"} size={13} />
      {label} {waited}
    </span>
  );
}
