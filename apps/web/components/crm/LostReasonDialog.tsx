"use client";

import { useState } from "react";
import { Modal } from "@/components/Modal";
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
    <Modal title={t("lost.title")} onClose={onCancel}>
      <input
        autoFocus
        value={reason}
        aria-label={t("lost.title")}
        placeholder={t("lost.placeholder")}
        onChange={(event) => setReason(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && reason.trim()) onConfirm(reason.trim());
        }}
        className="mt-3 min-h-11 w-full rounded-md border border-border px-3 text-sm"
      />
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="min-h-11 px-3 text-sm">
          {t("common.cancel")}
        </button>
        <button
          type="button"
          disabled={!reason.trim()}
          onClick={() => onConfirm(reason.trim())}
          className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-on-accent disabled:opacity-50"
        >
          {t("lost.confirm")}
        </button>
      </div>
    </Modal>
  );
}
