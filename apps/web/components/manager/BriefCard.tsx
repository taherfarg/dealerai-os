"use client";

import Link from "next/link";
import { Auto } from "@/components/Bidi";
import type { AttentionItem, ManagerDashboard } from "@/lib/api/hooks";
import { useLocale, useT } from "@/lib/i18n-client";

/** Every item links to what it is about. */
const HREF: Record<AttentionItem["kind"], (tenant: string, item: AttentionItem) => string> = {
  waiting: (tenant, item) => `/${tenant}/inbox/${item.id}`,
  hot_lead: (tenant, item) => `/${tenant}/pipeline?lead=${item.id}`,
  overdue_tasks: (tenant, item) => `/${tenant}/tasks?bucket=overdue&assignee=${item.id}`,
};

/**
 * The morning brief: one line a model wrote, in the reader's language, over
 * the rows that need somebody now (05-workflows § 13). The rows are rendered
 * here rather than written by the model, so they are in the reader's
 * language, they link to the right customer, and they are live — an item
 * somebody already handled is gone when the manager looks.
 */
export function BriefCard({
  brief,
  tenant,
}: {
  brief: ManagerDashboard["brief"];
  tenant: string;
}) {
  const t = useT();
  const locale = useLocale();
  const headline = brief.headline?.[locale];
  return (
    <section
      aria-label={t("brief.title")}
      className="bg-surface border-border rounded-lg border p-4"
    >
      {headline && (
        <p className="text-base font-medium" dir="auto">
          {headline}
        </p>
      )}
      <h2 className="text-muted mt-2 text-xs font-semibold">{t("brief.thisMorning")}</h2>
      {brief.items.length === 0 ? (
        <p className="text-muted mt-1 text-sm">{t("brief.nothing")}</p>
      ) : (
        <ul className="mt-1 divide-y divide-border">
          {brief.items.map((item) => (
            <li key={`${item.kind}:${item.id}`}>
              <Link
                href={HREF[item.kind](tenant, item)}
                className="hover:bg-surface flex min-h-11 items-center justify-between gap-2 text-sm"
              >
                {/* Who, then what is wrong, each its own: in one element the
                    name decided the direction, and an Arabic reader lost the
                    first word of the reason. */}
                <span className="flex min-w-0 items-baseline gap-2">
                  <Auto className="min-w-0 truncate">
                    {item.name ?? t("inbox.unknownCustomer")}
                  </Auto>
                  <span className="text-muted shrink-0 text-xs">
                    {t(`brief.${item.kind}`)}
                    {item.count ? ` · ${item.count}` : ""}
                  </span>
                </span>
                {item.owner && (
                  <span className="text-muted shrink-0 text-xs" dir="auto">
                    {item.owner.name}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
