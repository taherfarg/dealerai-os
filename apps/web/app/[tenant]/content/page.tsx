"use client";

import { use, useState, type FormEvent } from "react";
import { ContentGrid, mayReview } from "@/components/content/ContentGrid";
import { RunStream } from "@/components/content/RunStream";
import { useContentList, useGenerateContent, useMe, useVehicles } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

const TABS: readonly [string, MessageKey][] = [
  ["pending_approval", "content.tab.toApprove"],
  ["approved", "content.tab.approved"],
  ["rejected", "content.tab.rejected"],
  ["all", "content.tab.all"],
];

/**
 * The content a run made, waiting for a person (T3.7): make some for chosen
 * cars and watch it happen, then open a piece to edit its words, approve it or
 * reject it with a reason.
 */
export default function ContentPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const [filters, setFilters] = useFilters({ status: "pending_approval" });
  const list = useContentList(filters.status === "all" ? null : filters.status);
  const canReview = mayReview(me.data?.role);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <h1 className="text-lg font-semibold">{t("nav.content")}</h1>
      {canReview && <Generate />}
      <nav className="flex flex-wrap gap-2" aria-label={t("content.tabs")}>
        {TABS.map(([status, label]) => (
          <button
            key={status}
            type="button"
            aria-pressed={filters.status === status}
            onClick={() => setFilters({ status })}
            className={`btn ${filters.status === status ? "btn-primary" : ""}`}
          >
            {t(label)}
          </button>
        ))}
      </nav>
      {list.isError ? (
        <p role="alert" className="text-danger text-sm">
          {list.error.message}
        </p>
      ) : list.data ? (
        <ContentGrid items={list.data} tenant={tenant} />
      ) : (
        <p className="text-muted text-sm">…</p>
      )}
    </div>
  );
}

function Generate() {
  const t = useT();
  const stock = useVehicles({ status: "available" });
  const generate = useGenerateContent();
  const [runId, setRunId] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const vehicle_ids = form.getAll("vehicle").map(String);
    if (vehicle_ids.length === 0) return;
    generate.mutate(
      { vehicle_ids, count: Number(form.get("count") || 8) },
      { onSuccess: (started) => setRunId(started.run_id) },
    );
  };

  return (
    <section className="space-y-3">
      <form onSubmit={submit} className="space-y-2">
        <h2 className="text-sm font-semibold">{t("content.make")}</h2>
        <p className="text-muted text-xs">{t("content.makeHint")}</p>
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <legend className="sr-only">{t("content.cars")}</legend>
          {(stock.data ?? []).map((car) => (
            <label key={car.id} className="flex items-center gap-1.5">
              <input type="checkbox" name="vehicle" value={car.id} />
              {[car.model_year, car.make, car.model].filter(Boolean).join(" ")}
            </label>
          ))}
        </fieldset>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted">{t("content.count")}</span>
            <input
              name="count"
              type="number"
              min={1}
              max={12}
              defaultValue={8}
              className="field w-24"
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={generate.isPending}>
            {t("content.start")}
          </button>
        </div>
        {generate.error && <p className="text-danger text-xs">{generate.error.message}</p>}
      </form>
      {runId && <RunStream key={runId} runId={runId} />}
    </section>
  );
}
