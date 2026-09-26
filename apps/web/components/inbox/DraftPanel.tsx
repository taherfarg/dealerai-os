"use client";

import { useEffect, useState } from "react";
import type { Suggestion } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

export type DiscardReason = "wrong_info" | "wrong_tone" | "not_needed" | "other";
type Source = Record<string, unknown>;

const STORAGE_KEY = "dealerai:draft-collapsed";
const FACT_INTENTS = new Set(["price", "availability", "specs", "export_shipping", "documents_payment"]);
const REASONS: DiscardReason[] = ["wrong_info", "wrong_tone", "not_needed", "other"];
const INTENTS = new Set([
  "greeting", "price", "availability", "specs", "export_shipping", "financing", "trade_in",
  "visit_test_drive", "documents_payment", "negotiation", "complaint", "human_request",
  "opt_out", "other",
]);

function stringAt(row: Source, key: string): string | null {
  return typeof row[key] === "string" ? (row[key] as string) : null;
}

function savedCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function DraftPanel({
  suggestion,
  onSend,
  onEdit,
  onRegenerate,
  onOutcome,
  onAction,
  sending = false,
  sendDisabled = false,
  error,
}: {
  suggestion: Suggestion | null | undefined;
  onSend: (suggestion: Suggestion) => void;
  onEdit: (suggestion: Suggestion) => void;
  onRegenerate: () => void;
  onOutcome: (id: string, reason: DiscardReason) => void;
  onAction?: (action: Record<string, unknown>) => Promise<void>;
  sending?: boolean;
  sendDisabled?: boolean;
  error?: string | null;
}) {
  const t = useT();
  const [collapsed, setCollapsed] = useState(savedCollapsed);
  const [dismiss, setDismiss] = useState(false);
  const [openedDocument, setOpenedDocument] = useState<string | null>(null);
  const [doneActions, setDoneActions] = useState<number[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const canSend =
    suggestion?.status === "ready" &&
    !sending &&
    !sendDisabled &&
    Boolean(suggestion.text || suggestion.template);

  // Alt+Enter sends from anywhere in the thread (08 §4) — a key a person
  // presses, never a timer. Auto-repeat is ignored; the thread lets each draft
  // go once.
  useEffect(() => {
    if (!canSend || !suggestion) return;
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey || event.key !== "Enter" || event.repeat) return;
      event.preventDefault();
      onSend(suggestion);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canSend, suggestion, onSend]);

  if (!suggestion || suggestion.status === "superseded") return null;

  if (suggestion.status === "blocked") {
    return (
      <div className="text-muted border-border border-t px-3 py-2 text-sm" role="status" dir="auto">
        {t("draft.blocked")}: {suggestion.blocked_reason ?? t("draft.unavailable")}
      </div>
    );
  }

  const ready = suggestion.status === "ready";
  const template = suggestion.template;
  const templateName = template && stringAt(template, "name");
  // A template shows the message it will send, not its name: read unread,
  // Send would put words in front of the customer nobody had seen.
  const body = suggestion.text || (template && stringAt(template, "preview")) || templateName || "";
  const noSources = FACT_INTENTS.has(suggestion.intent ?? "") && suggestion.sources.length === 0;
  // A low-confidence draft is the one worth reading, so it cannot be folded
  // away — a remembered "collapsed" must not hide it.
  const low = suggestion.confidence === "low";
  const folded = collapsed && !low;
  const setOpen = (value: boolean) => {
    setCollapsed(!value);
    try {
      localStorage.setItem(STORAGE_KEY, String(!value));
    } catch {
      // Browsers that block storage still get a working panel.
    }
  };

  return (
    <section className="border-border bg-surface border-t px-3 py-2" aria-label={t("draft.title")}>
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide">{t("draft.title")}</span>
        {ready && suggestion.confidence && (
          <span
            className={`rounded px-2 py-0.5 text-xs font-medium ${
              suggestion.confidence === "low"
                ? "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100"
                : "bg-blue-500/10 text-blue-700 dark:text-blue-200"
            }`}
          >
            {t(`draft.confidence.${suggestion.confidence as "low" | "medium" | "high"}`)}
          </span>
        )}
        {suggestion.intent && (
          <span className="text-muted text-xs">
            {INTENTS.has(suggestion.intent)
              ? t(`draft.intent.${suggestion.intent}` as MessageKey)
              : suggestion.intent.replaceAll("_", " ")}
          </span>
        )}
        {!low && (
          <button
            type="button"
            className="text-muted ms-auto min-h-11 px-2 text-xs underline"
            aria-label={collapsed ? t("draft.expand") : t("draft.collapse")}
            onClick={() => setOpen(collapsed)}
          >
            {collapsed ? t("draft.expand") : t("draft.collapse")}
          </button>
        )}
      </div>
      {!folded && (
        <div>
          {ready ? (
            <>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-6" dir="auto">{body}</p>
              {templateName && (
                <p className="text-muted mt-1 text-xs">{t("draft.template")}: {templateName}</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">{t("draft.basedOn")}</span>
                {suggestion.sources.map((source, index) => {
                  const kind = stringAt(source, "kind");
                  const name = stringAt(source, "label") ?? stringAt(source, "title") ?? t("draft.source");
                  // The last step of "Financing › Who can finance a car with us".
                  const section = stringAt(source, "section")?.split("›").pop()?.trim();
                  const label = section ? `${name} · ${section}` : name;
                  const excerpt = stringAt(source, "excerpt");
                  return kind === "document" ? (
                    <span key={index}>
                      <button
                        type="button"
                        className="rounded-full border border-black/15 px-2 py-1 dark:border-white/20"
                        onClick={() => setOpenedDocument(openedDocument === String(index) ? null : String(index))}
                      >
                        {label}
                      </button>
                      {openedDocument === String(index) && excerpt && (
                        <p className="text-muted mt-1 max-w-lg whitespace-pre-wrap rounded bg-black/5 p-2 dark:bg-white/5" dir="auto">
                          {excerpt}
                        </p>
                      )}
                    </span>
                  ) : (
                    <span key={index} className="rounded-full border border-black/15 px-2 py-1 dark:border-white/20">
                      {label}
                    </span>
                  );
                })}
                {noSources && <span className="text-amber-800 dark:text-amber-200">{t("draft.noSources")}</span>}
              </div>
              {suggestion.needs_human && (
                <p
                  className="mt-2 rounded-md bg-amber-100 p-2 text-sm text-amber-950 dark:bg-amber-900/40 dark:text-amber-100"
                  // Written in English for the team, inside an Arabic page:
                  // without it the full stop lands at the start of the line.
                  dir="auto"
                >
                  {suggestion.needs_human}
                </p>
              )}
              {suggestion.actions.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {suggestion.actions.map((action, index) => (
                    doneActions.includes(index) ? null :
                    <button
                      key={index}
                      type="button"
                      disabled={!onAction}
                      onClick={async () => {
                        if (!onAction) return;
                        try {
                          await onAction(action);
                          setDoneActions((old) => [...old, index]);
                          setActionError(null);
                        } catch (failure) {
                          setActionError(failure instanceof Error ? failure.message : t("draft.actionFailed"));
                        }
                      }}
                      className="rounded-md border border-black/15 px-2 py-1 text-xs disabled:opacity-50 dark:border-white/20"
                    >
                      {stringAt(action, "label") ?? t("draft.action")}
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <button type="button" disabled={!canSend} onClick={() => onSend(suggestion)} className="bg-accent min-h-11 rounded-md px-3 font-semibold text-black disabled:opacity-50">
                  {t("draft.send")}
                </button>
                <button type="button" disabled={!suggestion.text} onClick={() => onEdit(suggestion)} className="min-h-11 rounded-md border border-black/15 px-3 disabled:opacity-50 dark:border-white/20">
                  {t("draft.edit")}
                </button>
                <button type="button" onClick={onRegenerate} className="min-h-11 rounded-md border border-black/15 px-3 dark:border-white/20">
                  {t("draft.regenerate")}
                </button>
                <button type="button" onClick={() => setDismiss(true)} className="min-h-11 rounded-md px-3 underline">
                  {t("draft.dismiss")}
                </button>
              </div>
              {sendDisabled && <p className="text-muted mt-1 text-xs">{t("draft.windowClosed")}</p>}
              {(error || actionError) && <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">{error || actionError}</p>}
              {dismiss && (
                <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={t("draft.dismissReason")}>
                  {REASONS.map((reason) => (
                    <button
                      key={reason}
                      type="button"
                      className="min-h-11 rounded-md border border-black/15 px-2 text-xs dark:border-white/20"
                      onClick={() => { onOutcome(suggestion.id, reason); setDismiss(false); }}
                    >
                      {t(`draft.reason.${reason}`)}
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-muted mt-2 text-sm">{t("draft.generating")}</p>
          )}
        </div>
      )}
    </section>
  );
}
