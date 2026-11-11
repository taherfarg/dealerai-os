"use client";

import { useRouter } from "next/navigation";
import { type Locale, t } from "@/lib/i18n";

type Tenant = { id: string; slug: string; name: string };

export function WorkspaceSwitcher({
  current,
  tenants,
  locale,
}: {
  current: Tenant;
  tenants: Tenant[];
  locale: Locale;
}) {
  const router = useRouter();

  if (tenants.length <= 1) {
    return (
      <div className="text-muted text-xs">
        <div className="uppercase tracking-wide">{t(locale, "workspace.switch")}</div>
        <div className="text-foreground mt-0.5 text-sm font-medium">{current.name}</div>
      </div>
    );
  }

  return (
    <label className="text-muted flex flex-col gap-1 text-xs">
      <span className="uppercase tracking-wide">{t(locale, "workspace.switch")}</span>
      <select
        value={current.slug}
        // Navigating rather than setting state: the tenant is in the URL, so
        // switching workspace has to change the address, not hidden state.
        onChange={(e) => router.push(`/${e.target.value}`)}
        className="field px-3"
      >
        {tenants.map((tn) => (
          <option key={tn.id} value={tn.slug}>
            {tn.name}
          </option>
        ))}
      </select>
    </label>
  );
}
