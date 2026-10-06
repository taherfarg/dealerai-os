"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";
import { Icon, type IconName } from "./Icon";

export type NavItem = { href: string; key: MessageKey; permission?: string; icon?: IconName };

/** Links a role cannot use are hidden. Cosmetic only — the API refuses anyway. */
export function NavLinks({
  slug,
  items,
  badges = {},
}: {
  slug: string;
  items: readonly NavItem[];
  badges?: Partial<Record<MessageKey, number>>;
}) {
  const t = useT();
  const pathname = usePathname();
  const me = useMe();
  const allowed = items.filter(
    (item) => !item.permission || me.data?.permissions.includes(item.permission),
  );
  return (
    <>
      {allowed.map((item) => {
        const href = `/${slug}${item.href}`;
        const active = pathname === href || pathname.startsWith(`${href}/`);
        const badge = badges[item.key] ?? 0;
        return item.icon ? (
          // In the shell: the drawing over its word ([11] § 4).
          <Link
            key={item.key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 w-full flex-col items-center justify-center gap-0.5 rounded-2xl px-1 py-1.5 text-center text-[11px] leading-4 transition-colors rtl:text-xs ${
              active
                ? "bg-accent-soft text-accent-ink font-semibold"
                : "text-muted hover:bg-surface hover:text-foreground"
            }`}
          >
            <span className="relative">
              <Icon name={item.icon} size={22} />
              {badge > 0 && <span className="badge absolute -end-2.5 -top-1.5">{badge}</span>}
            </span>
            <span>{t(item.key)}</span>
          </Link>
        ) : (
          // Anywhere else — the sections of Settings — a row.
          <Link
            key={item.key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center justify-between gap-2 rounded-md px-3 py-2 text-start text-sm transition-colors ${
              active ? "bg-surface font-medium" : "hover:bg-surface"
            }`}
          >
            <span>{t(item.key)}</span>
            {badge > 0 && <span className="badge">{badge}</span>}
          </Link>
        );
      })}
    </>
  );
}
