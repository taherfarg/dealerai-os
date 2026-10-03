"use client";

import Link from "next/link";
import { Fragment, useState } from "react";
import type { Conversation, RepRow } from "@/lib/api/hooks";
import { formatDuration } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import { tone } from "./StatTile";

const TONE_TEXT = {
  ok: "text-green-700 dark:text-green-400",
  warn: "text-amber-700 dark:text-amber-400",
  bad: "text-red-700 dark:text-red-400",
} as const;

function Median({ seconds, target }: { seconds: number | null; target: number }) {
  const locale = useLocale();
  const band = tone(seconds, target);
  return (
    // No dir here: the units are the reader's, and Arabic ones forced left to
    // right come out in the wrong order.
    <span className={`tabular-nums ${band ? TONE_TEXT[band] : "text-muted"}`}>
      {seconds == null ? "—" : formatDuration(seconds, locale)}
    </span>
  );
}

/** Who is waiting on one person, and where their overdue tasks are. */
function Opened({
  rep,
  waiting,
  tenant,
}: {
  rep: RepRow;
  waiting: Conversation[];
  tenant: string;
}) {
  const t = useT();
  const theirs = waiting.filter((conversation) => conversation.assignee?.id === rep.user.id);
  return (
    <div className="bg-background rounded-md p-2 text-sm">
      <h3 className="text-muted text-xs font-semibold">{t("teamTable.waitingOnThem")}</h3>
      {theirs.length === 0 ? (
        <p className="text-muted text-xs">{t("teamTable.nobodyWaiting")}</p>
      ) : (
        <ul>
          {theirs.map((conversation) => (
            <li key={conversation.id}>
              <Link
                href={`/${tenant}/inbox/${conversation.id}`}
                className="inline-flex min-h-11 items-center underline"
                dir="auto"
              >
                {conversation.contact.name ?? t("inbox.unknownCustomer")}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link
        href={`/${tenant}/tasks?bucket=overdue&assignee=${rep.user.id}`}
        className="inline-flex min-h-11 items-center underline"
      >
        {t("teamTable.theirTasks")} ({rep.overdue_tasks})
      </Link>
    </div>
  );
}

/**
 * One row per salesperson (08-screens § 11): a table from md up, a card per
 * person below it. Opening a person shows who is waiting on them — the
 * dashboard's own waiting list, filtered, so it costs no request — and links
 * to their overdue tasks.
 */
export function RepTable({
  team,
  waiting,
  target,
  tenant,
}: {
  team: RepRow[];
  waiting: Conversation[];
  target: number;
  tenant: string;
}) {
  const t = useT();
  const [opened, setOpened] = useState<string | null>(null);
  const toggle = (id: string) => setOpened((current) => (current === id ? null : id));

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("dashboard.team")}</h2>

      <table className="mt-2 hidden w-full text-sm md:table">
        <thead className="text-muted text-start text-xs">
          <tr>
            <th className="py-1 text-start font-normal">{t("teamTable.person")}</th>
            <th className="font-normal">{t("teamTable.open")}</th>
            <th className="font-normal">{t("teamTable.waiting")}</th>
            <th className="font-normal">{t("teamTable.median")}</th>
            <th className="font-normal">{t("teamTable.missed")}</th>
            <th className="font-normal">{t("teamTable.overdue")}</th>
            <th className="font-normal">{t("teamTable.leads")}</th>
            <th className="font-normal">{t("teamTable.won")}</th>
          </tr>
        </thead>
        <tbody>
          {team.map((rep) => (
            <Fragment key={rep.user.id}>
              <tr className="border-t border-black/5 text-center dark:border-white/10">
                <td className="py-1 text-start">
                  <button
                    type="button"
                    aria-expanded={opened === rep.user.id}
                    onClick={() => toggle(rep.user.id)}
                    className="min-h-11 text-start underline-offset-2 hover:underline"
                    dir="auto"
                  >
                    {rep.user.name}
                  </button>
                </td>
                <td className="tabular-nums">{rep.open}</td>
                <td className="tabular-nums">{rep.waiting}</td>
                <td>
                  <Median seconds={rep.median_first_response_seconds} target={target} />
                </td>
                <td className="tabular-nums">{rep.missed_targets}</td>
                <td className="tabular-nums">{rep.overdue_tasks}</td>
                <td className="tabular-nums" dir="ltr">
                  {rep.hot} · {rep.warm} · {rep.cold}
                </td>
                <td className="tabular-nums">{rep.won_this_month}</td>
              </tr>
              {opened === rep.user.id && (
                <tr>
                  <td colSpan={8}>
                    <Opened rep={rep} waiting={waiting} tenant={tenant} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>

      <ul className="mt-2 grid gap-2 md:hidden">
        {team.map((rep) => (
          <li key={rep.user.id} className="bg-surface border-border rounded-lg border p-3 text-sm">
            <button
              type="button"
              aria-expanded={opened === rep.user.id}
              onClick={() => toggle(rep.user.id)}
              className="min-h-11 w-full text-start font-medium"
              dir="auto"
            >
              {rep.user.name}
            </button>
            <dl className="text-muted grid grid-cols-2 gap-x-3 text-xs">
              <dt>{t("teamTable.waiting")}</dt>
              <dd className="tabular-nums">{rep.waiting}</dd>
              <dt>{t("teamTable.median")}</dt>
              <dd>
                <Median seconds={rep.median_first_response_seconds} target={target} />
              </dd>
              <dt>{t("teamTable.missed")}</dt>
              <dd className="tabular-nums">{rep.missed_targets}</dd>
              <dt>{t("teamTable.overdue")}</dt>
              <dd className="tabular-nums">{rep.overdue_tasks}</dd>
              <dt>{t("teamTable.won")}</dt>
              <dd className="tabular-nums">{rep.won_this_month}</dd>
            </dl>
            {opened === rep.user.id && (
              <div className="mt-2">
                <Opened rep={rep} waiting={waiting} tenant={tenant} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
