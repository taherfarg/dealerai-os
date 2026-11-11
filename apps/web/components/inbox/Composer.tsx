"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { useAddNote, useQuickReplies, useSendMessage, type QuickReply } from "@/lib/api/hooks";
import { Icon } from "@/components/Icon";
import { useT } from "@/lib/i18n-client";
import { filled, matching, QuickReplyMenu } from "./QuickReplyMenu";
import { TemplatePicker } from "./TemplatePicker";

/**
 * Where a reply is written.
 *
 * The note toggle turns the whole thing yellow, because the difference between
 * a note and a message is the difference between a colleague reading it and a
 * customer reading it.
 */
export function Composer({
  conversationId,
  channelId = null,
  windowOpen,
  disabled,
  draftToEdit,
  onSent,
  language = null,
  customerName = null,
}: {
  conversationId: string;
  /** Whose templates to offer once the window has closed. */
  channelId?: string | null;
  windowOpen: boolean;
  disabled?: boolean;
  draftToEdit?: { id?: string; text: string };
  onSent?: () => void;
  /** The customer's, for a quick reply in their language with their name. */
  language?: string | null;
  customerName?: string | null;
}) {
  const t = useT();
  const [text, setText] = useState(draftToEdit?.text ?? "");
  const [isNote, setIsNote] = useState(false);
  const [suggestionId, setSuggestionId] = useState<string | undefined>(draftToEdit?.id);
  const send = useSendMessage(conversationId);
  const note = useAddNote(conversationId);
  const action = isNote ? note : send;

  // "/" and one word opens the quick replies; they are fetched only then.
  const typingShortcut = text.startsWith("/") && !/\s/.test(text);
  const replies = useQuickReplies(typingShortcut);
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const options = typingShortcut && dismissedAt !== text ? matching(replies.data ?? [], text) : [];
  const pick = (reply: QuickReply) => {
    setText(filled(reply, language, customerName));
    setActive(0);
  };

  // Outside the 24-hour window WhatsApp takes only templates, so free text is
  // refused here rather than failing after the customer expected an answer —
  // and a template is offered in its place. A note goes to nobody's phone, so
  // it can always be written.
  const blocked = disabled || (!isNote && !windowOpen);
  const template = !disabled && !isNote && !windowOpen && channelId;

  const submit = () => {
    const body = text.trim();
    if (!body || blocked) return;
    setText("");
    if (isNote) {
      note.mutate(body, { onError: () => setText(body) });
    } else {
      send.mutate(
        { text: body, suggestionId },
        {
          onError: () => setText(body),
          onSuccess: () => {
            setSuggestionId(undefined);
            onSent?.();
          },
        },
      );
    }
  };

  return (
    <div
      className={`border-border border-t px-3 py-2 lg:px-5 ${
        isNote ? "bg-warning-soft" : "bg-background"
      }`}
    >
      {action.isError && (
        <p className="mb-2 text-xs text-danger">
          {action.error instanceof ApiError
            ? (action.error.problem.detail ?? action.error.problem.title)
            : t("thread.sendFailed")}
        </p>
      )}

      {template && (
        <TemplatePicker
          conversationId={conversationId}
          channelId={template}
          language={language}
          customerName={customerName}
          onSent={onSent}
        />
      )}

      <QuickReplyMenu
        options={options}
        active={Math.min(active, options.length - 1)}
        onPick={pick}
      />

      {/* One row ([11] § 5.1): whether it is a note, the words, and the way
          out. On a phone the note switch is its drawing; its words stay. */}
      <div className="flex items-end gap-2">
        <button
          type="button"
          aria-pressed={isNote}
          onClick={() => setIsNote((was) => !was)}
          className={`btn max-sm:min-w-11 max-sm:px-0 ${
            isNote ? "bg-warning text-background border-transparent" : "btn-quiet"
          }`}
        >
          <Icon name="note" size={18} />
          <span className="max-sm:sr-only">{t("thread.internalNote")}</span>
        </button>
      {!template && (
        <>
          <textarea
            value={text}
            rows={1}
            disabled={blocked}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              // While the menu is open the keys are its: Enter picks a reply
              // into the box — it never sends one unread.
              if (options.length > 0) {
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  const step = event.key === "ArrowDown" ? 1 : -1;
                  setActive((index) => (index + step + options.length) % options.length);
                  return;
                }
                if (event.key === "Enter" && !event.shiftKey && !event.altKey) {
                  event.preventDefault();
                  pick(options[Math.min(active, options.length - 1)]);
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setDismissedAt(text);
                  return;
                }
              }
              // Alt+Enter is the draft panel's: sending what is typed here as
              // well would put two messages in front of the customer.
              if (event.key === "Enter" && !event.shiftKey && !event.altKey) {
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
            className="field max-h-40 min-w-0 flex-1 resize-none [field-sizing:content] disabled:opacity-60"
          />
          <button
            type="button"
            onClick={submit}
            disabled={blocked || !text.trim() || action.isPending}
            aria-label={t("thread.send")}
            className="icon-btn bg-accent text-on-accent hover:bg-accent shrink-0 disabled:opacity-50"
          >
            <span aria-hidden className="inline-block rtl:-scale-x-100">
              <Icon name="send" />
            </span>
          </button>
        </>
      )}
      </div>
    </div>
  );
}
