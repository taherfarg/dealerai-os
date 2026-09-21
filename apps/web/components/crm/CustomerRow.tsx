"use client";

import Link from "next/link";
import type { Customer } from "@/lib/api/hooks";
import { countryFlag, formatRelative } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

const BAND_TONE: Record<string, string> = {
  hot: "bg-red-500/15 text-red-700 dark:text-red-300",
  warm: "bg-amber-500/15 text-amber-800 dark:text-amber-200",
  cold: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
};

/** One customer, as a table row on a desktop and a card on a phone. */
export function CustomerRow({ customer, href }: { customer: Customer; href: string }) {
  const t = useT();
  return (
    <li data-band={customer.band ?? "none"}>
      <Link
        href={href}
        className="hover:bg-background grid gap-x-3 gap-y-1 border-b border-black/5 px-3 py-3 md:grid-cols-[1fr_10rem_8rem_6rem_6rem] md:items-center dark:border-white/10"
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
          {formatRelative(customer.last_seen_at)}
        </time>
      </Link>
    </li>
  );
}
