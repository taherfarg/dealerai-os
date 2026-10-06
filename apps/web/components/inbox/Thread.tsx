"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import {
  useAssignConversation,
  useConversation,
  useCreateLead,
  useCreateTask,
  useEditCustomer,
  useMarkRead,
  useMe,
  useMessages,
  useRegenerateSuggestion,
  useRetryMessage,
  useSendMessage,
  useSetConversationStatus,
  useSuggestion,
  useSuggestionOutcome,
  type SendReply,
  type Suggestion,
} from "@/lib/api/hooks";
import { useNow } from "@/lib/clock";
import { formatUntil } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import { useWide } from "@/lib/media";
import { Avatar } from "@/components/Avatar";
import { CustomerName } from "@/components/Bidi";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { CustomerPanel } from "@/components/crm/CustomerPanel";
import { Composer } from "./Composer";
import { DraftPanel } from "./DraftPanel";
import { LeadStrip } from "./LeadStrip";
import { MessageBubble } from "./MessageBubble";
import { WaitingTimer } from "./WaitingTimer";

/** One conversation: who it is, what was said, and what you can do about it. */
export function Thread({ tenant, conversationId }: { tenant: string; conversationId: string }) {
  const t = useT();
  const locale = useLocale();
  const me = useMe();
  const conversation = useConversation(conversationId);
  const messages = useMessages(conversationId);
  const markRead = useMarkRead(conversationId);
  const assign = useAssignConversation(conversationId);
  const setStatus = useSetConversationStatus(conversationId);
  const retry = useRetryMessage(conversationId);
  const suggestion = useSuggestion(conversationId);
  const regenerate = useRegenerateSuggestion(conversationId);
  const outcome = useSuggestionOutcome(conversationId);
  const sendDraft = useSendMessage(conversationId);
  const createLead = useCreateLead();
  const createTask = useCreateTask();
  const editCustomer = useEditCustomer(conversation.data?.contact.id ?? "");
  const now = useNow();
  const wide = useWide();
  const [panel, setPanel] = useState(false);
  const [draftToEdit, setDraftToEdit] = useState<{ id?: string; text: string }>();
  const sentDraft = useRef<string | null>(null);

  // Opening it is reading it — for this person only.
  const { mutate: read } = markRead;
  useEffect(() => {
    read();
  }, [read, conversationId]);

  useEffect(() => {
    try {
      const key = `dealerai:followup-edit:${conversationId}`;
      const saved = sessionStorage.getItem(key);
      if (!saved) return;
      sessionStorage.removeItem(key);
      const candidate = JSON.parse(saved) as { text?: unknown };
      if (typeof candidate.text === "string" && candidate.text.trim()) {
        queueMicrotask(() => setDraftToEdit({ text: candidate.text as string }));
      }
    } catch {
      // Opening the conversation still works in private storage modes.
    }
  }, [conversationId]);

  if (conversation.isError) {
    const problem = conversation.error instanceof ApiError ? conversation.error.problem : null;
    // "Not yours" and "not there" are one answer from the API, in a
    // developer's words. The screen has its own sentence for it — and with no
    // conversation to name, that sentence is this page's heading.
    const gone = !problem || problem.status === 404;
    return (
      <h1 className="p-6 text-sm font-normal text-danger">
        {gone ? t("thread.gone") : (problem.detail ?? problem.title)}
      </h1>
    );
  }
  if (!conversation.data) return <p className="text-muted p-6 text-sm">…</p>;

  const row = conversation.data;
  const windowOpen = Boolean(
    row.window_expires_at && new Date(row.window_expires_at).getTime() > now,
  );
  const mine = row.assignee?.id === me.data?.user.id;
  const pages = messages.data?.pages ?? [];
  // Pages walk backwards in time, so the oldest page is last.
  const thread = [...pages].reverse().flatMap((page) => page.data);
  const liveDraft = suggestion.data;
  const template = liveDraft?.template;
  const templateId = template && typeof template.template_id === "string" ? template.template_id : null;
  const cannotSendDraft = row.status !== "open" || (!windowOpen && !templateId);

  const sendSuggestion = (draft: Suggestion) => {
    const draftTemplate = draft.template;
    const id = draftTemplate?.template_id;
    const reply: SendReply | null =
      draftTemplate && typeof id === "string"
        ? {
            templateId: id,
            variables: Array.isArray(draftTemplate.variables)
              ? draftTemplate.variables.filter((value): value is string => typeof value === "string")
              : [],
            suggestionId: draft.id,
          }
        : draft.text && windowOpen
          ? { text: draft.text, suggestionId: draft.id }
          : null;
    // Once per draft, however fast Send is clicked or Alt+Enter repeats: the
    // panel stays up until the refetch lands, and a second press in that gap
    // would reach the customer twice. Only a failed send frees it again.
    if (!reply || sentDraft.current === draft.id) return;
    sentDraft.current = draft.id;
    sendDraft.mutate(reply, {
      onError: () => {
        sentDraft.current = null;
      },
    });
  };

  const showEvidence = (messageId: string) => {
    const bubble = document.getElementById(`message-${messageId}`);
    bubble?.scrollIntoView({ block: "center" });
    // CSS cannot quieten an animation started here, so this asks for itself.
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    bubble?.animate([{ opacity: 0.35 }, { opacity: 1 }], { duration: 900 });
  };

  const takeAction = async (action: Record<string, unknown>) => {
    if (action.kind === "create_lead") {
      await createLead.mutateAsync({
        contact_id: row.contact.id,
        ...(typeof action.vehicle_id === "string" ? { vehicle_id: action.vehicle_id } : {}),
      });
    } else if (action.kind === "create_task" && typeof action.title === "string" && typeof action.due_at === "string") {
      await createTask.mutateAsync({
        title: action.title,
        due_at: action.due_at,
        kind: "follow_up",
        contact_id: row.contact.id,
        conversation_id: conversationId,
      });
    } else if (action.kind === "update_profile" && typeof action.field === "string" && typeof action.value === "string") {
      await editCustomer.mutateAsync({ profile: { [action.field]: action.value } });
    } else {
      throw new Error("This suggested action is incomplete.");
    }
  };

  return (
    <div data-thread className="flex h-full min-h-0 flex-col">
      <header className="bg-background border-border border-b px-3 py-2 lg:px-5">
        <div className="flex items-center gap-2">
          <Link
            href={`/${tenant}/inbox`}
            aria-label={t("thread.back")}
            // A thumb's width, pulled back into the header's own padding.
            className="text-muted hover:bg-surface -ms-2 inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full lg:hidden"
          >
            {/* The arrow is drawn pointing one way; the span turns it round in Arabic. */}
            <span aria-hidden className="inline-block rtl:-scale-x-100">
              <Icon name="back" />
            </span>
          </Link>
          {/* The flag rides on the avatar, so the name beside it is given none. */}
          <Avatar name={row.contact.name} country={row.contact.country} />
          <h1 className="min-w-0 flex-1 text-[15px] font-semibold">
            <CustomerName country={null} name={row.contact.name} />
          </h1>
          {/* On a phone these are their drawings; their words stay, for a screen reader. */}
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <button
              type="button"
              aria-pressed={panel}
              onClick={() => setPanel((was) => !was)}
              className={`btn max-sm:min-w-11 max-sm:px-0 ${
                panel ? "bg-accent-soft text-accent-ink border-transparent" : ""
              }`}
            >
              <Icon name="person" size={18} className="sm:hidden" />
              <span className="max-sm:sr-only">{t("customer.details")}</span>
            </button>
            {row.status === "open" ? (
              <button
                type="button"
                onClick={() => setStatus.mutate("closed")}
                className="btn max-sm:min-w-11 max-sm:px-0"
              >
                <Icon name="check" size={18} className="sm:hidden" />
                <span className="max-sm:sr-only">{t("thread.close")}</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStatus.mutate("open")}
                className="btn max-sm:min-w-11 max-sm:px-0"
              >
                <Icon name="refresh" size={18} className="sm:hidden" />
                <span className="max-sm:sr-only">{t("thread.reopen")}</span>
              </button>
            )}
          </div>
        </div>
        {/* The timer sits here, under the name: beside it, on a phone, it
            took two lines and left the name three letters. Taking the
            conversation sits here too, beside the word that says nobody has. */}
        <div className="text-muted mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <WaitingTimer waitingSince={row.waiting_since} state={row.sla_state} />
          <span>
            {row.assignee
              ? `${mine ? t("thread.assignedToYou") : row.assignee.name}`
              : t("inbox.unassigned")}
            {" · "}
            {windowOpen
              ? `${t("thread.windowOpen")} ${formatUntil(row.window_expires_at ?? "", locale, new Date(now))}`
              : t("thread.windowClosed")}
          </span>
          {!row.assignee && (
            <button
              type="button"
              onClick={() => me.data && assign.mutate(me.data.user.id)}
              className="btn btn-primary ms-auto"
            >
              {t("thread.assignToMe")}
            </button>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* The conversation's own column. The customer panel stands beside all
            of it — the draft and the composer too — not only the messages. */}
        <div className="flex min-w-0 flex-1 flex-col">
        {/* While the panel is open it says the same thing, and says more. */}
        {!panel && <LeadStrip contactId={row.contact.id} onOpen={() => setPanel(true)} />}
        {/* It scrolls inside itself, so the keyboard has to be able to
            reach it: with nothing in it to Tab to, there is no other way to
            read the messages that are out of sight. */}
        <div tabIndex={0} className="min-h-0 flex-1 overflow-y-auto py-3">
          {messages.hasNextPage && (
            <button
              type="button"
              onClick={() => messages.fetchNextPage()}
              className="text-muted mx-auto block min-h-11 px-3 text-xs underline"
            >
              {t("thread.older")}
            </button>
          )}
          {/* A log ([07] § 10): a message that arrives is read out, politely,
              without taking the keyboard. Around the list, not on it — a log is
              not a list, and its items would stop being list items. */}
          <div role="log" aria-live="polite" aria-relevant="additions" aria-label={t("thread.messages")}>
            <ul>
              {thread.map((message) => (
                <MessageBubble key={message.id} message={message} onRetry={retry.mutate} />
              ))}
            </ul>
          </div>
        </div>
      <DraftPanel
        suggestion={liveDraft}
        onSend={sendSuggestion}
        onEdit={(draft) => draft.text && setDraftToEdit({ id: draft.id, text: draft.text })}
        onRegenerate={() => regenerate.mutate()}
        onOutcome={(id, reason) => outcome.mutate({ suggestionId: id, reason })}
        onAction={takeAction}
        sending={sendDraft.isPending}
        sendDisabled={cannotSendDraft}
        error={sendDraft.isError ? (sendDraft.error instanceof ApiError ? sendDraft.error.message : t("thread.sendFailed")) : null}
      />
      <Composer
        key={draftToEdit ? `${draftToEdit.id ?? "followup"}:${draftToEdit.text}` : "plain"}
        conversationId={conversationId}
        channelId={row.channel?.id}
        windowOpen={windowOpen}
        disabled={row.status !== "open"}
        draftToEdit={draftToEdit}
        onSent={() => setDraftToEdit(undefined)}
        language={row.contact.language}
        customerName={row.contact.name}
      />
        </div>

        {panel &&
          (wide ? (
            // A column beside the thread, there while a reply is being typed.
            <aside className="border-border bg-background w-80 shrink-0 overflow-y-auto border-s">
              <CustomerPanel tenant={tenant} contactId={row.contact.id} onEvidence={showEvidence} />
            </aside>
          ) : (
            // On a phone it covers the thread, so it is a dialog: focus goes in,
            // Escape comes out, and a screen reader is told the page changed.
            <Modal variant="sheet" label={t("customer.details")} onClose={() => setPanel(false)}>
              <CustomerPanel
                tenant={tenant}
                contactId={row.contact.id}
                onClose={() => setPanel(false)}
                onEvidence={(messageId) => {
                  // The message is underneath: put the sheet away to show it.
                  setPanel(false);
                  showEvidence(messageId);
                }}
              />
            </Modal>
          ))}
      </div>
    </div>
  );
}
