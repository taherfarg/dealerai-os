"use client";

import { useState } from "react";
import { useDeleteQuickReply, useMe, useQuickReplies, type QuickReply } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";
import { QuickReplyForm } from "./QuickReplyForm";

const LANGUAGES = ["ar", "en", "fr"] as const;

/**
 * The shortcuts every salesperson types (08-screens § 13). A salesperson
 * reads them here; whoever holds settings.quick_replies changes them.
 */
export function QuickReplySettings() {
  const t = useT();
  const me = useMe();
  const replies = useQuickReplies();
  const remove = useDeleteQuickReply();
  const [editing, setEditing] = useState<QuickReply | "new" | null>(null);
  const canEdit = (me.data?.permissions ?? []).includes("settings.quick_replies");

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold">{t("settings.quickReplies")}</h1>
      {!canEdit && <p className="text-muted text-sm">{t("quick.readOnly")}</p>}
      {canEdit && editing === null && (
        <button
          type="button"
          onClick={() => setEditing("new")}
          className="bg-accent min-h-11 self-start rounded-md px-4 text-sm font-medium text-on-accent"
        >
          {t("quick.add")}
        </button>
      )}
      {editing && (
        <QuickReplyForm
          key={editing === "new" ? "new" : editing.id}
          reply={editing === "new" ? null : editing}
          onDone={() => setEditing(null)}
        />
      )}
      {(replies.data ?? []).length === 0 && !replies.isLoading && (
        <p className="text-muted text-sm">{t("quick.empty")}</p>
      )}
      <ul className="flex flex-col gap-2">
        {(replies.data ?? []).map((reply) => (
          <li key={reply.id} className="bg-surface border-border rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-baseline gap-2">
                <span className="font-mono" dir="ltr">
                  {reply.shortcut}
                </span>
                <span className="text-muted" dir="auto">
                  {reply.title}
                </span>
              </span>
              {canEdit && (
                <span className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => setEditing(reply)}
                    className="hover:bg-background min-h-11 rounded-md px-3"
                  >
                    {t("quick.edit")}
                  </button>
                  <button
                    type="button"
                    onClick={() => remove.mutate(reply.id)}
                    className="hover:bg-background min-h-11 rounded-md px-3 text-danger"
                  >
                    {t("quick.delete")}
                  </button>
                </span>
              )}
            </div>
            {LANGUAGES.map(
              (code) =>
                reply.body[code] && (
                  // The row runs the way its text does — the label has a dir
                  // of its own, so it is not what "auto" reads — and the gap
                  // is the row's: a margin on the label fell on its far side.
                  <p key={code} className="text-muted mt-1 flex gap-2 text-xs" dir="auto">
                    <span className="shrink-0 font-semibold uppercase" dir="ltr">
                      {code}
                    </span>
                    <span className="min-w-0">{reply.body[code]}</span>
                  </p>
                ),
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
