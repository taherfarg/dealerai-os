"use client";

import { useEffect, useState } from "react";
import { formatDuration } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

export type SlaState = "ok" | "due_soon" | "breached" | null;

const TONE: Record<"ok" | "due_soon" | "breached", string> = {
  ok: "text-muted",
  due_soon: "text-amber-600 dark:text-amber-400",
  breached: "text-red-600 dark:text-red-400",
};

/** A clock that advances on its own, so a timer counts up without a refetch. */
function useNow(everyMs = 30_000, fixed?: number): number {
  const [now, setNow] = useState(() => fixed ?? Date.now());
  useEffect(() => {
    if (fixed !== undefined) return;
    const tick = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(tick);
  }, [everyMs, fixed]);
  return now;
}

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
  const clock = useNow(30_000, now);
  if (!waitingSince || !state) return null;
  const seconds = Math.max(0, (clock - new Date(waitingSince).getTime()) / 1000);
  const label = {
    ok: t("inbox.waiting"),
    due_soon: t("inbox.dueSoon"),
    breached: t("inbox.missed"),
  }[state];
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium ${TONE[state]}`}
      aria-label={`${label} ${formatDuration(seconds)}`}
    >
      {label} {formatDuration(seconds)}
    </span>
  );
}
