"use client";

import { useState } from "react";
import { formatMoney } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

export type Field = {
  value: unknown;
  source: "human" | "ai";
  evidence_message_id: string | null;
  updated_at?: string;
} | null;

const CHOICES: Record<string, string[]> = {
  purchase_type: ["local", "export"],
  payment: ["cash", "finance"],
};

function display(name: string, field: Field, t: (key: MessageKey) => string): string | null {
  if (!field || field.value === null || field.value === undefined) return null;
  const value = field.value;
  if (name === "budget" && typeof value === "object" && value !== null) {
    return formatMoney(value as { amount_minor: number; currency: string });
  }
  if (typeof value === "boolean") return value ? t("profile.yes") : t("profile.no");
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

/**
 * One thing we know about a customer, and who said so.
 *
 * The marker is not decoration. A salesperson has to know at a glance whether
 * the budget is what the customer said or what a model inferred, and be one
 * click from the message it was inferred from. Editing it makes it theirs,
 * which is what stops the next AI run overwriting it.
 */
export function ProfileField({
  name,
  field,
  onSave,
  onEvidence,
}: {
  name: string;
  field: Field;
  onSave: (value: unknown) => void;
  onEvidence?: (messageId: string) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const shown = display(name, field, t);
  const choices = CHOICES[name];

  const save = (raw: string) => {
    setEditing(false);
    const trimmed = raw.trim();
    if (trimmed === (shown ?? "")) return;
    if (!trimmed) return onSave(null);
    if (name === "budget") {
      const digits = Number(trimmed.replace(/[^\d]/g, ""));
      return onSave(Number.isFinite(digits) ? { amount_minor: digits * 100 } : null);
    }
    if (name === "trade_in") return onSave(trimmed.toLowerCase() !== t("profile.no").toLowerCase());
    if (name === "objections") return onSave(trimmed.split(",").map((part) => part.trim()));
    onSave(trimmed);
  };

  return (
    <div
      className="flex items-baseline justify-between gap-2 py-1.5"
      data-field={name}
      data-source={field?.source ?? "none"}
    >
      <span className="text-muted shrink-0 text-xs">{t(`profile.${name}` as MessageKey)}</span>

      {editing ? (
        choices ? (
          <select
            autoFocus
            defaultValue={String(field?.value ?? "")}
            onChange={(event) => save(event.target.value)}
            onBlur={() => setEditing(false)}
            className="min-h-11 rounded-md border border-black/10 px-2 text-sm dark:border-white/15"
            aria-label={t(`profile.${name}` as MessageKey)}
          >
            <option value="">{t("profile.unknown")}</option>
            {choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </select>
        ) : (
          <input
            autoFocus
            defaultValue={shown ?? ""}
            aria-label={t(`profile.${name}` as MessageKey)}
            onBlur={(event) => save(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") save(event.currentTarget.value);
              if (event.key === "Escape") setEditing(false);
            }}
            className="min-h-11 w-40 rounded-md border border-black/10 px-2 text-end text-sm dark:border-white/15"
          />
        )
      ) : (
        <span className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setEditing(true)}
            className={`text-sm ${shown ? "" : "text-muted italic"}`}
          >
            {shown ?? t("profile.unknown")}
          </button>
          {field?.source === "ai" && (
            <button
              type="button"
              disabled={!field.evidence_message_id}
              title={t("profile.evidence")}
              aria-label={t("profile.evidence")}
              onClick={() => field.evidence_message_id && onEvidence?.(field.evidence_message_id)}
              className="rounded bg-blue-500/15 px-1 text-[10px] font-medium uppercase text-blue-700 disabled:opacity-60 dark:text-blue-300"
            >
              {t("profile.fromAi")}
            </button>
          )}
        </span>
      )}
    </div>
  );
}
