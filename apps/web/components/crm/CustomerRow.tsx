"use client";

import Link from "next/link";
import type { Customer } from "@/lib/api/hooks";
import { CustomerName, Ltr } from "@/components/Bidi";
import { formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

const BAND_TONE: Record<string, string> = {
  hot: "bg-hot-soft text-hot",
  warm: "bg-warning-soft text-warning",
  cold: "bg-info-soft text-info",
};

/**
 * One customer, as a table row on a desktop and a card on a phone. With
 * `onSelect` it carries a checkbox, for handing many customers over at once.
 */
export function CustomerRow({
  customer,
  href,
  selected = false,
  onSelect,
}: {
  customer: Customer;
  href: string;
  selected?: boolean;
  onSelect?: (selected: boolean) => void;
}) {
  const t = useT();
  const locale = useLocale();
  return (
    <li data-band={customer.band ?? "none"} className={onSelect ? "flex items-stretch" : undefined}>
      {onSelect && (
        <label className="flex min-h-11 min-w-11 items-center justify-center border-b border-border">
          <input
            type="checkbox"
            checked={selected}
            onChange={(event) => onSelect(event.target.checked)}
            aria-label={`${t("bulk.select")} ${customer.name ?? ""}`.trim()}
          />
        </label>
      )}
      <Link
        href={href}
        className={`hover:bg-background grid gap-x-3 gap-y-1 border-b border-border px-3 py-3 md:grid-cols-[1fr_10rem_8rem_6rem_6rem] md:items-center ${
          onSelect ? "min-w-0 flex-1" : ""
        }`}
      >
        <span className="flex min-w-0 items-baseline gap-2 text-sm font-medium">
          <CustomerName country={customer.country} name={customer.name} />
          {customer.opted_out && (
            <span className="shrink-0 rounded bg-danger-soft px-1 text-[10px] uppercase text-danger">
              {t("customer.optedOut")}
            </span>
          )}
        </span>
        <span className="text-muted truncate text-xs">
          <Ltr>{customer.phone}</Ltr>
        </span>
        <span className="text-muted truncate text-xs">
          {customer.owner?.name ?? t("customers.nobody")}
        </span>
        <span>
          {customer.band && (
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${BAND_TONE[customer.band]}`}
            >
              {t(`band.${customer.band}`)}
            </span>
          )}
        </span>
        <time className="text-muted text-xs md:text-end" dateTime={customer.last_seen_at}>
          {formatRelative(customer.last_seen_at, locale)}
        </time>
      </Link>
    </li>
  );
}
