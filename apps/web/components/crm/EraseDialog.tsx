"use client";

import { useState } from "react";
import { Auto } from "@/components/Bidi";
import { Modal } from "@/components/Modal";
import { ApiError } from "@/lib/api/client";
import { useEraseCustomer, useExportCustomer, type CustomerDetail } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * Erasing a customer — the one thing in this product that cannot be undone.
 *
 * It says what goes and what stays before it does anything, offers the copy
 * first (05-workflows § 14: "export offered first"), and only lets the button
 * work once the customer's name has been typed, so it is never a misclick.
 */
export function EraseDialog({
  customer,
  onClose,
  onErased,
}: {
  customer: CustomerDetail;
  onClose: () => void;
  onErased: () => void;
}) {
  const t = useT();
  const erase = useEraseCustomer(customer.id);
  const exporting = useExportCustomer(customer.id);
  const [typed, setTyped] = useState("");
  const expected = (customer.name ?? "").trim() || "delete";
  const confirmed = typed.trim().toLowerCase() === expected.toLowerCase();

  return (
    <Modal title={t("erase.title")} onClose={onClose}>
      <p className="text-muted mt-1 text-xs">
        <Auto>{customer.name}</Auto>
      </p>

      <section className="mt-3 text-xs">
        <h3 className="font-semibold">{t("erase.goes")}</h3>
        <ul className="text-muted mt-1 list-inside list-disc">
          <li>{t("erase.goes.conversations")}</li>
          <li>{t("erase.goes.files")}</li>
          <li>{t("erase.goes.leads")}</li>
          <li>{t("erase.goes.drafts")}</li>
        </ul>
        <p className="text-muted mt-2">{t("erase.stays")}</p>
      </section>

      <button
        type="button"
        onClick={() => exporting.mutate()}
        disabled={exporting.isPending}
        className="mt-3 min-h-11 text-sm underline"
      >
        {t("erase.exportFirst")}
      </button>

      <label className="mt-3 flex flex-col gap-1 text-xs">
        <span>
          {t("erase.type")}{" "}
          <span className="font-semibold" dir="auto">
            {expected}
          </span>
        </span>
        <input
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          className="field px-3"
          dir="auto"
        />
      </label>

      {erase.isError && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {erase.error instanceof ApiError
            ? (erase.error.problem.detail ?? erase.error.problem.title)
            : t("settings.saveFailed")}
        </p>
      )}

      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="btn btn-quiet">
          {t("common.cancel")}
        </button>
        <button
          type="button"
          disabled={!confirmed || erase.isPending}
          onClick={() => erase.mutate(undefined, { onSuccess: onErased })}
          className="btn btn-danger"
        >
          {t("erase.confirm")}
        </button>
      </div>
    </Modal>
  );
}
