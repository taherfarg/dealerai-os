"use client";

import Link from "next/link";
import { useState, type DragEvent, type FormEvent } from "react";
import type { CalendarItem, ContentCalendar, ContentItem } from "@/lib/api/hooks";
import { useSchedule } from "@/lib/api/hooks";
import { useLocale, useT } from "@/lib/i18n-client";
import { concept } from "./ContentGrid";

type Piece = ContentItem & { local_time?: string };

/** How a day reads: "2/4" against the limit, or just the count without one. */
export function dayLoad(count: number, limit: number | null): string {
  return limit == null ? String(count) : `${count}/${limit}`;
}

/** The day's name and number in the reader's language, the date being plain. */
function dayName(day: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-AE" : "en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

/**
 * The days a view shows, each with what goes out, against the daily limit
 * (T3.8). A piece is dragged onto a day, keeping its time — or, on a phone
 * where HTML5 drag and drop does not exist, moved with its own date and time
 * fields. A refusal says the rule it broke.
 * ponytail: HTML5 drag and drop has no touch support, which is why every card
 * also carries the fields.
 */
export function Calendar({
  calendar,
  tenant,
  canSchedule,
  compact,
}: {
  calendar: ContentCalendar;
  tenant: string;
  canSchedule: boolean;
  compact: boolean;
}) {
  const t = useT();
  const locale = useLocale();
  const move = useSchedule();
  const gaps = new Set(calendar.gaps);
  const byDay = new Map<string, CalendarItem[]>();
  for (const item of calendar.items) {
    byDay.set(item.local_date, [...(byDay.get(item.local_date) ?? []), item]);
  }

  const drop = (day: string) => (event: DragEvent) => {
    event.preventDefault();
    const [id, at] = event.dataTransfer.getData("text/plain").split("|");
    if (id) move.mutate({ id, day, at: at || undefined });
  };

  return (
    <div className="space-y-4">
      {move.error && (
        <p role="alert" className="bg-danger-soft text-danger rounded-md p-2 text-sm">
          {move.error.message}
        </p>
      )}

      {canSchedule && calendar.unscheduled.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold">{t("calendar.waiting")}</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {calendar.unscheduled.map((piece) => (
              <li key={piece.id}>
                <Card piece={piece} tenant={tenant} canSchedule />
              </li>
            ))}
          </ul>
        </section>
      )}

      <ol
        className={`grid gap-2 ${compact ? "grid-cols-7" : "grid-cols-1 md:grid-cols-7"}`}
        aria-label={t("calendar.days")}
      >
        {calendar.days.map((day) => {
          const items = byDay.get(day.date) ?? [];
          const gap = gaps.has(day.date);
          return (
            <li
              key={day.date}
              onDragOver={canSchedule ? (event) => event.preventDefault() : undefined}
              onDrop={canSchedule ? drop(day.date) : undefined}
              className={`min-h-24 rounded-xl border p-2 ${
                gap ? "border-dashed" : "border-border"
              } ${day.full ? "bg-surface" : ""}`}
            >
              <div className="flex items-baseline justify-between gap-1 text-xs">
                <span className="font-medium">{dayName(day.date, locale)}</span>
                <span className={day.full ? "text-warning" : "text-muted"}>
                  {dayLoad(day.count, calendar.max_posts_per_day)}
                </span>
              </div>
              {gap && !compact && <p className="text-muted mt-1 text-xs">{t("calendar.gap")}</p>}
              <ul className="mt-1 space-y-1">
                {items.map((item) =>
                  compact ? (
                    <li key={item.id} className="truncate text-[11px]">
                      {item.local_time} {concept(item)}
                    </li>
                  ) : (
                    <li key={item.id}>
                      <Card
                        piece={item}
                        tenant={tenant}
                        canSchedule={canSchedule && item.status === "scheduled"}
                      />
                    </li>
                  ),
                )}
              </ul>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Card({
  piece,
  tenant,
  canSchedule,
}: {
  piece: Piece;
  tenant: string;
  canSchedule: boolean;
}) {
  const t = useT();
  const move = useSchedule();
  const [open, setOpen] = useState(false);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    move.mutate(
      { id: piece.id, day: String(form.get("day")), at: String(form.get("at") || "10:00") },
      { onSuccess: () => setOpen(false) },
    );
  };

  return (
    <div
      draggable={canSchedule}
      onDragStart={(event) =>
        event.dataTransfer.setData("text/plain", `${piece.id}|${piece.local_time ?? ""}`)
      }
      data-piece={piece.id}
      className={`bg-surface rounded-lg p-1.5 text-xs ${canSchedule ? "cursor-grab" : ""}`}
    >
      <Link href={`/${tenant}/content/${piece.id}`} className="block hover:underline">
        {piece.local_time && <span className="font-mono">{piece.local_time} </span>}
        <span className="capitalize">{concept(piece)}</span>
      </Link>
      {piece.vehicle && <p className="text-muted truncate">{piece.vehicle}</p>}
      {canSchedule && (
        <>
          <button
            type="button"
            className="text-muted mt-0.5 underline-offset-2 hover:underline"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {t("calendar.move")}
          </button>
          {open && (
            <form onSubmit={submit} className="mt-1 flex flex-wrap items-end gap-1">
              <input name="day" type="date" required aria-label={t("calendar.day")} className="field" />
              <input
                name="at"
                type="time"
                defaultValue={piece.local_time ?? "10:00"}
                aria-label={t("calendar.time")}
                className="field"
              />
              <button type="submit" className="btn" disabled={move.isPending}>
                {t("calendar.put")}
              </button>
              {piece.status === "scheduled" && (
                <button
                  type="button"
                  className="btn"
                  disabled={move.isPending}
                  onClick={() => move.mutate({ id: piece.id, day: null })}
                >
                  {t("calendar.off")}
                </button>
              )}
            </form>
          )}
          {move.error && (
            <p role="alert" className="text-danger mt-1">
              {move.error.message}
            </p>
          )}
        </>
      )}
    </div>
  );
}
