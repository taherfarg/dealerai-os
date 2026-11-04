"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import {
  useConfirmShipping,
  useInbound,
  useMoveMilestone,
  useReadShipping,
  useSaveJourney,
  useSetPaper,
  useUploadPaper,
  type CostIn,
  type Inbound as Journey,
  type ShippingConfirmation,
  type ShippingReading,
} from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

type Milestone = Journey["milestones"][number];
type MilestoneCode = NonNullable<ShippingConfirmation["milestone"]>["code"];
type PaperCode = NonNullable<ShippingConfirmation["paper"]>["code"];

const DETAILS = [
  "carrier",
  "reference",
  "vessel",
  "container",
  "port_of_loading",
  "port_of_discharge",
] as const;

/**
 * What a person confirms from a reading: the details it found, the step it
 * proves and the paper it is. Nothing the paper did not say is sent, so a
 * reading never blanks a field somebody typed.
 */
export function confirmationFrom(reading: ShippingReading): ShippingConfirmation {
  const journey: ShippingConfirmation["journey"] = {};
  for (const name of DETAILS) {
    if (reading[name]) journey[name] = reading[name];
  }
  if (reading.eta) journey.eta = reading.eta;
  return {
    journey,
    milestone: reading.milestone
      ? { code: reading.milestone as MilestoneCode, done_on: reading.departed_on ?? null }
      : null,
    paper:
      reading.paper && reading.document_path
        ? { code: reading.paper as PaperCode, document_path: reading.document_path }
        : null,
  };
}

const today = () => new Date().toISOString().slice(0, 10);

const PILL: Record<string, string> = {
  done: "pill pill-accent",
  skipped: "pill text-muted",
  pending: "pill",
  received: "pill pill-accent",
  not_needed: "pill text-muted",
  missing: "pill pill-warning",
};

/**
 * Where a bought car is, the papers it still needs and what its landed cost is
 * missing (docs/lifecycle/README.md § L4). Everybody sees the journey; the
 * papers and the fees come back only for someone cleared for the buy side.
 */
export function Inbound({ vehicleId, canEdit }: { vehicleId: string; canEdit: boolean }) {
  const t = useT();
  const inbound = useInbound(vehicleId);
  const journey = inbound.data;
  if (!journey) return <p className="text-muted text-sm">…</p>;
  if (!journey.started) return <Start vehicleId={vehicleId} canEdit={canEdit} />;

  return (
    <div className="space-y-6">
      <section className="bg-surface rounded-2xl p-4">
        <p className="text-sm">
          {journey.stage ? (
            <>
              <span className="text-muted">{t("inbound.next")}</span>{" "}
              <span className="font-semibold">{t(`milestone.${journey.stage as MilestoneCode}`)}</span>
            </>
          ) : (
            <span className="font-semibold">{t("inbound.onTheLot")}</span>
          )}
        </p>
        <p className="text-muted mt-1 text-xs">
          {t(`route.${journey.route as "import" | "local"}`)}
          {journey.eta && (
            <>
              {" · "}
              {t("inbound.eta")} <Ltr>{journey.eta}</Ltr>
            </>
          )}
          {journey.arrived_at && (
            <>
              {" · "}
              {t("inbound.arrived")} <Ltr>{journey.arrived_at.slice(0, 10)}</Ltr>
            </>
          )}
          {journey.late && <span className="pill pill-danger ms-2">{t("inbound.late")}</span>}
        </p>
      </section>

      <Details vehicleId={vehicleId} journey={journey} canEdit={canEdit} />
      <Milestones vehicleId={vehicleId} milestones={journey.milestones} canEdit={canEdit} />
      {journey.documents && (
        <Papers vehicleId={vehicleId} papers={journey.documents} canEdit={canEdit} />
      )}
      {journey.missing && <LandedCost missing={journey.missing} />}
      {canEdit && <ReadShipping vehicleId={vehicleId} />}
    </div>
  );
}

function Start({ vehicleId, canEdit }: { vehicleId: string; canEdit: boolean }) {
  const t = useT();
  const save = useSaveJourney(vehicleId);
  if (!canEdit) return <p className="text-muted text-sm">{t("inbound.none")}</p>;
  return (
    <section>
      <h2 className="text-sm font-semibold">{t("inbound.start")}</h2>
      <p className="text-muted mt-1 text-xs">{t("inbound.startHint")}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {(["import", "local"] as const).map((route) => (
          <button
            key={route}
            type="button"
            className="btn btn-primary"
            disabled={save.isPending}
            onClick={() => save.mutate({ route })}
          >
            {t(`route.${route}`)}
          </button>
        ))}
      </div>
      {save.isError && <p className="text-danger mt-1 text-xs">{save.error.message}</p>}
    </section>
  );
}

