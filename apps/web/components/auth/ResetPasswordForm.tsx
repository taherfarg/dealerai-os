"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { useT } from "@/lib/i18n-client";
import { createClient } from "@/lib/supabase/client";

const FIELD = "field";

/**
 * A new password, for somebody the link in their email has just signed in
 * ([08] § 14). The page is behind the gate: opened cold, it leads to sign-in.
 */
export function ResetPasswordForm() {
  const t = useT();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rule = useId();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.updateUser({ password });
    if (error) {
      // Ours, in the reader's language, in place of Supabase's English.
      setError(t("auth.resetFailed"));
      setBusy(false);
      return;
    }
    // Already signed in: on into the app, which knows where they belong.
    router.push("/");
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full flex-col gap-4">
      <h1 className="text-accent-ink text-2xl font-semibold tracking-tight">{t("auth.resetTitle")}</h1>

      <div className="flex flex-col gap-1 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-muted">{t("auth.newPassword")}</span>
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            dir="ltr"
            aria-describedby={rule}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={FIELD}
          />
        </label>
        <span id={rule} className="text-muted text-xs">
          {t("auth.passwordRule")}
        </span>
      </div>

      {error && (
        <div className="flex flex-col gap-1 text-sm">
          <p role="alert" className="text-danger">
            {error}
          </p>
          {/* The link was old, or was opened twice: the way to another. */}
          <Link
            href="/forgot-password"
            className="inline-flex min-h-11 items-center self-start underline"
          >
            {t("auth.forgotTitle")}
          </Link>
        </div>
      )}

      <button
        type="submit"
        disabled={busy}
        className="btn btn-primary"
      >
        {busy ? t("auth.saving") : t("auth.savePassword")}
      </button>
    </form>
  );
}
