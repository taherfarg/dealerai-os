"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

export type NavItem = { href: string; key: MessageKey; permission?: string };

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
        return (
          <Link
            key={item.key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center justify-between gap-2 rounded-md px-3 py-2 text-start text-sm transition-colors ${
              active ? "bg-background font-medium" : "hover:bg-background"
            }`}
          >
            <span>{t(item.key)}</span>
            {badge > 0 && (
              <span className="bg-accent min-w-5 rounded-full px-1.5 py-0.5 text-center text-xs font-medium text-black">
                {badge}
              </span>
            )}
          </Link>
        );
      })}
    </>
  );
}
