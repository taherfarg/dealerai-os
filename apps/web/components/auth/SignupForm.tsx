"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";
import { safeNext } from "@/lib/auth/next";
import { useT } from "@/lib/i18n-client";
import { createClient } from "@/lib/supabase/client";
import { GoogleButton } from "./GoogleButton";

const FIELD = "border-border bg-background min-h-11 rounded-md border px-3";

/** An account through Supabase Auth, confirmed by email when the project asks
 *  for it ([08] § 14). An invitation's address arrives pre-filled. */
export function SignupForm() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [name, setName] = useState("");
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const rule = useId();

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const { data, error } = await createClient().auth.signUp({
      email,
      password,
      options: {
        data: { full_name: name.trim() },
        emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    if (error) {
      setError(error.message);
      setBusy(false);
      return;
    }
    if (data.session) {
      // Confirmation is off on this project: they are in already.
      router.push(next);
      router.refresh();
      return;
    }
    // With confirmation on, Supabase answers an address that already has an
    // account exactly as it answers a new one. So does this.
    setSent(true);
  }

  if (sent) {
    return (
      <p role="status" className="text-sm">
        {t("auth.checkEmail")}
      </p>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full flex-col gap-4">
      <h1 className="text-brand text-2xl font-semibold tracking-tight">DealerAI OS</h1>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("auth.name")}</span>
        <input
          required
          autoComplete="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={FIELD}
        />
      </label>

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

      <div className="flex flex-col gap-1 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-muted">{t("auth.password")}</span>
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
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="bg-brand min-h-11 rounded-md px-3 text-sm font-medium text-white disabled:opacity-60"
      >
        {busy ? t("auth.creating") : t("auth.createAccount")}
      </button>

      <p className="text-muted text-center text-xs">{t("auth.or")}</p>
      <GoogleButton next={next} />

      <p className="text-muted text-sm">
        {t("auth.haveAccount")}{" "}
        <Link href={`/login?next=${encodeURIComponent(next)}`} className="underline">
          {t("auth.signIn")}
        </Link>
      </p>
    </form>
  );
}
