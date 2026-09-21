"use client";

import { use, useState } from "react";
import { TaskComposer } from "@/components/crm/TaskComposer";
import { TaskRow } from "@/components/crm/TaskRow";
import { useEditTask, useMe, useTasks, type Bucket } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { useT } from "@/lib/i18n-client";

const BUCKETS: Bucket[] = ["overdue", "today", "upcoming", "done"];
const DEFAULTS = { bucket: "today", assignee: "me" };

export default function TasksPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const [filters, setFilters] = useFilters(DEFAULTS);
  const bucket = (BUCKETS.includes(filters.bucket as Bucket) ? filters.bucket : "today") as Bucket;
  const tasks = useTasks({ assignee: filters.assignee, bucket });
  const edit = useEditTask();
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
                    ? "text-red-600 dark:text-red-400"
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
            className="text-muted ms-auto min-h-11 rounded-md border border-black/10 px-2 text-sm dark:border-white/15"
          >
            <option value="me">{t("tasks.mine")}</option>
            <option value="team">{t("tasks.team")}</option>
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
            />
          ))}
        </ul>
      )}

      {undo && (
        // Undo is an ordinary edit, which is why this needs no endpoint of its own.
        <div className="bg-surface border-border fixed inset-x-4 bottom-24 mx-auto flex max-w-sm items-center justify-between gap-3 rounded-lg border p-3 text-sm shadow-lg md:bottom-6">
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
