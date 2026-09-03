import Link from "next/link";
import { type Locale, t } from "@/lib/i18n";
import { LocaleToggle } from "./LocaleToggle";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type Tenant = { id: string; slug: string; name: string };

const NAV = [
  { href: "", key: "nav.command" },
  { href: "/inventory", key: "nav.inventory" },
  { href: "/content", key: "nav.content" },
  { href: "/inbox", key: "nav.inbox" },
  { href: "/leads", key: "nav.leads" },
  { href: "/approvals", key: "nav.approvals" },
  { href: "/analytics", key: "nav.analytics" },
  { href: "/settings", key: "nav.settings" },
] as const;

export function Shell({
  tenant,
  tenants,
  locale,
  pendingApprovals,
  children,
}: {
  tenant: Tenant;
  tenants: Tenant[];
  locale: Locale;
  pendingApprovals: number;
  children: React.ReactNode;
}) {
  return (
    // Grid columns, not float/absolute: the browser mirrors a grid under
    // dir="rtl" for free, so the sidebar moves to the right with no RTL CSS.
    <div className="grid min-h-screen grid-rows-[auto_1fr] md:grid-cols-[16rem_1fr] md:grid-rows-1">
      <aside className="border-border bg-surface flex flex-col gap-4 border-b p-4 md:border-b-0 md:border-e md:p-6">
        <div className="flex items-center justify-between gap-2">
          <span className="text-brand text-lg font-semibold tracking-tight">DealerAI</span>
          <LocaleToggle locale={locale} />
        </div>

        <WorkspaceSwitcher current={tenant} tenants={tenants} locale={locale} />

        <nav className="flex flex-row flex-wrap gap-1 md:flex-col">
          {NAV.map((item) => (
            <Link
              key={item.key}
              href={`/${tenant.slug}${item.href}`}
              // ps-3 / text-start are logical: they flip automatically in RTL.
              className="hover:bg-background flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-start transition-colors"
            >
              <span>{t(locale, item.key)}</span>
              {item.key === "nav.approvals" && pendingApprovals > 0 && (
                <span className="bg-accent min-w-5 rounded-full px-1.5 py-0.5 text-center text-xs font-medium text-black">
                  {pendingApprovals}
                </span>
              )}
            </Link>
          ))}
        </nav>
      </aside>

      <main className="min-w-0 p-4 md:p-8">{children}</main>
    </div>
  );
}
