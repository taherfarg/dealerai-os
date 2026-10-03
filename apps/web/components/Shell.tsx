import { type Locale, t } from "@/lib/i18n";
import { AvailabilitySwitch } from "./AvailabilitySwitch";
import { LocaleToggle } from "./LocaleToggle";
import { NavLinks, type NavItem } from "./NavLinks";
import { NotificationsBell } from "./NotificationsBell";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type Tenant = { id: string; slug: string; name: string };

const SALES: readonly NavItem[] = [
  { href: "/inbox", key: "nav.inbox" },
  { href: "/today", key: "nav.today" },
  { href: "/customers", key: "nav.customers" },
  { href: "/pipeline", key: "nav.pipeline" },
  { href: "/tasks", key: "nav.tasks" },
  { href: "/dashboard", key: "nav.dashboard", permission: "dashboard.manager" },
  { href: "/inventory", key: "nav.inventory" },
  { href: "/approvals", key: "nav.approvals" },
  { href: "/settings", key: "nav.settings" },
];

const MARKETING: readonly NavItem[] = [
  { href: "/command", key: "nav.command" },
  { href: "/content", key: "nav.content" },
];

/** Five destinations fit a phone's bottom bar; everything else is one tap into Settings for now. */
const MOBILE: readonly NavItem[] = [...SALES.slice(0, 4), { href: "/settings", key: "nav.settings" }];

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
          <div className="flex items-center gap-1">
            <NotificationsBell />
            <LocaleToggle locale={locale} />
          </div>
        </div>

        <WorkspaceSwitcher current={tenant} tenants={tenants} locale={locale} />

        {/* The same list as the bar under a phone's page; CSS shows one. */}
        <nav aria-label={t(locale, "nav.main")} className="hidden flex-col gap-1 md:flex">
          <NavLinks
            slug={tenant.slug}
            items={SALES}
            badges={{ "nav.approvals": pendingApprovals }}
          />
          <p className="text-muted mt-4 px-3 text-xs uppercase tracking-wide">
            {t(locale, "nav.marketing")}
          </p>
          <NavLinks slug={tenant.slug} items={MARKETING} />
        </nav>

        <div className="mt-auto hidden md:block">
          <AvailabilitySwitch />
        </div>
      </aside>

      <main className="min-w-0 p-4 pb-24 md:p-8">{children}</main>

      <nav
        aria-label={t(locale, "nav.main")}
        className="border-border bg-surface fixed inset-x-0 bottom-0 flex justify-around border-t p-1 md:hidden"
      >
        <NavLinks slug={tenant.slug} items={MOBILE} />
      </nav>
    </div>
  );
}
