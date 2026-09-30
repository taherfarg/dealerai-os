"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { safeNext } from "@/lib/auth/next";
import { useT } from "@/lib/i18n-client";
import { createClient } from "@/lib/supabase/client";

const FIELD = "border-border bg-background min-h-11 rounded-md border px-3";

/** Email and password through Supabase Auth ([08] § 14). */
export function LoginForm() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.signInWithPassword({ email, password });
    if (error) {
      // Supabase already returns "Invalid login credentials" without saying
      // which half was wrong. Do not improve on that — it would turn the form
      // into an account-enumeration oracle.
      setError(error.message);
      setBusy(false);
      return;
    }
    router.push(next);
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full flex-col gap-4">
      <div>
        <h1 className="text-brand text-2xl font-semibold tracking-tight">DealerAI OS</h1>
        <p className="text-muted mt-1 text-sm">{t("auth.signInTitle")}</p>
      </div>

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

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("auth.password")}</span>
        <input
          type="password"
          required
          autoComplete="current-password"
          dir="ltr"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className={FIELD}
        />
      </label>

      {error && (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="bg-brand min-h-11 rounded-md px-3 text-sm font-medium text-white disabled:opacity-60"
      >
        {busy ? t("auth.working") : t("auth.signIn")}
      </button>

      <p className="text-muted text-sm">
        {t("auth.noAccount")}{" "}
        <Link href={`/signup?next=${encodeURIComponent(next)}`} className="underline">
          {t("auth.createAccount")}
        </Link>
      </p>
    </form>
  );
}
