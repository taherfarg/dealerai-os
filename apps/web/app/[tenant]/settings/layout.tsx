"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { use, type ReactNode } from "react";
import { NavLinks } from "@/components/NavLinks";
import { SignOutButton } from "@/components/SignOutButton";
import { SECTIONS, firstSection, mayOpen } from "@/components/settings/sections";
import { useMe } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * The sections beside the section: a column from md up. Below it they wrap,
 * each on one line — as a scrolling row an owner's nine were three-line labels
 * with Sign out off the far end.
 */
export default function SettingsLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ tenant: string }>;
}) {
  const { tenant } = use(params);
  const t = useT();
  const permissions = useMe().data?.permissions;
  const allowed = mayOpen(usePathname(), permissions);
  const elsewhere = permissions && firstSection(permissions);
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 md:flex-row">
      <nav
        aria-label={t("nav.settings")}
        className="flex shrink-0 flex-wrap gap-1 *:whitespace-nowrap md:w-56 md:flex-col md:flex-nowrap md:*:whitespace-normal"
      >
        <NavLinks slug={tenant} items={SECTIONS} />
        <SignOutButton />
      </nav>
      <div className="min-w-0 flex-1 pb-24">
        {allowed
          ? children
          : elsewhere && (
              <>
                <h1 className="text-lg font-semibold">{t("nav.settings")}</h1>
                <p className="mt-2 text-sm">
                  {t("settings.notYours")}{" "}
                  <Link href={`/${tenant}${elsewhere.href}`} className="underline">
                    {t(elsewhere.key)}
                  </Link>
                </p>
              </>
            )}
      </div>
    </div>
  );
}
