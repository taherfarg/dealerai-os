"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import {
  useSalesSettings,
  useSaveSalesSettings,
  useTeams,
  type SalesSettings,
  type SalesSettingsPatch,
} from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";
import { changes } from "./changes";
import { badDays, HoursEditor } from "./HoursEditor";
import { RuleEditor } from "./RuleEditor";

/** The keys this screen writes — all of them settings.routing's (06 § 12). */
const KEYS = [
  "first_response_target_min",
  "unassigned_visible_to_sales",
  "default_team_id",
  "business_hours",
  "routing_rules",
] as const;
type Routing = Pick<SalesSettings, (typeof KEYS)[number]>;

function routingOf(settings: SalesSettings): Routing {
  return Object.fromEntries(KEYS.map((key) => [key, settings[key]])) as Routing;
}

function moved<T>(list: T[], index: number, step: -1 | 1): T[] {
  const copy = [...list];
  [copy[index], copy[index + step]] = [copy[index + step], copy[index]];
  return copy;
}

/**
 * Where a new conversation goes, and how fast it must be answered
 * (08-screens § 13). Edits stay local until Save, which sticks to the bottom
 * of the screen — above the phone's navigation — while anything is unsaved.
 */
export function RoutingForm() {
  const t = useT();
  const settings = useSalesSettings();
  const teams = useTeams();
  const save = useSaveSalesSettings();
  const [draft, setDraft] = useState<Routing | null>(null);

  if (!settings.data) return <p className="text-muted text-sm">…</p>;

  const saved = routingOf(settings.data);
  const current = draft ?? saved;
  const patch = changes(saved, current) as SalesSettingsPatch;
  const dirty = Object.keys(patch).length > 0;
  const hours = current.business_hours ?? {};
  const rules = current.routing_rules ?? [];
  const teamList = teams.data ?? [];
  const edit = (next: Partial<Routing>) => setDraft({ ...current, ...next });
  const field = "min-h-11 rounded-md border border-black/10 px-2 dark:border-white/15";

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold">{t("settings.routing")}</h1>

      <section className="flex flex-col gap-2 text-sm">
        <label className="flex flex-wrap items-center gap-2">
          {t("routing.target")}
          <input
            type="number"
            min={1}
            max={1440}
            value={current.first_response_target_min ?? 5}
            onChange={(event) => edit({ first_response_target_min: Number(event.target.value) })}
            className={`${field} w-24`}
            dir="ltr"
          />
          {t("routing.minutes")}
        </label>
        <p className="text-muted text-xs">{t("routing.targetHint")}</p>
        <label className="flex min-h-11 items-center gap-2">
          <input
            type="checkbox"
            checked={current.unassigned_visible_to_sales ?? true}
            onChange={(event) => edit({ unassigned_visible_to_sales: event.target.checked })}
          />
          {t("routing.pool")}
        </label>
        <label className="flex flex-wrap items-center gap-2">
          {t("routing.defaultTeam")}
          <select
            value={current.default_team_id ?? ""}
            onChange={(event) => edit({ default_team_id: event.target.value || null })}
            className={field}
          >
            <option value="">{t("routing.noTeam")}</option>
            {teamList.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <HoursEditor value={hours} onChange={(next) => edit({ business_hours: next })} />

      <section>
        <h2 className="text-sm font-semibold">{t("routing.rules")}</h2>
        <p className="text-muted text-xs">{t("routing.rulesHint")}</p>
        <ol className="mt-2 flex flex-col gap-2">
          {rules.map((rule, index) => (
            <RuleEditor
              key={index}
              rule={rule}
              teams={teamList}
              first={index === 0}
              last={index === rules.length - 1}
              onChange={(next) =>
                edit({ routing_rules: rules.map((old, at) => (at === index ? next : old)) })
              }
              onMove={(step) => edit({ routing_rules: moved(rules, index, step) })}
              onRemove={() => edit({ routing_rules: rules.filter((_, at) => at !== index) })}
            />
          ))}
        </ol>
        <button
          type="button"
          disabled={teamList.length === 0}
          onClick={() =>
            edit({
              routing_rules: [
                ...rules,
                { languages: [], countries: [], from_ad: null, team_id: teamList[0].id },
              ],
            })
          }
          className="hover:bg-background mt-2 min-h-11 rounded-md px-3 text-sm underline disabled:opacity-40"
        >
          {t("routing.addRule")}
        </button>
      </section>

      {(dirty || save.isError) && (
        <div className="bg-surface border-border sticky bottom-16 flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 shadow-lg md:bottom-0">
          <span role={save.isError ? "alert" : undefined} className="text-sm">
            {save.isError
              ? save.error instanceof ApiError
                ? (save.error.problem.detail ?? save.error.problem.title)
                : t("settings.saveFailed")
              : t("settings.unsaved")}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                setDraft(null);
                save.reset();
              }}
              className="min-h-11 px-3 text-sm"
            >
              {t("settings.discard")}
            </button>
            <button
              type="button"
              disabled={!dirty || badDays(hours).length > 0 || save.isPending}
              onClick={() => save.mutate(patch, { onSuccess: () => setDraft(null) })}
              className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-black disabled:opacity-50"
            >
              {t("common.save")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
