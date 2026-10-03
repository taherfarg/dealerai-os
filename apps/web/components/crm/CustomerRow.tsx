"use client";

import Link from "next/link";
import type { Customer } from "@/lib/api/hooks";
import { countryFlag, formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

const BAND_TONE: Record<string, string> = {
  hot: "bg-red-500/15 text-red-700 dark:text-red-300",
  warm: "bg-amber-500/15 text-amber-800 dark:text-amber-200",
  cold: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
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
        <label className="flex min-h-11 min-w-11 items-center justify-center border-b border-black/5 dark:border-white/10">
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
        className={`hover:bg-background grid gap-x-3 gap-y-1 border-b border-black/5 px-3 py-3 md:grid-cols-[1fr_10rem_8rem_6rem_6rem] md:items-center dark:border-white/10 ${
          onSelect ? "min-w-0 flex-1" : ""
        }`}
      >
        <span className="truncate text-sm font-medium">
          {countryFlag(customer.country)} {customer.name ?? t("inbox.unknownCustomer")}
          {customer.opted_out && (
            <span className="ms-2 rounded bg-red-500/15 px-1 text-[10px] uppercase text-red-700 dark:text-red-300">
              {t("customer.optedOut")}
            </span>
          )}
        </span>
        <span className="text-muted truncate text-xs">{customer.phone}</span>
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
