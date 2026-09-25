import type { RoutingRule, Team } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";

/**
 * "Arabic or French · from DZ, MA · from an ad → Export". Every part is
 * optional; a rule with none of them matches everybody. A team that no longer
 * exists shows as "?" rather than an id nobody can read.
 */
export function describeRule(
  rule: RoutingRule,
  teams: Team[],
  t: (key: MessageKey) => string,
): string {
  const parts: string[] = [];
  if (rule.languages?.length) {
    parts.push(
      rule.languages.map((code) => t(`language.${code}` as MessageKey)).join(t("routing.or")),
    );
  }
  if (rule.countries?.length) parts.push(`${t("routing.from")} ${rule.countries.join(", ")}`);
  if (rule.from_ad === true) parts.push(t("routing.adOnly"));
  if (rule.from_ad === false) parts.push(t("routing.notAd"));
  const team = teams.find((candidate) => candidate.id === rule.team_id)?.name ?? "?";
  return `${parts.length ? parts.join(" · ") : t("routing.everyone")} → ${team}`;
}
