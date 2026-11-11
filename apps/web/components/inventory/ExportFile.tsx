"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import {
  useCheckDraft,
  useDownloadStep,
  useExportFile,
  useMoveStep,
  useSetConsignee,
  useStartExport,
  useUploadStep,
  type Consignee,
  type DraftCheck,
  type ExportStep,
  type Order,
  type StepCode,
} from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

export type Action = "done" | "skip" | "undo" | "upload" | "download" | "invoice" | "check";

/**
 * What a person can do with a step. The invoice is done by signing it, on its
 * own page; the bill of lading draft is checked against the order before the
 * buyer is asked to confirm it. The API refuses the same moves.
 */
export function stepActions(step: ExportStep, canEdit: boolean): Action[] {
  const actions: Action[] = [];
  if (step.code === "commercial_invoice") return ["invoice"];
  if (canEdit) actions.push(...(step.status === "pending" ? (["done", "skip"] as const) : (["undo"] as const)));
  if (canEdit && step.code === "bl_draft_confirmed") actions.push("check");
  if (canEdit && step.takes_document) actions.push("upload");
  if (step.has_document) actions.push("download");
  return actions;
}

const today = () => new Date().toISOString().slice(0, 10);

const PILL: Record<string, string> = {
  done: "pill pill-accent",
  skipped: "pill text-muted",
  pending: "pill",
};

/**
 * The export file of a held order (docs/lifecycle/README.md § L7): the
 * destination's procedure as Pollux runs it, the paper each step produced, the
 * consignee, and the commercial invoice.
 */
export function ExportFile({ order, canEdit }: { order: Order; canEdit: boolean }) {
  const t = useT();
  const file = useExportFile(order.id, true);
  const start = useStartExport(order.id);
  if (!file.data) return null;
  const data = file.data;

  if (data.steps.length === 0) {
    return canEdit ? (
      <div className="mt-4">
        <button type="button" className="btn" disabled={start.isPending} onClick={() => start.mutate(undefined)}>
          {t("export.start")}
        </button>
      </div>
    ) : null;
  }

  return (
    <div className="border-border mt-4 border-t pt-3">
      <h3 className="text-xs font-semibold">
        {t(`procedure.${data.procedure as "DZ" | "TN" | "other" | "local"}`)}
      </h3>
      <p className="text-muted text-xs">
        {data.stage ? (
          <>
            {t("inbound.next")} <span className="font-medium">{t(`step.${data.stage as StepCode}`)}</span>
          </>
        ) : (
          t("export.complete")
        )}
      </p>

      {order.purchase_type === "export" && (
        <ConsigneeForm orderId={order.id} file={data} canEdit={canEdit} />
      )}

      <ol className="divide-border mt-2 divide-y text-sm">
        {data.steps.map((step) => (
          <StepRow key={step.code} orderId={order.id} step={step} canEdit={canEdit} />
        ))}
      </ol>
    </div>
  );
}

function ConsigneeForm({
  orderId,
  file,
  canEdit,
}: {
  orderId: string;
  file: NonNullable<ReturnType<typeof useExportFile>["data"]>;
  canEdit: boolean;
}) {
  const t = useT();
  const save = useSetConsignee(orderId);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim() || null;
    save.mutate({
      consignee_name: text("consignee_name"),
      consignee_address: text("consignee_address"),
      consignee_phone: text("consignee_phone"),
      port_of_discharge: text("port_of_discharge"),
      shipping_method: (text("shipping_method") as Consignee["shipping_method"]) ?? null,
    });
  };
  return (
    <form
      key={`${file.consignee_name}-${file.port_of_discharge}`}
      onSubmit={submit}
      className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2"
    >
      {(["consignee_name", "consignee_phone", "consignee_address", "port_of_discharge"] as const).map((name) => (
        <label key={name} className={`text-xs ${name === "consignee_address" ? "sm:col-span-2" : ""}`}>
          <span className="text-muted">{t(`export.${name}`)}</span>
          <input
            name={name}
            disabled={!canEdit}
            defaultValue={file[name] ?? ""}
            dir={name === "consignee_phone" ? "ltr" : undefined}
            className="field mt-1 w-full"
          />
        </label>
      ))}
      <label className="text-xs">
        <span className="text-muted">{t("export.shipping_method")}</span>
        <select
          name="shipping_method"
          disabled={!canEdit}
          defaultValue={file.shipping_method ?? ""}
          className="field mt-1 w-full px-3"
        >
          <option value="">—</option>
          {(["container", "shared_container", "roro", "air"] as const).map((method) => (
            <option key={method} value={method}>
              {t(`shippingMethod.${method}`)}
            </option>
          ))}
        </select>
      </label>
      {canEdit && (
        <div className="flex items-end gap-3">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {t("common.save")}
          </button>
          {save.isError && <span className="text-danger text-xs">{save.error.message}</span>}
        </div>
      )}
    </form>
  );
}

