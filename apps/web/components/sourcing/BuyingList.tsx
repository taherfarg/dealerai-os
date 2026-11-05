"use client";

import Link from "next/link";
import { Auto, Ltr } from "@/components/Bidi";
import type { BuyingList as List, Wanted } from "@/lib/api/hooks";
import { countryName, formatMoney, formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import { BidLines } from "./BidLines";

/** "2 sold in a year · median price AED 235,000 · 10 days to sell" — what history says. */
export function worthLine(car: Wanted, words: { sold: string; median: string; days: string }) {
  const { sold, price, days_to_sell: days } = car.worth;
  if (!sold) return null;
  return [
    `${words.sold}: ${sold}`,
    price && `${words.median} ${formatMoney(price)}`,
    days != null && `${days} ${words.days}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * What customers asked for that the dealer does not have
 * (docs/lifecycle/README.md § L5): each car, who asked and in what words, what
 * the dealer's own sales say it is worth, and the most to pay for one.
 */
export function BuyingList({ list, tenant }: { list: List; tenant: string }) {
  const t = useT();
  const locale = useLocale();
  const words = {
    sold: t("sourcing.sold"),
    median: t("sourcing.median"),
    days: t("sourcing.daysToSell"),
  };

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("sourcing.list")}</h2>
      <p className="text-muted mt-1 text-xs">{t("sourcing.listHint")}</p>
      {list.cars.length === 0 ? (
        <p className="text-muted mt-3 text-sm">{t("sourcing.empty")}</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {list.cars.map((car) => {
            const history = worthLine(car, words);
            return (
              <li key={`${car.make}/${car.model}`} className="bg-surface rounded-2xl p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="font-semibold">
                    <Ltr>
                      {car.make} {car.model}
                    </Ltr>
                  </h3>
                  <span className="text-muted text-sm">
                    {car.askers.length}{" "}
                    {car.askers.length === 1 ? t("sourcing.askedOne") : t("sourcing.asked")}
                  </span>
                </div>
                <ul className="mt-2 space-y-1">
                  {car.askers.map((asker) => (
                    <li
                      key={asker.contact_id}
                      className="flex flex-wrap items-baseline gap-x-2 text-sm"
                    >
                      <Link
                        href={`/${tenant}/customers/${asker.contact_id}`}
                        className="font-medium underline-offset-2 hover:underline"
                      >
                        <Auto>{asker.name ?? "—"}</Auto>
                      </Link>
                      <span className="text-muted min-w-0">
                        “<Auto>{asker.quoted}</Auto>”
                      </span>
                      <span className="text-muted text-xs">
                        {[
                          asker.model_year,
                          asker.budget && `${t("sourcing.budget")} ${formatMoney(asker.budget)}`,
                          asker.destination && countryName(asker.destination, locale),
                          formatRelative(asker.asked_at, locale),
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="mt-3 text-sm">
                  {history && <p className="text-muted text-xs">{history}</p>}
                  {car.bid ? (
                    <details className="mt-1">
                      <summary className="cursor-pointer">
                        {t("sourcing.maxBid")}:{" "}
                        <strong>
                          <Ltr>{formatMoney(car.bid.max_bid)}</Ltr>
                        </strong>
                        <span className="text-muted ms-2 text-xs">{t("sourcing.how")}</span>
                      </summary>
                      <div className="mt-2 max-w-sm">
                        <BidLines bid={car.bid} />
                      </div>
                    </details>
                  ) : (
                    <p className="text-muted text-xs">{t("sourcing.neverSold")}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
