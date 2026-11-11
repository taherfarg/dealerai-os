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
        className="field mt-3 w-full"
      />
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="btn btn-quiet">
          {t("common.cancel")}
        </button>
        <button
          type="button"
          disabled={!reason.trim()}
          onClick={() => onConfirm(reason.trim())}
          className="btn btn-primary"
        >
          {t("lost.confirm")}
        </button>
      </div>
    </Modal>
  );
}
