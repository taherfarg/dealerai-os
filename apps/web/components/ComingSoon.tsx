"use client";

import { useMe } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

/** A placeholder that also proves who the API thinks you are. */
export function ComingSoon({ titleKey }: { titleKey: MessageKey }) {
  const t = useT();
  const me = useMe();
  return (
    <section className="flex flex-col gap-2">
      <h1 className="text-2xl font-semibold tracking-tight">{t(titleKey)}</h1>
      <p className="text-muted text-sm">{t("common.comingSoon")}</p>
      {me.data && (
        <p className="text-muted text-xs" data-testid="whoami">
          {me.data.user.name} · {me.data.role} · {me.data.scope}
        </p>
      )}
      {me.isError && (
        <p role="alert" className="text-danger text-sm">
          {me.error.message}
        </p>
      )}
    </section>
  );
}
