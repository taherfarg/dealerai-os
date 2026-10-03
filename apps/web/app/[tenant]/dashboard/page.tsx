"use client";

import Link from "next/link";
import { use } from "react";
import { BriefCard } from "@/components/manager/BriefCard";
import { RepTable } from "@/components/manager/RepTable";
import { StatTile, tone } from "@/components/manager/StatTile";
import { WaitingList } from "@/components/manager/WaitingList";
import { useManagerDashboard, useMe, type ManagerDashboard } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { formatDuration } from "@/lib/format";
import { Auto } from "@/components/Bidi";
import { useLocale, useT } from "@/lib/i18n-client";
import { word } from "@/lib/words";

type Share = ManagerDashboard["phone_share"]["this_week"];

function inboxShare(share: Share): string {
  const replies = share.inbox + share.phone;
  return replies ? `${Math.round((100 * share.inbox) / replies)}%` : "—";
}

/**
 * The manager's morning (08-screens § 11): the brief, the tiles, who is
 * waiting, the team, the pipeline, where leads came from and how much of the
 * talking happens in the inbox. One request, refreshed live.
 */
export default function DashboardPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const locale = useLocale();
  const me = useMe();
  const [filters, setFilters] = useFilters({ date: "" });
  const permissions = me.data?.permissions ?? [];
  const allowed = permissions.includes("dashboard.manager");
  const board = useManagerDashboard(filters.date || null, allowed);

  if (me.data && !allowed) {
    return (
      <div className="mx-auto max-w-md p-6 text-sm">
        <h1 className="text-lg font-semibold">{t("nav.dashboard")}</h1>
        <p className="mt-2">{t("dashboard.forManagers")}</p>
        <Link href={`/${tenant}/today`} className="mt-2 inline-block underline">
          {t("dashboard.openMyDay")}
        </Link>
      </div>
    );
  }
  if (board.isError) {
    return (
      <p role="alert" className="p-6 text-sm text-red-600 dark:text-red-400">
        {board.error.message}
      </p>
    );
  }
  if (!board.data) return <p className="text-muted p-6 text-sm">…</p>;

  const { tiles, brief, waiting, team, pipeline, sources, phone_share: share } = board.data;
  const target = tiles.first_response_target_seconds;
  const median = tiles.median_first_response_seconds;
  const inbox = `/${tenant}/inbox?view=${me.data?.scope === "all" ? "all" : "team"}`;
  const boards = [...new Set(pipeline.map((stage) => stage.pipeline_id))].map((id) =>
    pipeline.filter((stage) => stage.pipeline_id === id),
  );

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">{t("nav.dashboard")}</h1>
        <label className="text-muted flex items-center gap-2 text-sm">
          {t("dashboard.day")}
          <input
            type="date"
            value={filters.date || board.data.date}
            onChange={(event) => setFilters({ date: event.target.value })}
            className="min-h-11 rounded-md border border-black/10 px-2 text-sm dark:border-white/15"
          />
        </label>
      </header>

      <BriefCard brief={brief} tenant={tenant} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label={t("tile.newConversations")}
          value={String(tiles.new_conversations)}
          href={inbox}
        />
        <StatTile label={t("tile.waitingNow")} value={String(tiles.waiting_now)} href={inbox} />
        <StatTile
          label={t("tile.median")}
          value={median == null ? "—" : formatDuration(median, locale)}
          hint={`${t("tile.target")} ${formatDuration(target, locale)}`}
          tone={tone(median, target)}
        />
        <StatTile label={t("tile.missed")} value={String(tiles.missed_targets)} />
        <StatTile
          label={t("tile.newLeads")}
          value={String(tiles.new_leads)}
          href={`/${tenant}/pipeline`}
        />
        <StatTile
          label={t("tile.hotLeads")}
          value={String(tiles.hot_leads)}
          href={`/${tenant}/customers?band=hot`}
        />
        <StatTile label={t("tile.won")} value={String(tiles.won)} href={`/${tenant}/pipeline`} />
        <StatTile label={t("tile.lost")} value={String(tiles.lost)} href={`/${tenant}/pipeline`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <WaitingList
          conversations={waiting}
          tenant={tenant}
          canAssign={permissions.includes("inbox.assign")}
        />
        <RepTable team={team} waiting={waiting} target={target} tenant={tenant} />
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <section>
          <h2 className="text-sm font-semibold">{t("dashboard.pipeline")}</h2>
          {boards.map((stages) => (
            <div key={stages[0].pipeline_id} className="mt-2">
              <h3 className="text-muted text-xs">
                <Auto>{stages[0].pipeline_name}</Auto>
              </h3>
              <ul className="text-sm">
                {stages.map((stage) => (
                  <li key={stage.stage_id} className="flex justify-between gap-2 py-0.5">
                    <span dir="auto">{stage.stage_name}</span>
                    <span className="tabular-nums">{stage.leads}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>

        <section>
          <h2 className="text-sm font-semibold">{t("dashboard.sources")}</h2>
          <ul className="mt-2 text-sm">
            {sources.map((source) => (
              <li key={source.source} className="flex justify-between gap-2 py-0.5">
                <span>{word(t, "source", source.source)}</span>
                <span className="tabular-nums">{source.leads}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2 className="text-sm font-semibold">{t("dashboard.share")}</h2>
          <dl className="mt-2 grid grid-cols-2 gap-1 text-sm">
            <dt className="text-muted">{t("dashboard.thisWeek")}</dt>
            <dd className="tabular-nums" dir="ltr">
              {inboxShare(share.this_week)}
            </dd>
            <dt className="text-muted">{t("dashboard.lastWeek")}</dt>
            <dd className="tabular-nums" dir="ltr">
              {inboxShare(share.last_week)}
            </dd>
          </dl>
          <p className="text-muted mt-2 text-xs">{t("dashboard.phoneLine")}</p>
        </section>
      </div>
    </div>
  );
}
