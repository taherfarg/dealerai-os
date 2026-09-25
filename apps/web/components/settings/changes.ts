/**
 * Only what changed, so a save is exactly what the person did — and a
 * manager's save never carries a key she may not write, which would refuse
 * the whole save (routes/settings.WRITERS). A key set back to null is a
 * change: that is how the default team is cleared.
 */
export function changes<T extends object>(saved: T, draft: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(draft).filter(
      ([key, value]) => JSON.stringify(saved[key as keyof T]) !== JSON.stringify(value),
    ),
  ) as Partial<T>;
}
