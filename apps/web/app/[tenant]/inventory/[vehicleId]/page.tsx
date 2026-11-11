"use client";

import Link from "next/link";
import { use } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import { BuySide } from "@/components/inventory/BuySide";
import { ApiError } from "@/lib/api/client";
import { useMe, useVehicle } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/i18n-client";

export default function VehiclePage({
  params,
}: {
  params: Promise<{ tenant: string; vehicleId: string }>;
}) {
  const { tenant, vehicleId } = use(params);
  const t = useT();
  const locale = useLocale();
  const me = useMe();
  const vehicle = useVehicle(vehicleId);
  const [tab, setTab] = useFilters({ tab: "overview" });
  const seesCost = (me.data?.permissions ?? []).includes("costs.view");
  const tabs = seesCost ? (["overview", "costs"] as const) : (["overview"] as const);

  if (vehicle.isError) {
    const problem = vehicle.error instanceof ApiError ? vehicle.error.problem : null;
    return (
      <div className="p-6 text-sm">
        <h1 className="text-danger font-normal">
          {!problem || problem.status === 404 ? t("vehicle.gone") : problem.detail}
        </h1>
        <Link href={`/${tenant}/inventory`} className="mt-2 inline-block underline">
          {t("vehicle.back")}
        </Link>
      </div>
    );
  }
  if (!vehicle.data) return <p className="text-muted p-6 text-sm">…</p>;
  const car = vehicle.data;

  const specs: [MessageKey, string | number | null | undefined][] = [
    ["vehicle.stock", car.stock_number],
    ["vehicle.vin", car.vin],
    ["vehicle.year", car.model_year],
    ["vehicle.mileage", car.mileage_km ? `${car.mileage_km.toLocaleString("en-US")} km` : null],
    ["vehicle.engine", car.engine],
    ["vehicle.transmission", car.transmission],
    ["vehicle.fuel", car.fuel],
    ["vehicle.colour", car.exterior_color],
    ["vehicle.seats", car.seats],
    ["vehicle.location", car.location],
    [
      "vehicle.listed",
      formatDateTime(car.listed_at, me.data?.tenant.timezone ?? "Asia/Dubai", locale),
    ],
  ];

  return (
    <div className="mx-auto max-w-4xl">
      <Link href={`/${tenant}/inventory`} className="text-muted text-xs underline">
        {t("vehicle.back")}
      </Link>
      <header className="mt-1 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold">
          <Auto>
            {[car.model_year, car.make, car.model, car.trim].filter(Boolean).join(" ")}
          </Auto>
        </h1>
        <p className="flex items-baseline gap-3">
          <span className="pill">{t(`vehicleStatus.${car.status}`)}</span>
          {car.price && <Ltr className="text-lg font-semibold">{formatMoney(car.price)}</Ltr>}
        </p>
      </header>

      {tabs.length > 1 && (
        <div role="tablist" className="border-border mt-4 flex gap-1 overflow-x-auto border-b">
          {tabs.map((name) => (
            <button
              key={name}
              role="tab"
              type="button"
              aria-selected={tab.tab === name}
              onClick={() => setTab({ tab: name })}
              className={`min-h-11 shrink-0 px-3 text-sm ${
                tab.tab === name ? "border-accent border-b-2 font-medium" : "text-muted"
              }`}
            >
              {t(`vehicle.tabs.${name}`)}
            </button>
          ))}
        </div>
      )}

      <div className="mt-4">
        {tab.tab === "costs" && seesCost ? (
          <BuySide
            vehicleId={vehicleId}
            canEdit={(me.data?.permissions ?? []).includes("costs.edit")}
          />
        ) : (
          <>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              {specs
                .filter(([, value]) => value !== null && value !== undefined && value !== "")
                .map(([key, value]) => (
                  <div key={key} className="border-border flex justify-between gap-3 border-b py-1">
                    <dt className="text-muted">{t(key)}</dt>
                    <dd>
                      <Auto>{String(value)}</Auto>
                    </dd>
                  </div>
                ))}
            </dl>
            {car.features.length > 0 && (
              <section className="mt-4">
                <h2 className="text-muted text-xs">{t("vehicle.features")}</h2>
                <ul className="mt-1 flex flex-wrap gap-1">
                  {car.features.map((feature) => (
                    <li key={feature} className="pill">
                      <Auto>{feature}</Auto>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