function Details({
  vehicleId,
  journey,
  canEdit,
}: {
  vehicleId: string;
  journey: Journey;
  canEdit: boolean;
}) {
  const t = useT();
  const save = useSaveJourney(vehicleId);

  if (!canEdit) {
    const known = DETAILS.filter((name) => journey[name]);
    if (known.length === 0) return null;
    return (
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {known.map((name) => (
          <div key={name} className="border-border flex justify-between gap-3 border-b py-1">
            <dt className="text-muted">{t(`inbound.${name}`)}</dt>
            <dd>
              <Auto>{journey[name]}</Auto>
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim() || null;
    save.mutate({
      route: form.get("route") as "import" | "local",
      carrier: text("carrier"),
      reference: text("reference"),
      vessel: text("vessel"),
      container: text("container"),
      port_of_loading: text("port_of_loading"),
      port_of_discharge: text("port_of_discharge"),
      eta: text("eta"),
    });
  };

  return (
    <section>
      <form
        key={`${journey.route}-${journey.eta}-${journey.reference}-${journey.carrier}`}
        onSubmit={submit}
        className="grid grid-cols-1 gap-2 sm:grid-cols-2"
      >
        <label className="text-xs">
          <span className="text-muted">{t("inbound.route")}</span>
          <select name="route" defaultValue={journey.route ?? "import"} className="field mt-1 w-full px-3">
            {(["import", "local"] as const).map((route) => (
              <option key={route} value={route}>
                {t(`route.${route}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("inbound.eta")}</span>
          <input type="date" name="eta" defaultValue={journey.eta ?? ""} className="field mt-1 w-full" />
        </label>
        {DETAILS.map((name) => (
          <label key={name} className="text-xs">
            <span className="text-muted">{t(`inbound.${name}`)}</span>
            <input
              name={name}
              maxLength={name === "container" ? 40 : 120}
              dir={name === "reference" || name === "container" ? "ltr" : undefined}
              defaultValue={journey[name] ?? ""}
              className="field mt-1 w-full"
            />
          </label>
        ))}
        <div className="flex items-center gap-3 sm:col-span-2">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {t("common.save")}
          </button>
          {save.isError && <span className="text-danger text-xs">{save.error.message}</span>}
        </div>
      </form>
    </section>
  );
}

function Milestones({
  vehicleId,
  milestones,
  canEdit,
}: {
  vehicleId: string;
  milestones: Milestone[];
  canEdit: boolean;
}) {
  const t = useT();
  const move = useMoveMilestone(vehicleId);
  const [dates, setDates] = useState<Record<string, string>>({});

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("inbound.journey")}</h2>
      <ol className="divide-border mt-2 divide-y text-sm">
        {milestones.map((step) => {
          const code = step.code as MilestoneCode;
          return (
            <li key={code} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <span className="min-w-0 flex-1">{t(`milestone.${code}`)}</span>
              {step.done_on && <Ltr className="text-muted text-xs">{step.done_on}</Ltr>}
              <span className={PILL[step.status]}>{t(`milestoneStatus.${step.status as "pending" | "done" | "skipped"}`)}</span>
              {canEdit && step.status === "pending" && (
                <>
                  <input
                    type="date"
                    aria-label={t("inbound.when")}
                    value={dates[code] ?? today()}
                    onChange={(event) => setDates({ ...dates, [code]: event.target.value })}
                    className="field w-36"
                  />
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={move.isPending}
                    onClick={() => move.mutate({ code, status: "done", done_on: dates[code] ?? today() })}
                  >
                    {t("inbound.done")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-quiet"
                    disabled={move.isPending}
                    onClick={() => move.mutate({ code, status: "skipped" })}
                  >
                    {t("inbound.skip")}
                  </button>
                </>
              )}
              {canEdit && step.status !== "pending" && (
                <button
                  type="button"
                  className="btn btn-quiet"
                  disabled={move.isPending}
                  onClick={() => move.mutate({ code, status: "pending" })}
                >
                  {t("inbound.undo")}
                </button>
              )}
            </li>
          );
        })}
      </ol>
      {move.isError && <p className="text-danger mt-1 text-xs">{move.error.message}</p>}
    </section>
  );
}

function Papers({
  vehicleId,
  papers,
  canEdit,
}: {
  vehicleId: string;
  papers: NonNullable<Journey["documents"]>;
  canEdit: boolean;
}) {
  const t = useT();
  const set = useSetPaper(vehicleId);
  const upload = useUploadPaper(vehicleId);
  const failed = set.error ?? upload.error;

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("inbound.papers")}</h2>
      <ul className="divide-border mt-2 divide-y text-sm">
        {papers.map((paper) => {
          const code = paper.code as PaperCode;
          return (
            <li key={code} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <span className="min-w-0 flex-1">{t(`paper.${code}`)}</span>
              <span className={PILL[paper.status]}>
                {t(`paperStatus.${paper.status as "missing" | "received" | "not_needed"}`)}
              </span>
              {canEdit && paper.status === "missing" && (
                <>
                  <label className="btn">
                    {t("inbound.upload")}
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp,application/pdf"
                      className="sr-only"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) upload.mutate({ code, file });
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn btn-quiet"
                    onClick={() => set.mutate({ code, status: "received" })}
                  >
                    {t("inbound.onPaper")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-quiet"
                    onClick={() => set.mutate({ code, status: "not_needed" })}
                  >
                    {t("inbound.notNeeded")}
                  </button>
                </>
              )}
              {canEdit && paper.status !== "missing" && (
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => set.mutate({ code, status: "missing" })}
                >
                  {t("inbound.undo")}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {failed && <p className="text-danger mt-1 text-xs">{failed.message}</p>}
    </section>
  );
}

function LandedCost({ missing }: { missing: NonNullable<Journey["missing"]> }) {
  const t = useT();
  const { tenant, vehicleId } = useParams<{ tenant: string; vehicleId: string }>();
  const name = (category: string) => t(`category.${category as CostIn["category"]}`);
  return (
    <section className="bg-surface rounded-2xl p-4">
      <h2 className="text-sm font-semibold">{t("inbound.landedCost")}</h2>
      {missing.costs.length === 0 && missing.estimated.length === 0 ? (
        <p className="text-success mt-1 text-sm">{t("inbound.costComplete")}</p>
      ) : (
        <ul className="mt-1 space-y-1 text-sm">
          {missing.costs.length > 0 && (
            <li>
              <span className="text-danger">{t("inbound.costMissing")}</span>{" "}
              {missing.costs.map(name).join(" · ")}
            </li>
          )}
          {missing.estimated.length > 0 && (
            <li>
              <span className="text-warning">{t("inbound.costEstimated")}</span>{" "}
              {missing.estimated.map(name).join(" · ")}
            </li>
          )}
        </ul>
      )}
      <Link href={`/${tenant}/inventory/${vehicleId}?tab=costs`} className="mt-2 inline-block text-xs underline">
        {t("inbound.openCosts")}
      </Link>
    </section>
  );
}

function ReadShipping({ vehicleId }: { vehicleId: string }) {
  const t = useT();
  const read = useReadShipping(vehicleId);
  const confirm = useConfirmShipping(vehicleId);
  const [reading, setReading] = useState<ShippingReading | null>(null);

  if (!reading) {
    return (
      <section>
        <h2 className="text-sm font-semibold">{t("shipping.title")}</h2>
        <p className="text-muted mt-1 text-xs">{t("shipping.hint")}</p>
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const file = new FormData(event.currentTarget).get("file");
            if (file instanceof File && file.size > 0) read.mutate(file, { onSuccess: setReading });
          }}
        >
          <input
            type="file"
            name="file"
            required
            accept="image/jpeg,image/png,image/webp,application/pdf"
            aria-label={t("shipping.title")}
            className="field flex-1"
          />
          <button type="submit" className="btn btn-primary" disabled={read.isPending}>
            {read.isPending ? t("invoice.reading") : t("shipping.read")}
          </button>
        </form>
        {read.isError && <p className="text-danger mt-1 text-xs">{read.error.message}</p>}
      </section>
    );
  }

  const found: [string, string | null | undefined][] = [
    [t("shipping.kind"), t(`shippingKind.${reading.kind as "bill_of_lading"}`)],
    ...DETAILS.map((name) => [t(`inbound.${name}`), reading[name]] as [string, string | null]),
    [t("shipping.departed"), reading.departed_on],
    [t("inbound.eta"), reading.eta],
  ];

  return (
    <section className="bg-surface rounded-2xl p-4">
      <h2 className="text-sm font-semibold">{t("shipping.proposal")}</h2>
      <p className={`mt-1 text-sm ${reading.matches ? "text-success" : "text-danger"}`} role="status">
        {reading.matches ? t("shipping.matches") : t("shipping.notThisCar")}
      </p>
      {reading.warnings.length > 0 && (
        <ul className="bg-danger-soft text-danger mt-2 list-disc rounded-md p-2 ps-6 text-xs" role="alert">
          {reading.warnings.map((warning) => (
            <li key={warning} dir="auto">
              {warning}
            </li>
          ))}
        </ul>
      )}
      <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {found
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label} className="border-border flex justify-between gap-3 border-b py-1">
              <dt className="text-muted">{label}</dt>
              <dd>
                <Auto>{value}</Auto>
              </dd>
            </div>
          ))}
      </dl>
      {reading.milestone && (
        <p className="text-muted mt-2 text-xs">
          {t("shipping.proves")} {t(`milestone.${reading.milestone as MilestoneCode}`)}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {confirm.isError && <span className="text-danger text-xs">{confirm.error.message}</span>}
        <button type="button" className="btn" onClick={() => setReading(null)}>
          {t("invoice.discard")}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!reading.matches || confirm.isPending}
          onClick={() =>
            confirm.mutate(confirmationFrom(reading), { onSuccess: () => setReading(null) })
          }
        >
          {t("shipping.confirm")}
        </button>
      </div>
    </section>
  );
}
