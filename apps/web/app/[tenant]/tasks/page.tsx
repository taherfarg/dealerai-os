"use client";

import { use, useState } from "react";
import { TaskComposer } from "@/components/crm/TaskComposer";
import { TaskRow } from "@/components/crm/TaskRow";
import {
  useEditTask,
  useMe,
  useMembers,
  useSendDraft,
  useTasks,
  type Bucket,
} from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { useT } from "@/lib/i18n-client";

const BUCKETS: Bucket[] = ["overdue", "today", "upcoming", "done"];
const DEFAULTS = { bucket: "today", assignee: "me" };

export default function TasksPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const members = useMembers();
  const [filters, setFilters] = useFilters(DEFAULTS);
  const bucket = (BUCKETS.includes(filters.bucket as Bucket) ? filters.bucket : "today") as Bucket;
  const tasks = useTasks({ assignee: filters.assignee, bucket });
  const edit = useEditTask();
  const sendDraft = useSendDraft();
  const [undo, setUndo] = useState<string | null>(null);

  const isManager = me.data?.role !== "sales";
  const rows = tasks.data ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-lg font-semibold">{t("tasks.title")}</h1>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <div role="tablist" className="flex gap-1">
          {BUCKETS.map((name) => (
            <button
              key={name}
              role="tab"
              type="button"
              aria-selected={bucket === name}
              onClick={() => setFilters({ bucket: name })}
              className={`min-h-11 rounded-md px-3 text-sm ${
                bucket === name
                  ? "bg-background font-medium"
                  : name === "overdue"
                    ? "text-danger"
                    : "text-muted"
              }`}
            >
              {t(`tasks.${name}`)}
            </button>
          ))}
        </div>

        {isManager && (
          <select
            value={filters.assignee}
            aria-label={t("tasks.team")}
            onChange={(event) => setFilters({ assignee: event.target.value })}
            className="text-muted ms-auto min-h-11 rounded-md border border-border px-2 text-sm"
          >
            <option value="me">{t("tasks.mine")}</option>
            <option value="team">{t("tasks.team")}</option>
            {/* One person, so a link from the dashboard opens with their name showing. */}
            {(members.data ?? [])
              .filter((member) => member.id !== me.data?.user.id && member.role !== "viewer")
              .map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name ?? member.email}
                </option>
              ))}
          </select>
        )}
      </div>

      <div className="mt-4">
        <TaskComposer />
      </div>

      {rows.length === 0 ? (
        <p className="text-muted mt-8 text-center text-sm">{t("tasks.empty")}</p>
      ) : (
        <ul className="mt-4">
          {rows.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              tenant={tenant}
              showAssignee={filters.assignee === "team"}
              onComplete={(done) => {
                edit.mutate({ id: task.id, status: done ? "done" : "open" });
                setUndo(done ? task.id : null);
              }}
              onSnooze={(at) => edit.mutate({ id: task.id, due_at: at.toISOString() })}
              onSendDraft={async (id) => { await sendDraft.mutateAsync(id); }}
              onSkipDraft={async (id, reason) => {
                await edit.mutateAsync({ id, status: "cancelled", cancel_reason: reason });
              }}
            />
          ))}
        </ul>
      )}

      {undo && (
        // Undo is an ordinary edit, which is why this needs no endpoint of its own.
        <div className="bg-surface border-border fixed inset-x-4 bottom-28 mx-auto flex max-w-sm items-center justify-between gap-3 rounded-lg border p-3 text-sm shadow-lg md:bottom-6">
          <span>{t("tasks.completed")}</span>
          <button
            type="button"
            onClick={() => {
              edit.mutate({ id: undo, status: "open" });
              setUndo(null);
            }}
            className="min-h-11 font-medium underline"
          >
            {t("tasks.undo")}
          </button>
        </div>
      )}
    </div>
  );
}
