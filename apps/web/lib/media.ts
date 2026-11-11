"use client";

import { useSyncExternalStore } from "react";

/** Tailwind's `lg`, where the customer panel becomes a column beside the thread. */
const WIDE = "(min-width: 64rem)";

const watch = (changed: () => void) => {
  const media = window.matchMedia?.(WIDE);
  media?.addEventListener("change", changed);
  return () => media?.removeEventListener("change", changed);
};

/**
 * Whether the screen is wide enough for two columns, as CSS itself decides it.
 *
 * For the one thing CSS cannot do: something that is a column on a desk and a
 * dialog on a phone has to be opened differently, not only drawn differently.
 */
export function useWide(): boolean {
  return useSyncExternalStore(
    watch,
    () => window.matchMedia?.(WIDE).matches ?? false,
    () => false,
  );
}
