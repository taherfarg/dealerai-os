"use client";

import Link from "next/link";
import { Auto, Ltr } from "@/components/Bidi";
import type { CustomerDetail } from "@/lib/api/hooks";
import { countryName, formatMoney, formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

/**
 * What a customer bought before (docs/lifecycle/README.md § L8). A buyer
 * writing again is a returning one, and the salesperson sees it before
 * replying — beside the thread and on Customer 360 alike. Nothing when they
 * have bought nothing.
 */
export function Purchases({
  purchases,
  tenant,
}: {
  purchases: CustomerDetail["purchases"];
  tenant: string;
}) {
  const t = useT();
  const locale = useLocale();
  if (purchases.length === 0) return null;
  return (
    <section>
      <h3 className="text-muted mb-1 text-xs font-semibold uppercase tracking-wide">
        {t("customer.purchases")}
      </h3>
      <ul className="space-y-1">
        {purchases.map((bought) => (
          <li key={bought.order_id} className="flex flex-wrap items-center gap-x-2 text-sm">
            <Link
              href={`/${tenant}/inventory/${bought.vehicle_id}`}
              className="min-w-0 font-medium underline-offset-2 hover:underline"
            >
              <Auto>{bought.car}</Auto>
            </Link>
            <span className="text-muted text-xs">
              {bought.purchase_type === "export" && bought.destination
                ? countryName(bought.destination, locale)
                : t("deal.type.local")}
              {" · "}
              {formatRelative(bought.completed_at, locale)}
            </span>
            {bought.price && <Ltr className="ms-auto text-xs">{formatMoney(bought.price)}</Ltr>}
          </li>
        ))}
      </ul>
    </section>
  );
}
