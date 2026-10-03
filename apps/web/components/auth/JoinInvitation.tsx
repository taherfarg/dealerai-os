"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { acceptInvitation } from "@/lib/api/joining";
import { signOut } from "@/lib/auth/sign-out";
import { signedInEmail } from "@/lib/auth/token";
import { DEV_AUTH } from "@/lib/dev-auth";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";
import { readInvitation } from "@/lib/invitation";

const BUTTON = "bg-brand min-h-11 rounded-md px-3 text-sm font-medium text-white disabled:opacity-60";
const LINK = "border-border flex min-h-11 items-center justify-center rounded-md border px-3 text-sm";

/**
 * Joining a workspace from an invitation link ([08] § 14). The link says who
 * is invited, where and as what; the API decides — this page only says it
 * kindly first, and keeps the invitation through sign-up or sign-in.
 */
export function JoinInvitation({ token }: { token: string }) {
  const t = useT();
  const router = useRouter();
  const invitation = useMemo(() => readInvitation(token), [token]);
  /** undefined while we look, null when nobody is signed in. */
  const [current, setCurrent] = useState<string | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    signedInEmail().then(setCurrent, () => setCurrent(null));
  }, []);

  if (!invitation || invitation.expired) {
    return (
      <div className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">{t("accept.title")}</h1>
        <p role="alert" className="text-sm">
          {invitation ? t("accept.expired") : t("accept.invalid")}
        </p>
      </div>
    );
  }

  const back = `/accept-invite?token=${encodeURIComponent(token)}`;
  const create = DEV_AUTH
    ? `/dev-login?next=${encodeURIComponent(back)}`
    : `/signup?email=${encodeURIComponent(invitation.email)}&next=${encodeURIComponent(back)}`;
  const signIn = DEV_AUTH
    ? `/dev-login?next=${encodeURIComponent(back)}`
    : `/login?next=${encodeURIComponent(back)}`;

  async function join() {
    setBusy(true);
    setError(null);
    try {
      const joined = await acceptInvitation(token);
      router.push(`/${joined.tenant_slug}/inbox`);
      router.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("settings.saveFailed"));
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-muted text-sm">{t("accept.invitedTo")}</p>
        <h1 className="text-xl font-semibold" dir="auto">
          {invitation.workspace}
        </h1>
        <p className="text-muted mt-1 text-sm">
          {t("accept.role")} {t(`role.${invitation.role}` as MessageKey)}
        </p>
      </div>

      {current === undefined && <p className="text-muted text-sm">…</p>}

      {current === null && (
        <div className="flex flex-col gap-2">
          <Link href={create} className={LINK}>
            {t("accept.createAccount")}
          </Link>
          <Link href={signIn} className={LINK}>
            {t("accept.signIn")}
          </Link>
        </div>
      )}

      {/* Compared here only to say so kindly: the API is what refuses. */}
      {current && current !== invitation.email && (
        <div className="flex flex-col gap-2 text-sm">
          <p>
            {t("accept.forEmail")} <span dir="ltr">{invitation.email}</span>
          </p>
          <p className="text-muted">
            {t("accept.signedInAs")} <span dir="ltr">{current}</span>
          </p>
          {/* Back to this invitation, to accept it with the right address. */}
          <button
            type="button"
            onClick={() => void signOut().then(() => window.location.reload())}
            className={BUTTON}
          >
            {t("accept.signOut")}
          </button>
        </div>
      )}

      {current && current === invitation.email && (
        <button type="button" onClick={join} disabled={busy} className={BUTTON}>
          {busy ? t("accept.joining") : t("accept.join")}
        </button>
      )}

      {error && (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      )}
    </div>
  );
}
