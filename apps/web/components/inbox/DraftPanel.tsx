"use client";

import { useEffect, useState } from "react";
import type { Suggestion } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { Icon } from "@/components/Icon";
import { useT } from "@/lib/i18n-client";
import { blockedReasons } from "@/lib/words";

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
      <div className="text-muted px-3 py-2 text-sm lg:px-5" role="status" dir="auto">
        {t("draft.blocked")}:{" "}
        {suggestion.blocked_reason
          ? blockedReasons(t, suggestion.blocked_reason)
          : t("draft.unavailable")}
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
    // Still a region of its own, outside the log: always in view, and never
    // read out as a message. Drawn as a bubble on our side that has not gone
    // yet — white, with a dashed outline ([11] § 5.1).
    <section className="px-3 pb-2 lg:px-5" aria-label={t("draft.title")}>
      <div className="border-accent bg-background ms-auto max-w-2xl rounded-[1.375rem] rounded-ee-md border border-dashed px-4 py-2">
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        <span className="text-accent-ink inline-flex items-center gap-1.5 text-xs font-semibold">
          <Icon name="spark" size={16} />
          {t("draft.title")}
        </span>
        {ready && suggestion.confidence && (
          <span className={`pill ${suggestion.confidence === "low" ? "pill-warning" : "pill-accent"}`}>
            {t(`draft.confidence.${suggestion.confidence as "low" | "medium" | "high"}`)}
          </span>
        )}
        {suggestion.intent && (
          <span className="pill">
            {INTENTS.has(suggestion.intent)
              ? t(`draft.intent.${suggestion.intent}` as MessageKey)
              : suggestion.intent.replaceAll("_", " ")}
          </span>
        )}
        </div>
        {!low && (
          <button
            type="button"
            className="icon-btn text-muted shrink-0"
            aria-label={collapsed ? t("draft.expand") : t("draft.collapse")}
            onClick={() => setOpen(collapsed)}
          >
            <Icon name={collapsed ? "chevronDown" : "chevronUp"} />
          </button>
        )}
      </div>
      {!folded && (
        <div>
          {ready ? (
            <>
              <p className="mt-1 whitespace-pre-wrap text-base leading-7 lg:text-[15px]" dir="auto">{body}</p>
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
                        className="btn text-xs"
                        dir="auto"
                        onClick={() => setOpenedDocument(openedDocument === String(index) ? null : String(index))}
                      >
                        {label}
                      </button>
                      {openedDocument === String(index) && excerpt && (
                        <p className="text-muted mt-1 max-w-lg whitespace-pre-wrap rounded bg-surface p-2" dir="auto">
                          {excerpt}
                        </p>
                      )}
                    </span>
                  ) : (
                    <span key={index} dir="auto" className="pill">
                      {label}
                    </span>
                  );
                })}
                {noSources && <span className="text-warning">{t("draft.noSources")}</span>}
              </div>
              {suggestion.needs_human && (
                <p
                  className="mt-2 rounded-md bg-warning-soft p-2 text-sm text-foreground"
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
                      className="btn text-xs"
                      dir="auto"
                    >
                      {stringAt(action, "label") ?? t("draft.action")}
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" disabled={!canSend} onClick={() => onSend(suggestion)} className="btn btn-primary">
                  <span aria-hidden className="inline-block rtl:-scale-x-100">
                    <Icon name="send" size={16} />
                  </span>
                  {t("draft.send")}
                </button>
                <button type="button" disabled={!suggestion.text} onClick={() => onEdit(suggestion)} className="btn">
                  {t("draft.edit")}
                </button>
                <button type="button" onClick={onRegenerate} className="btn btn-quiet">
                  {t("draft.regenerate")}
                </button>
                <button type="button" onClick={() => setDismiss(true)} className="btn btn-quiet">
                  {t("draft.dismiss")}
                </button>
              </div>
              {sendDisabled && <p className="text-muted mt-1 text-xs">{t("draft.windowClosed")}</p>}
              {(error || actionError) && <p role="alert" className="mt-1 text-xs text-danger">{error || actionError}</p>}
              {dismiss && (
                <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={t("draft.dismissReason")}>
                  {REASONS.map((reason) => (
                    <button
                      key={reason}
                      type="button"
                      className="btn text-xs"
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
      </div>
    </section>
  );
}
