"use client";

import Link from "next/link";
import type { Task } from "@/lib/api/hooks";
import { useNow } from "@/lib/clock";
import { formatRelative } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { FollowUpCard } from "./FollowUpCard";

const KIND_ICON: Record<Task["kind"], string> = {
  follow_up: "↩",
  call: "☎",
  meeting: "🗓",
  todo: "•",
};

/** An hour, tomorrow morning, next week — the three snoozes anybody uses. */
export function snoozeOptions(
  now: Date,
): { key: "snoozeHour" | "snoozeTomorrow" | "snoozeWeek"; at: Date }[] {
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(9, 0, 0, 0);
  const week = new Date(now);
  week.setDate(week.getDate() + 7);
  week.setHours(9, 0, 0, 0);
  return [
    { key: "snoozeHour", at: new Date(now.getTime() + 3_600_000) },
    { key: "snoozeTomorrow", at: tomorrow },
    { key: "snoozeWeek", at: week },
  ];
}

/**
 * One thing to do.
 *
 * Overdue is red and says so in words as well: a colour-blind salesperson and
 * a screen reader both have to be able to tell a late task from a later one.
 */
export function TaskRow({
  task,
  tenant,
  showAssignee,
  onComplete,
  onSnooze,
  onSendDraft,
  onSkipDraft,
  now,
}: {
  task: Task;
  tenant: string;
  showAssignee?: boolean;
  onComplete: (done: boolean) => void;
  onSnooze: (at: Date) => void;
  onSendDraft: (taskId: string) => Promise<void>;
  onSkipDraft: (taskId: string, reason: string) => Promise<void>;
  /** Fixed clock, for tests. */
  now?: number;
}) {
  const t = useT();
  const clock = useNow(60_000, now);
  const done = task.status !== "open";
  const overdue = !done && new Date(task.due_at).getTime() < clock;

  return (
    <li
      data-task={task.id}
      data-overdue={overdue}
      className="flex flex-wrap items-center gap-3 border-b border-black/5 py-2 dark:border-white/10"
    >
      <input
        type="checkbox"
        checked={done}
        aria-label={t("tasks.complete")}
        onChange={(event) => onComplete(event.target.checked)}
        className="size-4 shrink-0"
      />

      <span className="min-w-0 flex-1">
        <span className={`block truncate text-sm ${done ? "text-muted line-through" : ""}`}>
          <span aria-hidden className="me-1">
            {KIND_ICON[task.kind]}
          </span>
          {task.title}
          {task.source === "ai" && (
            <span className="ms-2 rounded bg-blue-500/15 px-1 text-[10px] uppercase text-blue-700 dark:text-blue-300">
              {t("tasks.ai")}
            </span>
          )}
        </span>
        {task.contact && (
          <Link
            href={`/${tenant}/customers/${task.contact.id}`}
            className="text-muted truncate text-xs underline"
          >
            {task.contact.name}
          </Link>
        )}
      </span>

      {showAssignee && task.assignee && (
        <span className="text-muted shrink-0 text-xs">{task.assignee.name}</span>
      )}

      <time
        dateTime={task.due_at}
        className={`shrink-0 text-xs ${overdue ? "font-medium text-red-600 dark:text-red-400" : "text-muted"}`}
      >
        {overdue && <span className="me-1">{t("tasks.overdue")}</span>}
        {formatRelative(task.due_at, new Date(clock))}
      </time>

      {!done && (
        <select
          aria-label={t("tasks.snooze")}
          value=""
          onChange={(event) => {
            const chosen = snoozeOptions(new Date(clock)).find(
              (option) => option.key === event.target.value,
            );
            if (chosen) onSnooze(chosen.at);
          }}
          className="text-muted min-h-11 shrink-0 rounded-md border border-black/10 bg-transparent text-xs dark:border-white/15"
        >
          <option value="">{t("tasks.snooze")}</option>
          {snoozeOptions(new Date(clock)).map((option) => (
            <option key={option.key} value={option.key}>
              {t(`tasks.${option.key}`)}
            </option>
          ))}
        </select>
      )}

      {!done && task.source === "ai" && task.ai_draft && (
        <div className="basis-full ps-7">
          <FollowUpCard
            task={task}
            tenant={tenant}
            onSend={() => onSendDraft(task.id)}
            onSkip={(reason) => onSkipDraft(task.id, reason)}
          />
        </div>
      )}
    </li>
  );
}
