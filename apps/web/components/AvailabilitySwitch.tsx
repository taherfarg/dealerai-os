"use client";

import { useMe, useSetAcceptingChats } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * Whether new conversations may be assigned to me. Assignment reads it immediately.
 *
 * `compact` is its shape in the rail: the dot over its words ([11] § 4).
 */
export function AvailabilitySwitch({ compact = false }: { compact?: boolean }) {
  const t = useT();
  const me = useMe();
  const setAccepting = useSetAcceptingChats();
  if (!me.data) return null;
  const on = me.data.accepting_chats;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={setAccepting.isPending}
      onClick={() => setAccepting.mutate(!on)}
      className={
        compact
          ? "text-muted hover:bg-surface flex min-h-11 w-full flex-col items-center justify-center gap-1 rounded-2xl px-1 py-1.5 text-center text-[11px] leading-4 disabled:opacity-60 rtl:text-xs"
          : "hover:bg-background flex min-h-11 w-full items-center gap-2 rounded-md px-3 py-2 text-sm disabled:opacity-60"
      }
    >
      <span aria-hidden className={`size-2 rounded-full ${on ? "bg-success" : "bg-muted"}`} />
      {on ? t("availability.taking") : t("availability.away")}
    </button>
  );
}