function StepRow({ orderId, step, canEdit }: { orderId: string; step: ExportStep; canEdit: boolean }) {
  const t = useT();
  const { tenant } = useParams<{ tenant: string }>();
  const move = useMoveStep(orderId);
  const upload = useUploadStep(orderId);
  const download = useDownloadStep(orderId);
  const check = useCheckDraft(orderId);
  const [when, setWhen] = useState(today());
  const [result, setResult] = useState<DraftCheck | null>(null);
  const code = step.code as StepCode;
  const actions = stepActions(step, canEdit);
  const failed = move.error ?? upload.error ?? download.error ?? check.error;

  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1">{t(`step.${code}`)}</span>
        {step.done_on && <Ltr className="text-muted text-xs">{step.done_on}</Ltr>}
        <span className={PILL[step.status]}>
          {t(`milestoneStatus.${step.status as "pending" | "done" | "skipped"}`)}
        </span>
        {actions.includes("done") && (
          <>
            <input
              type="date"
              value={when}
              aria-label={t("inbound.when")}
              onChange={(event) => setWhen(event.target.value)}
              className="field w-36"
            />
            <button
              type="button"
              className="btn btn-primary"
              disabled={move.isPending}
              onClick={() => move.mutate({ code, status: "done", done_on: when })}
            >
              {t("inbound.done")}
            </button>
          </>
        )}
        {actions.includes("skip") && (
          <button type="button" className="btn btn-quiet" onClick={() => move.mutate({ code, status: "skipped" })}>
            {t("inbound.skip")}
          </button>
        )}
        {actions.includes("undo") && (
          <button type="button" className="btn btn-quiet" onClick={() => move.mutate({ code, status: "pending" })}>
            {t("inbound.undo")}
          </button>
        )}
        {actions.includes("check") && (
          <label className="btn">
            {check.isPending ? t("invoice.reading") : t("export.checkDraft")}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              className="sr-only"
              onChange={(event) => {
                const picked = event.target.files?.[0];
                if (picked) check.mutate(picked, { onSuccess: setResult });
              }}
            />
          </label>
        )}
        {actions.includes("upload") && (
          <label className="btn">
            {t("inbound.upload")}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              className="sr-only"
              onChange={(event) => {
                const picked = event.target.files?.[0];
                if (picked) upload.mutate({ code, file: picked });
              }}
            />
          </label>
        )}
        {actions.includes("download") && (
          <button type="button" className="btn btn-quiet" onClick={() => download.mutate(code)}>
            {t("export.download")}
          </button>
        )}
        {actions.includes("invoice") && (
          <Link href={`/${tenant}/orders/${orderId}/invoice`} className="btn">
            {t("export.openInvoice")}
          </Link>
        )}
      </div>

      {result && (
        <div
          className={`mt-2 rounded-md p-2 text-xs ${result.clean ? "bg-surface" : "bg-danger-soft text-danger"}`}
          role="status"
        >
          <p className="font-medium">{result.clean ? t("export.draftClean") : t("export.draftDiffers")}</p>
          <ul className="mt-1 space-y-0.5">
            {result.checks.map((c) => (
              <li key={c.name}>
                {c.ok === true ? "✓" : c.ok === false ? "✗" : "–"} {t(`draftCheck.${c.name as "vin" | "consignee" | "port"}`)}
                {c.ok === false && (
                  <>
                    {": "}
                    {t("export.expected")} <Auto>{c.expected}</Auto> · {t("export.found")}{" "}
                    <Auto>{c.found ?? "—"}</Auto>
                  </>
                )}
                {c.ok === null && <span className="text-muted"> — {t("export.notCompared")}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {failed && <p className="text-danger mt-1 text-xs">{failed.message}</p>}
    </li>
  );
}
