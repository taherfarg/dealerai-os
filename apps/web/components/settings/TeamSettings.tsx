"use client";

import { useState } from "react";
import {
  useDeleteTeam,
  useEditMember,
  useMembers,
  useSaveTeam,
  useTeams,
  type Member,
  type Team,
} from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";
import { InviteForm } from "./InviteForm";
import { FIELD, problem, ROLES } from "./shared";

const LANGUAGES = ["ar", "en", "fr"] as const;

/** Its own component so a refusal — the last owner — shows on its own row. */
function MemberRow({ member, teams }: { member: Member; teams: Team[] }) {
  const t = useT();
  const edit = useEditMember();
  const patch = (body: Parameters<typeof edit.mutate>[0]["patch"]) =>
    edit.mutate({ userId: member.id, patch: body });
  const spoken = member.languages.filter((code): code is (typeof LANGUAGES)[number] =>
    (LANGUAGES as readonly string[]).includes(code),
  );

  return (
    <li className="bg-surface border-border rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium" dir="auto">
          {member.name ?? member.email}
        </span>
        <select
          aria-label={t("team.role")}
          value={member.role}
          onChange={(event) => patch({ role: event.target.value as Member["role"] })}
          className={FIELD}
        >
          {ROLES.map((role) => (
            <option key={role} value={role}>
              {t(`role.${role}` as MessageKey)}
            </option>
          ))}
        </select>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        <span className="text-muted">{t("team.teams")}</span>
        {teams.map((team) => (
          <label key={team.id} className="flex min-h-11 items-center gap-1">
            <input
              type="checkbox"
              checked={member.team_ids.includes(team.id)}
              onChange={(event) =>
                patch({
                  team_ids: event.target.checked
                    ? [...member.team_ids, team.id]
                    : member.team_ids.filter((id) => id !== team.id),
                })
              }
            />
            <span dir="auto">{team.name}</span>
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-muted">{t("team.languages")}</span>
        {LANGUAGES.map((code) => (
          <label key={code} className="flex min-h-11 items-center gap-1">
            <input
              type="checkbox"
              checked={spoken.includes(code)}
              onChange={(event) =>
                patch({
                  languages: event.target.checked
                    ? [...spoken, code]
                    : spoken.filter((language) => language !== code),
                })
              }
            />
            {t(`language.${code}`)}
          </label>
        ))}
        <label className="flex min-h-11 items-center gap-1">
          <input
            type="checkbox"
            checked={member.accepting_chats}
            onChange={(event) => patch({ accepting_chats: event.target.checked })}
          />
          {t("team.takingChats")}
        </label>
      </div>
      {edit.isError && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem(edit.error, t("settings.saveFailed"))}
        </p>
      )}
    </li>
  );
}

function TeamRow({ team }: { team: Team }) {
  const t = useT();
  const save = useSaveTeam();
  const remove = useDeleteTeam();
  const failed = save.error ?? remove.error;
  return (
    <li className="flex flex-wrap items-center gap-2 py-1 text-sm">
      {/* Renamed on blur, re-mounted when the saved name changes. */}
      <input
        key={team.name}
        defaultValue={team.name}
        aria-label={t("team.teamName")}
        onBlur={(event) => {
          const name = event.target.value.trim();
          if (name && name !== team.name) save.mutate({ id: team.id, name });
        }}
        className={`${FIELD} flex-1`}
        dir="auto"
      />
      <span className="text-muted text-xs">
        {team.member_ids.length} {t("team.people")}
      </span>
      <button
        type="button"
        onClick={() => remove.mutate(team.id)}
        disabled={remove.isPending}
        className="hover:bg-background min-h-11 rounded-md px-3 text-sm text-red-700 dark:text-red-400"
      >
        {t("team.deleteTeam")}
      </button>
      {failed && (
        <p role="alert" className="w-full text-xs text-red-600 dark:text-red-400">
          {problem(failed, t("settings.saveFailed"))}
        </p>
      )}
    </li>
  );
}

/**
 * Team and roles (08-screens § 13): who is here, what they may do, who they
 * work with — and, in words, what each role lets somebody see. Somebody new
 * arrives by an invitation link from here (08-screens § 14).
 */
export function TeamSettings() {
  const t = useT();
  const members = useMembers();
  const teams = useTeams();
  const create = useSaveTeam();
  const [name, setName] = useState("");
  const teamList = teams.data ?? [];

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold">{t("settings.team")}</h1>

      <InviteForm />

      <section>
        <h2 className="text-sm font-semibold">{t("team.members")}</h2>
        <ul className="mt-2 flex flex-col gap-2">
          {(members.data ?? []).map((member) => (
            <MemberRow key={member.id} member={member} teams={teamList} />
          ))}
        </ul>
      </section>

      <section>
        <h2 className="text-sm font-semibold">{t("team.teamsTitle")}</h2>
        <ul className="mt-1">
          {teamList.map((team) => (
            <TeamRow key={team.id} team={team} />
          ))}
        </ul>
        <form
          className="mt-2 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) create.mutate({ name: name.trim() }, { onSuccess: () => setName("") });
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("team.newTeam")}
            aria-label={t("team.newTeam")}
            className={`${FIELD} flex-1 text-sm`}
          />
          <button type="submit" className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-black">
            {t("team.add")}
          </button>
        </form>
        {create.isError && (
          <p role="alert" className="text-xs text-red-600 dark:text-red-400">
            {problem(create.error, t("settings.saveFailed"))}
          </p>
        )}
      </section>

      <section className="text-sm">
        <h2 className="font-semibold">{t("team.whoSeesWhat")}</h2>
        <ul className="text-muted mt-1 list-inside list-disc">
          <li>{t("team.sees.owner")}</li>
          <li>{t("team.sees.manager")}</li>
          <li>{t("team.sees.sales")}</li>
          <li>{t("team.sees.viewer")}</li>
        </ul>
      </section>
    </div>
  );
}
