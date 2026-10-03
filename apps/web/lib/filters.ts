"use client";

import { usePathname, useSearchParams } from "next/navigation";

/**
 * Filters that live in the URL.
 *
 * A list somebody sends a colleague has to be the list they were looking at,
 * and a reload has to land on the same rows — which means the state belongs in
 * the address bar rather than in a component.
 */
export function readFilters<T extends Record<string, string>>(
  defaults: T,
  params: URLSearchParams,
): T {
  const values = { ...defaults } as Record<string, string>;
  for (const key of Object.keys(defaults)) {
    const found = params.get(key);
    if (found !== null) values[key] = found;
  }
  return values as T;
}

/**
 * The next query string after applying `changes`.
 *
 * A value equal to its default is removed rather than written, so a shared link
 * carries only what somebody actually chose. Parameters this list knows nothing
 * about are left alone: another feature may own them.
 */
export function nextQuery<T extends Record<string, string>>(
  defaults: T,
  params: URLSearchParams,
  changes: Partial<T>,
): string {
  const next = new URLSearchParams(params.toString());
  for (const [key, value] of Object.entries(changes)) {
    if (!value || value === defaults[key]) next.delete(key);
    else next.set(key, String(value));
  }
  return next.toString();
}

export function useFilters<T extends Record<string, string>>(
  defaults: T,
): readonly [T, (changes: Partial<T>) => void] {
  const pathname = usePathname();
  const params = useSearchParams();
  const values = readFilters(defaults, new URLSearchParams(params.toString()));
  const set = (changes: Partial<T>) => {
    // From the address as it is now, not as it was when this was drawn: a
    // change made a moment after another — a search typed straight after a tab
    // was pressed, a letter after a letter — must build on it, not undo it.
    const query = nextQuery(defaults, new URLSearchParams(window.location.search), changes);
    // The History API, which Next keeps in step with useSearchParams: a filter
    // is read in the browser, so there is nothing to ask the server for, and
    // the address changes at once. replace, not push: filtering is not
    // something to press Back through.
    window.history.replaceState(null, "", query ? `${pathname}?${query}` : pathname);
  };
  return [values, set] as const;
}
