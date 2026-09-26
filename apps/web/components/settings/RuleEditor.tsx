"use client";

import type { RoutingRule, Team } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";
import { describeRule } from "./describeRule";

const LANGUAGES = ["ar", "en", "fr"] as const;

/** Two-letter codes out of whatever was typed: "dz, ma" and "DZ MA" are both
 *  Algeria and Morocco. */
export function countriesFrom(text: string): string[] {
  return [...new Set(text.toUpperCase().split(/[^A-Z]+/).filter((code) => code.length === 2))];
}

/** One routing rule, with the sentence it amounts to under it. */
export function RuleEditor({
  rule,
  teams,
  first,
  last,
  onChange,
  onMove,
  onRemove,
}: {
  rule: RoutingRule;
  teams: Team[];
  first: boolean;
  last: boolean;
  onChange: (next: RoutingRule) => void;
  onMove: (step: -1 | 1) => void;
  onRemove: () => void;
}) {
  const t = useT();
  const languages = rule.languages ?? [];
  const countries = (rule.countries ?? []).join(", ");
  const field = "min-h-11 rounded-md border border-black/10 px-2 dark:border-white/15";

  return (
    <li className="bg-surface border-border rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-muted">{t("routing.languages")}</span>
        {LANGUAGES.map((code) => (
          <label key={code} className="flex min-h-11 items-center gap-1">
            <input
              type="checkbox"
              checked={languages.includes(code)}
              onChange={(event) =>
                onChange({
                  ...rule,
                  languages: event.target.checked
                    ? [...languages, code]
                    : languages.filter((language) => language !== code),
                })
              }
            />
            {t(`language.${code}`)}
          </label>
        ))}
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2">
          <span className="text-muted">{t("routing.countries")}</span>
          {/* Committed on blur and re-mounted when the saved value changes:
              parsing on every keystroke would eat the comma being typed. */}
          <input
            key={countries}
            defaultValue={countries}
            placeholder="DZ, MA"
            dir="ltr"
            onBlur={(event) => onChange({ ...rule, countries: countriesFrom(event.target.value) })}
            className={`${field} w-32`}
          />
        </label>
        <label className="flex items-center gap-2">
          <span className="text-muted">{t("routing.fromAd")}</span>
          <select
            value={rule.from_ad == null ? "" : String(rule.from_ad)}
            onChange={(event) =>
              onChange({
                ...rule,
                from_ad: event.target.value === "" ? null : event.target.value === "true",
              })
            }
            className={field}
          >
            <option value="">{t("routing.either")}</option>
            <option value="true">{t("routing.yes")}</option>
            <option value="false">{t("routing.no")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-muted">{t("routing.team")}</span>
          <select
            value={rule.team_id}
            onChange={(event) => onChange({ ...rule, team_id: event.target.value })}
            className={field}
          >
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted text-xs" dir="auto">
          {describeRule(rule, teams, t)}
        </p>
        <div className="flex gap-1">
          <button
            type="button"
            aria-label={t("routing.moveUp")}
            disabled={first}
            onClick={() => onMove(-1)}
            className="hover:bg-background min-h-11 min-w-11 rounded-md disabled:opacity-40"
          >
            ↑
          </button>
          <button
            type="button"
            aria-label={t("routing.moveDown")}
            disabled={last}
            onClick={() => onMove(1)}
            className="hover:bg-background min-h-11 min-w-11 rounded-md disabled:opacity-40"
          >
            ↓
          </button>
          <button
            type="button"
            aria-label={t("routing.remove")}
            onClick={onRemove}
            className="hover:bg-background min-h-11 min-w-11 rounded-md"
          >
            ×
          </button>
        </div>
      </div>
    </li>
  );
}
