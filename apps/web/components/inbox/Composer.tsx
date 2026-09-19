"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { useAddNote, useSendMessage } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * Where a reply is written.
 *
 * The note toggle turns the whole thing yellow, because the difference between
 * a note and a message is the difference between a colleague reading it and a
 * customer reading it.
 */
export function Composer({
  conversationId,
  windowOpen,
  disabled,
}: {
  conversationId: string;
  windowOpen: boolean;
  disabled?: boolean;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const [isNote, setIsNote] = useState(false);
  const send = useSendMessage(conversationId);
  const note = useAddNote(conversationId);
  const action = isNote ? note : send;

  // Outside the 24-hour window WhatsApp takes only templates, so free text is
  // refused here rather than failing after the customer expected an answer.
  const blocked = disabled || (!isNote && !windowOpen);

  const submit = () => {
    const body = text.trim();
    if (!body || blocked) return;
    setText("");
    action.mutate(body, { onError: () => setText(body) });
  };

  return (
    <div
      className={`border-t border-black/5 p-3 dark:border-white/10 ${
        isNote ? "bg-amber-50 dark:bg-amber-950/30" : ""
      }`}
    >
      <div className="mb-2 flex items-center gap-2">
        <button
          type="button"
          aria-pressed={isNote}
          onClick={() => setIsNote((was) => !was)}
          className={`min-h-11 rounded-md px-3 text-sm ${
            isNote ? "bg-amber-200 font-medium dark:bg-amber-800" : "hover:bg-background"
          }`}
        >
          {t("thread.internalNote")}
        </button>
        {action.isError && (
          <span className="text-xs text-red-600 dark:text-red-400">
            {action.error instanceof ApiError
              ? (action.error.problem.detail ?? action.error.problem.title)
              : t("thread.sendFailed")}
          </span>
        )}
      </div>

      <div className="flex items-end gap-2">
        <textarea
          value={text}
          rows={2}
          disabled={blocked}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={
            blocked
              ? t("thread.windowClosedHint")
              : isNote
                ? t("thread.notePlaceholder")
                : t("thread.placeholder")
          }
          aria-label={isNote ? t("thread.internalNote") : t("thread.placeholder")}
          className="min-h-11 flex-1 resize-none rounded-md border border-black/10 px-3 py-2 text-sm disabled:opacity-60 dark:border-white/15"
        />
        <button
          type="button"
          onClick={submit}
          disabled={blocked || !text.trim() || action.isPending}
          className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-black disabled:opacity-50"
        >
          {t("thread.send")}
        </button>
      </div>
    </div>
  );
}
