"use client";

import { useMe, useSetAcceptingChats } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/** Whether new conversations may be assigned to me. Assignment reads it immediately. */
export function AvailabilitySwitch() {
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
      className="hover:bg-background flex min-h-11 w-full items-center gap-2 rounded-md px-3 py-2 text-sm disabled:opacity-60"
    >
      <span aria-hidden className={`size-2 rounded-full ${on ? "bg-success" : "bg-muted"}`} />
      {on ? t("availability.taking") : t("availability.away")}
    </button>
  );
}
