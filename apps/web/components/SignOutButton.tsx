"use client";

import { useState } from "react";
import { signOut } from "@/lib/auth/sign-out";
import { useT } from "@/lib/i18n-client";

/** The way out. It leaves by loading the front door afresh rather than by a
 *  client-side move, so nothing a customer said stays in this tab's memory. */
export function SignOutButton() {
  const t = useT();
  const [leaving, setLeaving] = useState(false);
  return (
    <button
      type="button"
      disabled={leaving}
      onClick={() => {
        setLeaving(true);
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a whole page load, not the router, is what empties this tab's memory
        void signOut().then(() => window.location.assign("/"));
      }}
      className="text-muted hover:bg-background flex min-h-11 items-center rounded-md px-3 py-2 text-start text-sm whitespace-nowrap disabled:opacity-50"
    >
      {t("auth.signOut")}
    </button>
  );
}
