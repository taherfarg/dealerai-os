"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n-client";

/**
 * Why a lead was lost.
 *
 * The API refuses a lost lead without a reason, so this dialog is the UI half
 * of a rule that holds anyway — and the reason is the only thing anybody learns
 * from a lost deal.
 */
export function LostReasonDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const t = useT();
  const [reason, setReason] = useState("");
  return (
    <div
      role="dialog"
      aria-label={t("lost.title")}
      className="bg-surface border-border fixed inset-x-4 top-24 z-40 mx-auto max-w-sm rounded-lg border p-4 shadow-xl"
    >
      <h2 className="text-sm font-medium">{t("lost.title")}</h2>
      <input
        autoFocus
        value={reason}
        aria-label={t("lost.title")}
        placeholder={t("lost.placeholder")}
        onChange={(event) => setReason(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && reason.trim()) onConfirm(reason.trim());
          if (event.key === "Escape") onCancel();
        }}
        className="mt-3 min-h-11 w-full rounded-md border border-black/10 px-3 text-sm dark:border-white/15"
      />
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="min-h-11 px-3 text-sm">
          {t("common.cancel")}
        </button>
        <button
          type="button"
          disabled={!reason.trim()}
          onClick={() => onConfirm(reason.trim())}
          className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-black disabled:opacity-50"
        >
          {t("lost.confirm")}
        </button>
      </div>
    </div>
  );
}
