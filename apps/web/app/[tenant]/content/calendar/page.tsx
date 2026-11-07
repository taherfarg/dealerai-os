"use client";

import Link from "next/link";
import { use } from "react";
import { Calendar } from "@/components/content/Calendar";
import { mayReview } from "@/components/content/ContentGrid";
import { span, step, today } from "@/components/content/calendarDates";
import { useContentCalendar, useMe } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { useT } from "@/lib/i18n-client";

/** When content goes out (T3.8): a week or a month, the daily limit, the gaps. */
export default function ContentCalendarPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const [filters, setFilters] = useFilters({ view: "week", day: "" });
  const view = filters.view === "month" ? "month" : "week";
  const day = filters.day || today();
  const [from, to] = span(view, day);
  const calendar = useContentCalendar(from, to);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link
            href={`/${tenant}/content`}
            className="text-muted text-sm underline-offset-2 hover:underline"
          >
            {t("nav.content")}
          </Link>
          <h1 className="text-lg font-semibold">{t("calendar.title")}</h1>
        </div>
        <nav className="flex flex-wrap items-center gap-2" aria-label={t("calendar.title")}>
          <button type="button" className="btn" onClick={() => setFilters({ day: step(view, day, -1) })}>
            {t("calendar.back")}
          </button>
          <button type="button" className="btn" onClick={() => setFilters({ day: "" })}>
            {t("calendar.today")}
          </button>
          <button type="button" className="btn" onClick={() => setFilters({ day: step(view, day, 1) })}>
            {t("calendar.on")}
          </button>
          {(["week", "month"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              className={`btn ${view === v ? "btn-primary" : ""}`}
              onClick={() => setFilters({ view: v })}
            >
              {t(v === "week" ? "calendar.week" : "calendar.month")}
            </button>
          ))}
        </nav>
      </header>
      {calendar.data && (
        <p className="text-muted text-xs">
          {calendar.data.max_posts_per_day != null
            ? `${t("calendar.limit")} ${calendar.data.max_posts_per_day}`
            : t("calendar.noLimit")}
          {calendar.data.quiet_hours &&
            ` · ${t("calendar.quiet")} ${calendar.data.quiet_hours.join("–")}`}
          {` · ${calendar.data.timezone}`}
        </p>
      )}
      {calendar.isError ? (
        <p role="alert" className="text-danger text-sm">
          {calendar.error.message}
        </p>
      ) : calendar.data ? (
        <Calendar
          calendar={calendar.data}
          tenant={tenant}
          canSchedule={mayReview(me.data?.role)}
          compact={view === "month"}
        />
      ) : (
        <p className="text-muted text-sm">…</p>
      )}
    </div>
  );
}
