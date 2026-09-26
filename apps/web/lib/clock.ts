"use client";

import { useEffect, useState } from "react";

/**
 * A clock that advances on its own.
 *
 * Reading Date.now() while rendering makes a component impure — and a waiting
 * timer that only moves when something else refetches is worse than useless to
 * a manager watching it.
 */
export function useNow(everyMs = 30_000, fixed?: number): number {
  const [now, setNow] = useState(() => fixed ?? Date.now());
  useEffect(() => {
    if (fixed !== undefined) return;
    const tick = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(tick);
  }, [everyMs, fixed]);
  return now;
}
