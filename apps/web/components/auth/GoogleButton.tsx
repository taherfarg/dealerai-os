"use client";

import { useT } from "@/lib/i18n-client";
import { createClient } from "@/lib/supabase/client";

/** Google through Supabase Auth. It comes back to /auth/callback with a
 *  one-time code, and on from there to `next`. */
export function GoogleButton({ next }: { next: string }) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={() =>
        createClient().auth.signInWithOAuth({
          provider: "google",
          options: {
            redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
          },
        })
      }
      className="btn"
    >
      {t("auth.google")}
    </button>
  );
}
