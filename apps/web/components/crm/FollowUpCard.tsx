"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import type { Task } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

function value(row: Record<string, unknown>, key: string): string | null {
  return typeof row[key] === "string" ? (row[key] as string) : null;
}

/** The salesperson sees the reason before deciding whether this message exists. */
export function FollowUpCard({
  task,
  tenant,
  onSend,
  onSkip,
}: {
  task: Task;
  tenant: string;
  onSend: () => Promise<void>;
  onSkip: (reason: string) => Promise<void>;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const locked = useRef(false);
  const draft = task.ai_draft ?? {};
  const reason = value(draft, "reason") ?? task.title;
  const text = value(draft, "text");
  const templateId = value(draft, "template_id");
  const templateName = value(draft, "template_name");
  const preview = value(draft, "preview");
  const sendable = Boolean(text || templateId);
  const conversation = task.conversation_id ? `/${tenant}/inbox/${task.conversation_id}` : null;

  const send = async () => {
    if (locked.current || sent) return;
    locked.current = true;
    setBusy(true);
    setError(null);
    try {
      await onSend();
      setSent(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t("followup.failed"));
      locked.current = false;
    } finally {
      setBusy(false);
    }
  };

  const skip = async () => {
    if (!skipReason.trim() || locked.current) return;
    locked.current = true;
    setBusy(true);
    setError(null);
    try {
      await onSkip(skipReason.trim());
      setSent(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t("followup.failed"));
      locked.current = false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 rounded-lg border border-info/20 bg-info-soft p-3 text-sm">
      <p className="font-semibold" dir="auto">{reason}</p>
      {text && <p className="mt-2 whitespace-pre-wrap" dir="auto">{text}</p>}
      {templateId && preview && (
        <p className="mt-2 whitespace-pre-wrap" dir="auto">{preview}</p>
      )}
      {templateId && (
        <p className="mt-2 text-xs">
          {t("followup.windowClosed")} {t("followup.template")}: {templateName ?? templateId}
          {!preview && Array.isArray(draft.variables) && draft.variables.length > 0 &&
            ` · ${draft.variables.map(String).join(" · ")}`}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        {sendable ? (
          <>
            <button
              type="button"
              disabled={busy || sent}
              onClick={() => void send()}
              className="bg-accent min-h-11 rounded-md px-3 font-semibold text-on-accent disabled:opacity-50"
            >
              {t("followup.send")}
            </button>
            {conversation && (
              <Link
                href={conversation}
                onClick={() => {
                  if (!text || !task.conversation_id) return;
                  try {
                    sessionStorage.setItem(
                      `dealerai:followup-edit:${task.conversation_id}`,
                      JSON.stringify({ text }),
                    );
                  } catch {
                    // The conversation still opens if this browser blocks storage.
                  }
                }}
                className="min-h-11 rounded-md border border-border-strong px-3 py-3"
              >
                {t("followup.edit")}
              </Link>
            )}
            <button type="button" disabled={busy || sent} onClick={() => setSkipping(true)} className="min-h-11 px-2 underline">
              {t("followup.skip")}
            </button>
          </>
        ) : conversation ? (
          <Link href={conversation} className="min-h-11 py-3 underline">{t("followup.open")}</Link>
        ) : null}
      </div>
      {skipping && !sent && (
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            value={skipReason}
            onChange={(event) => setSkipReason(event.target.value)}
            aria-label={t("followup.skipReason")}
            className="min-h-11 min-w-40 flex-1 rounded-md border border-border-strong bg-transparent px-2"
          />
          <button type="button" disabled={!skipReason.trim() || busy} onClick={() => void skip()} className="min-h-11 rounded-md border border-border-strong px-3 disabled:opacity-50">
            {t("followup.confirmSkip")}
          </button>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}
    </div>
  );
}
