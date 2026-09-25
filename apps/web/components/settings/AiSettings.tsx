"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import {
  useAcceptance,
  useSalesSettings,
  useSaveSalesSettings,
  type Acceptance,
  type SalesSettings,
  type SalesSettingsPatch,
} from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";
import { changes } from "./changes";

/** The keys this screen writes — all of them settings.ai's (06 § 12). */
type Ai = Pick<SalesSettings, "drafts_enabled" | "arabic_register" | "follow_up_cadence_days">;

const NEVER = ["send", "price", "promise", "reserved", "optOut"] as const;
const FIELD = "min-h-11 rounded-md border border-black/10 px-2 dark:border-white/15";

function percent(rate: number | null): string {
  return rate == null ? "—" : `${Math.round(rate * 100)}%`;
}

function AcceptanceTable({ acceptance }: { acceptance: Acceptance }) {
  const t = useT();
  const rows = [acceptance.overall, ...acceptance.by_intent];
  if (acceptance.overall.decided === 0) {
    return <p className="text-muted text-sm">{t("ai.noDrafts")}</p>;
  }
  return (
    <table className="w-full text-sm">
      <thead className="text-muted text-xs">
        <tr>
          <th className="py-1 text-start font-normal">{t("ai.intent")}</th>
          <th className="font-normal">{t("ai.decided")}</th>
          <th className="font-normal">{t("ai.accepted")}</th>
          <th className="font-normal">{t("ai.sent")}</th>
          <th className="font-normal">{t("ai.lightlyEdited")}</th>
          <th className="font-normal">{t("ai.rewritten")}</th>
          <th className="font-normal">{t("ai.discarded")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr
            key={row.intent ?? `all-${index}`}
            className={`border-t border-black/5 text-center dark:border-white/10 ${
              index === 0 ? "font-semibold" : ""
            }`}
          >
            <td className="py-1 text-start">
              {index === 0
                ? t("ai.allDrafts")
                : row.intent
                  ? t(`draft.intent.${row.intent}` as MessageKey)
                  : "—"}
            </td>
            <td className="tabular-nums">{row.decided}</td>
            <td className="tabular-nums" dir="ltr">
              {percent(row.rate)}
            </td>
            <td className="tabular-nums">{row.sent}</td>
            <td className="tabular-nums">{row.lightly_edited}</td>
            <td className="tabular-nums">{row.rewritten}</td>
            <td className="tabular-nums">{row.discarded}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * The AI assistant (08-screens § 13): whether it drafts at all, how it writes
 * Arabic, when it follows up — what it never does, in plain words — and how
 * its drafts fared last month, which is the pilot's S5 number.
 */
export function AiSettings() {
  const t = useT();
  const settings = useSalesSettings();
  const save = useSaveSalesSettings();
  const acceptance = useAcceptance(30);
  const [draft, setDraft] = useState<Ai | null>(null);

  if (!settings.data) return <p className="text-muted text-sm">…</p>;

  const saved: Ai = {
    drafts_enabled: settings.data.drafts_enabled,
    arabic_register: settings.data.arabic_register,
    follow_up_cadence_days: settings.data.follow_up_cadence_days,
  };
  const current = draft ?? saved;
  const patch = changes(saved, current) as SalesSettingsPatch;
  const dirty = Object.keys(patch).length > 0;
  const cadence = current.follow_up_cadence_days ?? [];
  const edit = (next: Partial<Ai>) => setDraft({ ...current, ...next });

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold">{t("settings.ai")}</h1>

      <section className="flex flex-col gap-2 text-sm">
        <label className="flex min-h-11 items-center gap-2">
          <input
            type="checkbox"
            checked={current.drafts_enabled ?? true}
            onChange={(event) => edit({ drafts_enabled: event.target.checked })}
          />
          {t("ai.drafts")}
        </label>

        <fieldset>
          <legend className="font-semibold">{t("ai.register")}</legend>
          {(["mirror", "gulf"] as const).map((register) => (
            <label key={register} className="flex min-h-11 items-center gap-2">
              <input
                type="radio"
                name="register"
                checked={(current.arabic_register ?? "mirror") === register}
                onChange={() => edit({ arabic_register: register })}
              />
              {t(`ai.register.${register}`)}
            </label>
          ))}
        </fieldset>

        <fieldset>
          <legend className="font-semibold">{t("ai.cadence")}</legend>
          <p className="text-muted text-xs">{t("ai.cadenceHint")}</p>
          <ol className="mt-1 flex flex-wrap items-center gap-2">
            {cadence.map((days, index) => (
              <li key={index} className="flex items-center gap-1">
                <input
                  type="number"
                  min={1}
                  max={90}
                  value={days}
                  aria-label={`${t("ai.followUp")} ${index + 1}`}
                  onChange={(event) =>
                    edit({
                      follow_up_cadence_days: cadence.map((old, at) =>
                        at === index ? Number(event.target.value) : old,
                      ),
                    })
                  }
                  className={`${FIELD} w-20`}
                  dir="ltr"
                />
                <span className="text-muted">{t("ai.days")}</span>
                <button
                  type="button"
                  aria-label={t("routing.remove")}
                  onClick={() =>
                    edit({ follow_up_cadence_days: cadence.filter((_, at) => at !== index) })
                  }
                  className="hover:bg-background min-h-11 min-w-11 rounded-md"
                >
                  ×
                </button>
              </li>
            ))}
          </ol>
          {cadence.length < 5 && (
            <button
              type="button"
              onClick={() => edit({ follow_up_cadence_days: [...cadence, 14] })}
              className="hover:bg-background min-h-11 rounded-md px-3 underline"
            >
              {t("ai.addFollowUp")}
            </button>
          )}
        </fieldset>
      </section>

      <section className="text-sm">
        <h2 className="font-semibold">{t("ai.never")}</h2>
        <ul className="text-muted mt-1 list-inside list-disc">
          {NEVER.map((rule) => (
            <li key={rule}>{t(`ai.never.${rule}`)}</li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="text-sm font-semibold">{t("ai.acceptance")}</h2>
        {acceptance.data && <AcceptanceTable acceptance={acceptance.data} />}
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
              disabled={!dirty || save.isPending || cadence.some((days) => !(days >= 1))}
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
