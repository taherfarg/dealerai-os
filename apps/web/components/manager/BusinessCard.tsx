"use client";

import Link from "next/link";
import { Auto, Ltr } from "@/components/Bidi";
import type { ManagerDashboard } from "@/lib/api/hooks";
import { formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { StatTile } from "./StatTile";

type Business = NonNullable<ManagerDashboard["business"]>;

/**
 * What the month made and what the stock costs to keep
 * (docs/lifecycle/README.md § L8). Shown only to a reader cleared for the buy
 * side — the API sends nothing to anybody else. Every figure is the API's;
 * nothing here adds two numbers up.
 */
export function BusinessCard({ business, tenant }: { business: Business; tenant: string }) {
  const t = useT();
  const { month } = business;
  const partly = month.costed < month.sold;
  return (
    <section aria-labelledby="business-title">
      <h2 id="business-title" className="text-sm font-semibold">
        {t("business.title")}
      </h2>
      <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label={t("business.sold")} value={String(month.sold)} />
        <StatTile
          label={t("business.gross")}
          value={formatMoney(month.gross)}
          hint={partly ? `${t("business.costedOnly")} ${month.costed} / ${month.sold}` : undefined}
          tone={month.gross.amount_minor < 0 ? "bad" : null}
        />
        <StatTile
          label={t("business.perCar")}
          value={month.gross_per_car ? formatMoney(month.gross_per_car) : "—"}
        />
        <StatTile
          label={t("business.daysToSell")}
          value={month.avg_days_held == null ? "—" : String(month.avg_days_held)}
        />
        <StatTile
          label={t("business.inStock")}
          value={String(business.in_stock)}
          href={`/${tenant}/inventory`}
        />
        <StatTile label={t("business.tiedUp")} value={formatMoney(business.tied_up)} />
        <StatTile label={t("business.perDay")} value={formatMoney(business.holding_per_day)} />
      </div>

      <h3 className="mt-4 text-sm font-semibold">{t("business.costly")}</h3>
      <p className="text-muted text-xs">
        {t("business.heldOver")} <Ltr>{String(business.old_after_days)}</Ltr>{" "}
        {t("economics.days")}
      </p>
      {business.costly.length === 0 ? (
        <p className="text-muted mt-1 text-sm">{t("business.nothingCostly")}</p>
      ) : (
        <ul className="mt-1 divide-y divide-border">
          {business.costly.map((car) => (
            <li key={car.vehicle_id}>
              <Link
                href={`/${tenant}/inventory/${car.vehicle_id}`}
                className="hover:bg-surface flex min-h-11 flex-wrap items-center justify-between gap-x-3 text-sm"
              >
                <Auto className="min-w-0 truncate">{car.label}</Auto>
                <span className="text-muted flex flex-wrap gap-x-3 text-xs">
                  <span>
                    <Ltr>{String(car.days_held)}</Ltr> {t("economics.days")}
                  </span>
                  <span>
                    {t("economics.holding")} <Ltr>{formatMoney(car.holding)}</Ltr>
                  </span>
                  {car.margin_left && (
                    <span className={car.margin_left.amount_minor < 0 ? "text-danger" : ""}>
                      {t("business.marginLeft")} <Ltr>{formatMoney(car.margin_left)}</Ltr>
                    </span>
                  )}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
