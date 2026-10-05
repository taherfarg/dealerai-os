"use client";

import Link from "next/link";
import { useState } from "react";
import { useT } from "@/lib/i18n-client";
import { createClient } from "@/lib/supabase/client";

const FIELD = "border-border bg-background min-h-11 rounded-md border px-3";

/** A link to choose a new password, sent to an address ([08] § 14). */
export function ForgotPasswordForm() {
  const t = useT();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      // The link comes back through /auth/callback, which signs them in, to
      // the page where the new password is typed.
      await createClient().auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent("/reset-password")}`,
      });
    } catch {
      // Answered below, like every other outcome.
    }
    // One sentence whatever happened — sent, refused, no such address. Which
    // addresses have an account is what the sign-in form will not say, and
    // this form is a door into the same room.
    setSent(true);
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <div>
        <h1 className="text-accent-ink text-2xl font-semibold tracking-tight">{t("auth.forgotTitle")}</h1>
        {!sent && <p className="text-muted mt-1 text-sm">{t("auth.forgotIntro")}</p>}
      </div>

      {sent ? (
        <p role="status" className="text-sm">
          {t("auth.linkSent")}
        </p>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">{t("auth.email")}</span>
            <input
              type="email"
              required
              autoComplete="email"
              dir="ltr"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className={FIELD}
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="bg-accent min-h-11 rounded-md px-3 text-sm font-medium text-on-accent disabled:opacity-60"
          >
            {busy ? t("auth.sending") : t("auth.sendLink")}
          </button>
        </form>
      )}

      <Link
        href="/login"
        className="text-muted inline-flex min-h-11 items-center self-start text-sm underline"
      >
        {t("auth.backToSignIn")}
      </Link>
    </div>
  );
}
