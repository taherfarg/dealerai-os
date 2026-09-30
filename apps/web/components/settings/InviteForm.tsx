"use client";

import { useId, useState } from "react";
import { useInvite, useMe, useTeams, type Invitation } from "@/lib/api/hooks";
import { formatDateTime } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/i18n-client";
import { FIELD, problem, ROLES } from "./shared";

/** The API's order (core/permissions.ROLES). It refuses anything above the
 *  inviter anyway; this only stops the form offering what will be refused. */
const RANK = ["viewer", "sales", "marketer", "manager", "admin", "owner"];

/**
 * Inviting somebody by a link the manager sends on WhatsApp, where Pollux's
 * people already are — DealerAI sends no email. The link works once, for that
 * address, for seven days, and joins them to the teams ticked here.
 */
export function InviteForm() {
  const t = useT();
  const locale = useLocale();
  const me = useMe();
  const teams = useTeams();
  const invite = useInvite();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("sales");
  const [teamIds, setTeamIds] = useState<string[]>([]);
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [copied, setCopied] = useState(false);
  const ready = useId();

  const mine = RANK.indexOf(me.data?.role ?? "viewer");
  const offered = ROLES.filter((option) => RANK.indexOf(option) <= mine);
  const link = invitation && `${window.location.origin}/accept-invite?token=${invitation.token}`;
  const whatsapp =
    link && `https://wa.me/?text=${encodeURIComponent(`${t("invite.message")}\n${link}`)}`;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold">{t("invite.title")}</h2>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setCopied(false);
          invite.mutate(
            { email: email.trim(), role, team_ids: teamIds },
            { onSuccess: setInvitation },
          );
        }}
      >
        <div className="flex flex-wrap gap-2">
          <input
            type="email"
            required
            dir="ltr"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-label={t("invite.email")}
            placeholder={t("invite.email")}
            className={`${FIELD} min-w-0 flex-1 text-sm`}
          />
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as (typeof ROLES)[number])}
            aria-label={t("team.role")}
            className={`${FIELD} text-sm`}
          >
            {offered.map((option) => (
              <option key={option} value={option}>
                {t(`role.${option}` as MessageKey)}
              </option>
            ))}
          </select>
        </div>
        {(teams.data ?? []).length > 0 && (
          <fieldset className="flex flex-wrap items-center gap-x-4 text-sm">
            <legend className="text-muted text-xs">{t("invite.teams")}</legend>
            {(teams.data ?? []).map((team) => (
              <label key={team.id} className="flex min-h-11 items-center gap-2">
                <input
                  type="checkbox"
                  checked={teamIds.includes(team.id)}
                  onChange={(event) =>
                    setTeamIds((current) =>
                      event.target.checked
                        ? [...current, team.id]
                        : current.filter((id) => id !== team.id),
                    )
                  }
                />
                {team.name}
              </label>
            ))}
          </fieldset>
        )}
        <button
          type="submit"
          disabled={invite.isPending}
          className="bg-accent min-h-11 self-start rounded-md px-4 text-sm font-medium text-black disabled:opacity-50"
        >
          {t("invite.create")}
        </button>
      </form>

      {invite.isError && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem(invite.error, t("settings.saveFailed"))}
        </p>
      )}

      {invitation && link && whatsapp && (
        <div className="flex flex-col gap-2 text-sm">
          <p id={ready} className="text-muted text-xs">
            {t("invite.ready")}{" "}
            <span dir="ltr">
              {formatDateTime(invitation.expires_at, me.data?.tenant.timezone ?? "Asia/Dubai", locale)}
            </span>
          </p>
          <input
            readOnly
            dir="ltr"
            value={link}
            aria-labelledby={ready}
            onFocus={(event) => event.target.select()}
            className={`${FIELD} text-xs`}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(link).then(() => setCopied(true))}
              className="border-border min-h-11 rounded-md border px-3"
            >
              {copied ? t("invite.copied") : t("invite.copy")}
            </button>
            <a
              href={whatsapp}
              target="_blank"
              rel="noreferrer"
              className="border-border flex min-h-11 items-center rounded-md border px-3"
            >
              {t("invite.whatsapp")}
            </a>
          </div>
        </div>
      )}
    </section>
  );
}
