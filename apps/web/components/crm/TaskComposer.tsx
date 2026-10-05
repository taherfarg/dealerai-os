"use client";

import { useState } from "react";
import { useCreateTask } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/** Adding a task: a line and a time, because anything longer never gets used. */
export function TaskComposer({
  contactId,
  leadId,
  conversationId,
}: {
  contactId?: string;
  leadId?: string;
  conversationId?: string;
}) {
  const t = useT();
  const create = useCreateTask();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(() => {
    const later = new Date(Date.now() + 3_600_000);
    // datetime-local wants the local clock without a zone, trimmed to minutes.
    return new Date(later.getTime() - later.getTimezoneOffset() * 60_000)
      .toISOString()
      .slice(0, 16);
  });

  const add = () => {
    if (!title.trim()) return;
    create.mutate(
      {
        title: title.trim(),
        due_at: new Date(due).toISOString(),
        kind: "todo",
        contact_id: contactId,
        lead_id: leadId,
        conversation_id: conversationId,
      },
      { onSuccess: () => setTitle("") },
    );
  };

  return (
    <div className="flex flex-wrap items-end gap-2">
      <input
        value={title}
        placeholder={t("tasks.newTitle")}
        aria-label={t("tasks.newTitle")}
        onChange={(event) => setTitle(event.target.value)}
        onKeyDown={(event) => event.key === "Enter" && add()}
        className="min-h-11 flex-1 rounded-md border border-border px-3 text-sm"
      />
      <input
        type="datetime-local"
        value={due}
        aria-label={t("tasks.due")}
        onChange={(event) => setDue(event.target.value)}
        className="min-h-11 rounded-md border border-border px-2 text-sm"
      />
      <button
        type="button"
        onClick={add}
        disabled={!title.trim() || create.isPending}
        className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-on-accent disabled:opacity-50"
      >
        {t("tasks.add")}
      </button>
    </div>
  );
}
