"use client";

import { use, type ReactNode } from "react";
import { NavLinks } from "@/components/NavLinks";
import { SECTIONS } from "@/components/settings/sections";
import { useT } from "@/lib/i18n-client";

/** The sections beside the section: a column from md up, a scrolling row below it. */
export default function SettingsLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ tenant: string }>;
}) {
  const { tenant } = use(params);
  const t = useT();
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 md:flex-row">
      <nav
        aria-label={t("nav.settings")}
        className="flex shrink-0 gap-1 overflow-x-auto md:w-56 md:flex-col"
      >
        <NavLinks slug={tenant} items={SECTIONS} />
      </nav>
      <div className="min-w-0 flex-1 pb-24">{children}</div>
    </div>
  );
}
