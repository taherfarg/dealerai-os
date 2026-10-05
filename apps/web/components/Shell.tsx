import { type Locale, t } from "@/lib/i18n";
import { AccountMenu } from "./AccountMenu";
import { AvailabilitySwitch } from "./AvailabilitySwitch";
import { LocaleToggle } from "./LocaleToggle";
import { NavLinks, type NavItem } from "./NavLinks";
import { NotificationsBell } from "./NotificationsBell";
import { SignOutButton } from "./SignOutButton";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type Tenant = { id: string; slug: string; name: string };

const SETTINGS: NavItem = { href: "/settings", key: "nav.settings", icon: "settings" };

const SALES: readonly NavItem[] = [
  { href: "/inbox", key: "nav.inbox", icon: "inbox" },
  { href: "/today", key: "nav.today", icon: "today" },
  { href: "/customers", key: "nav.customers", icon: "customers" },
  { href: "/pipeline", key: "nav.pipeline", icon: "pipeline" },
  { href: "/tasks", key: "nav.tasks", icon: "tasks" },
  { href: "/dashboard", key: "nav.dashboard", permission: "dashboard.manager", icon: "dashboard" },
  { href: "/inventory", key: "nav.inventory", icon: "inventory" },
  { href: "/approvals", key: "nav.approvals", icon: "approvals" },
  SETTINGS,
];

const MARKETING: readonly NavItem[] = [
  { href: "/command", key: "nav.command", icon: "command" },
  { href: "/content", key: "nav.content", icon: "content" },
];

/** Five destinations fit a phone's bottom bar; everything else is one tap into Settings for now. */
const MOBILE: readonly NavItem[] = [...SALES.slice(0, 4), SETTINGS];

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
    // dir="rtl" for free, so the rail moves to the right with no RTL CSS.
    <div className="grid min-h-screen grid-rows-[auto_1fr] md:grid-cols-[5.5rem_1fr] md:grid-rows-1">
      {/* The first stop for a keyboard: on a desk the navigation is some
          fifteen Tabs long, and every page begins after it. Seen only while
          it has focus. */}
      <a
        href="#page"
        className="bg-surface border-border sr-only rounded-md border px-3 py-2 text-sm focus:not-sr-only focus:fixed focus:start-2 focus:top-2 focus:z-50"
      >
        {t(locale, "nav.skip")}
      </a>
      {/* One element, two shapes ([11] § 4): a row across the top of a phone, a
          rail down the side of a desk. So there is one bell and one account. */}
      <aside className="border-border bg-background flex items-center gap-2 border-b px-3 py-1 md:sticky md:top-0 md:h-dvh md:flex-col md:gap-3 md:overflow-y-auto md:border-b-0 md:border-e md:px-2 md:py-3">
        <span
          role="img"
          aria-label="DealerAI"
          className="bg-accent text-on-accent grid size-9 shrink-0 place-items-center rounded-xl text-base font-semibold md:size-11 md:text-lg"
        >
          D
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium md:hidden">{tenant.name}</span>

        {/* The same list as the bar under a phone's page; CSS shows one. */}
        <nav
          aria-label={t(locale, "nav.main")}
          className="hidden w-full flex-col items-center gap-0.5 md:flex"
        >
          <NavLinks
            slug={tenant.slug}
            items={SALES}
            badges={{ "nav.approvals": pendingApprovals }}
          />
          <hr aria-hidden="true" className="border-border my-1.5 w-10" />
          <p className="sr-only">{t(locale, "nav.marketing")}</p>
          <NavLinks slug={tenant.slug} items={MARKETING} />
        </nav>

        <div className="flex shrink-0 items-center gap-1 md:mt-auto md:w-full md:flex-col">
          <div className="hidden w-full md:block">
            <AvailabilitySwitch compact />
          </div>
          <NotificationsBell />
          <AccountMenu>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm">{t(locale, "account.language")}</span>
              <LocaleToggle locale={locale} />
            </div>
            <WorkspaceSwitcher current={tenant} tenants={tenants} locale={locale} />
            {/* On a desk it is in the rail, where it is one press away. */}
            <div className="md:hidden">
              <AvailabilitySwitch />
            </div>
            <SignOutButton />
          </AccountMenu>
        </div>
      </aside>

      <main id="page" className="min-w-0 p-4 pb-28 md:p-8">
        {children}
      </main>

      <nav
        aria-label={t(locale, "nav.main")}
        className="border-border bg-background fixed inset-x-3 bottom-3 z-10 grid grid-cols-5 gap-1 rounded-3xl border p-1.5 shadow-lg md:hidden"
      >
        <NavLinks slug={tenant.slug} items={MOBILE} />
      </nav>
    </div>
  );
}
