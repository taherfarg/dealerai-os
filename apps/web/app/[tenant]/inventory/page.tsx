"use client";

import Link from "next/link";
import { use } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import {
  useEconomicsList,
  useMe,
  useVehicles,
  type Economics,
  type VehicleStatus,
} from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

const STATUSES: readonly VehicleStatus[] = ["available", "reserved", "sold", "draft", "archived"];
const DEFAULTS = { q: "", status: "available" };

const DAY = 86_400_000;

/** A car's age in whole days, from when it was listed. */
const daysSince = (iso: string) => Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / DAY));

export default function InventoryPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const [filters, setFilters] = useFilters(DEFAULTS);
  // Cost and margin are the buy side: asked for only by someone who may see it.
  const seesCost = (me.data?.permissions ?? []).includes("costs.view");

  const vehicles = useVehicles({
    q: filters.q || undefined,
    status: (filters.status || undefined) as VehicleStatus | undefined,
  });
  const economics = useEconomicsList(seesCost);
  const byId = new Map<string, Economics>(
    (economics.data ?? []).map((row) => [row.vehicle_id, row]),
  );
  const rows = vehicles.data ?? [];

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-lg font-semibold">{t("inventory.title")}</h1>

      <div className="mt-3 flex flex-wrap gap-2">
        <input
          type="search"
          defaultValue={filters.q}
          placeholder={t("inventory.search")}
          aria-label={t("inventory.search")}
          onChange={(event) => setFilters({ q: event.target.value })}
          className="field field-soft flex-1"
        />
        <select
          value={filters.status}
          aria-label={t("inventory.status")}
          onChange={(event) => setFilters({ status: event.target.value })}
          className="field px-3"
        >
          <option value="">{t("inventory.anyStatus")}</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {t(`vehicleStatus.${status}`)}
            </option>
          ))}
        </select>
      </div>

      {vehicles.isSuccess && rows.length === 0 && (
        <p className="text-muted mt-6 text-sm">{t("inventory.empty")}</p>
      )}

      <ul className="divide-border mt-3 divide-y">
        {rows.map((vehicle) => {
          const money = byId.get(vehicle.id);
          const margin = money?.margin_at_price;
          return (
            <li key={vehicle.id}>
              <Link
                href={`/${tenant}/inventory/${vehicle.id}`}
                className="hover:bg-surface flex min-h-14 flex-wrap items-center gap-x-4 gap-y-1 rounded-md px-2 py-2 text-sm"
              >
                <span className="min-w-0 flex-1">
                  <Auto className="block truncate font-medium">
                    {[vehicle.model_year, vehicle.make, vehicle.model, vehicle.trim]
                      .filter(Boolean)
                      .join(" ")}
                  </Auto>
                  <span className="text-muted text-xs">
                    {vehicle.stock_number && <Ltr>{vehicle.stock_number}</Ltr>}
                    <span className="ms-2">{t(`vehicleStatus.${vehicle.status}`)}</span>
                  </span>
                </span>

                <span
                  className="text-muted w-20 text-xs whitespace-nowrap"
                  title={t("inventory.days")}
                >
                  <Ltr>{daysSince(vehicle.listed_at)}</Ltr> {t("inventory.daysUnit")}
                </span>

                <span className="w-32 text-end">
                  {vehicle.price ? (
                    <Ltr>{formatMoney(vehicle.price)}</Ltr>
                  ) : (
                    <span className="text-muted text-xs">{t("inventory.noPrice")}</span>
                  )}
                </span>

                {seesCost && (
                  <span className="w-40 text-end text-xs">
                    {money && money.cost_lines > 0 ? (
                      <>
                        <span className="text-muted block">
                          {t("inventory.landed")} <Ltr>{formatMoney(money.landed_cost)}</Ltr>
                        </span>
                        {margin && (
                          <span
                            className={`block font-medium ${
                              margin.amount_minor < 0 ? "text-danger" : "text-success"
                            }`}
                          >
                            {t("inventory.margin")} <Ltr>{formatMoney(margin)}</Ltr>
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-muted">{t("inventory.noCost")}</span>
                    )}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
