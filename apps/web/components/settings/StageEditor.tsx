"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { useReplaceStages, type Pipeline, type Stage } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

type Editable = { id?: string; name: string; category: Stage["category"] };

const CATEGORIES = ["open", "won", "lost"] as const;
const FIELD = "min-h-11 rounded-md border border-black/10 px-2 dark:border-white/15";

/**
 * One board's stages, as they will be saved, in order. The PUT replaces the
 * list whole (routes/pipelines.py), so there is no half-saved board; and a
 * stage that still holds leads is refused with a sentence saying how many.
 */
export function StageEditor({ pipeline }: { pipeline: Pipeline }) {
  const t = useT();
  const replace = useReplaceStages(pipeline.id);
  const saved: Editable[] = pipeline.stages.map(({ id, name, category }) => ({
    id,
    name,
    category,
  }));
  const [draft, setDraft] = useState<Editable[] | null>(null);
  const stages = draft ?? saved;
  const dirty = JSON.stringify(stages) !== JSON.stringify(saved);
  const set = (next: Editable[]) => {
    replace.reset();
    setDraft(next);
  };
  const move = (index: number, step: -1 | 1) => {
    const copy = [...stages];
    [copy[index], copy[index + step]] = [copy[index + step], copy[index]];
    set(copy);
  };

  return (
    <section className="bg-surface border-border rounded-lg border p-3">
      <h2 className="text-sm font-semibold" dir="auto">
        {pipeline.name}
      </h2>
      <ol className="mt-2 flex flex-col gap-1">
        {stages.map((stage, index) => (
          <li key={stage.id ?? `new-${index}`} className="flex flex-wrap items-center gap-2">
            <input
              value={stage.name}
              aria-label={t("pipelines.stage")}
              onChange={(event) =>
                set(stages.map((old, at) => (at === index ? { ...old, name: event.target.value } : old)))
              }
              className={`${FIELD} flex-1 text-sm`}
              dir="auto"
            />
            <select
              value={stage.category}
              aria-label={t("pipelines.category")}
              onChange={(event) =>
                set(
                  stages.map((old, at) =>
                    at === index ? { ...old, category: event.target.value as Stage["category"] } : old,
                  ),
                )
              }
              className={`${FIELD} text-sm`}
            >
              {CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {t(`category.${category}`)}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label={t("routing.moveUp")}
              disabled={index === 0}
              onClick={() => move(index, -1)}
              className="hover:bg-background min-h-11 min-w-11 rounded-md disabled:opacity-40"
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={t("routing.moveDown")}
              disabled={index === stages.length - 1}
              onClick={() => move(index, 1)}
              className="hover:bg-background min-h-11 min-w-11 rounded-md disabled:opacity-40"
            >
              ↓
            </button>
            <button
              type="button"
              aria-label={t("routing.remove")}
              onClick={() => set(stages.filter((_, at) => at !== index))}
              className="hover:bg-background min-h-11 min-w-11 rounded-md"
            >
              ×
            </button>
          </li>
        ))}
      </ol>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => set([...stages, { name: "", category: "open" }])}
          className="hover:bg-background min-h-11 rounded-md px-3 text-sm underline"
        >
          {t("pipelines.addStage")}
        </button>
        {dirty && (
          <div className="flex gap-2">
            <button type="button" onClick={() => setDraft(null)} className="min-h-11 px-3 text-sm">
              {t("settings.discard")}
            </button>
            <button
              type="button"
              disabled={replace.isPending || stages.some((stage) => !stage.name.trim())}
              onClick={() => replace.mutate(stages, { onSuccess: () => setDraft(null) })}
              className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-black disabled:opacity-50"
            >
              {t("common.save")}
            </button>
          </div>
        )}
      </div>
      {replace.isError && (
        <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
          {replace.error instanceof ApiError
            ? (replace.error.problem.detail ?? replace.error.problem.title)
            : t("settings.saveFailed")}
        </p>
      )}
    </section>
  );
}
