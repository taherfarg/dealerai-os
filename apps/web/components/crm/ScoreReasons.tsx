"use client";

import type { LeadDetail } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * What the score is made of.
 *
 * The points shown are the points counted — the API recomputes them from the
 * stored signals rather than keeping a second copy — and they add up on screen,
 * because a score a salesperson cannot check is a score they ignore.
 */
export function ScoreReasons({
  reasons,
  onEvidence,
}: {
  reasons: LeadDetail["score_reasons"];
  onEvidence?: (messageId: string) => void;
}) {
  const t = useT();
  if (reasons.length === 0) return null;
  return (
    <section>
      <h3 className="text-muted text-xs font-semibold uppercase tracking-wide">{t("lead.why")}</h3>
      <ul className="mt-1">
        {reasons.map((reason, index) => (
          <li
            key={`${reason.signal}-${index}`}
            className="flex items-baseline justify-between gap-2 py-1 text-sm"
          >
            <span>
              {reason.label}
              {reason.evidence_message_id && (
                <button
                  type="button"
                  onClick={() => onEvidence?.(reason.evidence_message_id as string)}
                  aria-label={t("lead.evidence")}
                  className="text-muted ms-1 text-xs underline"
                >
                  ↗
                </button>
              )}
            </span>
            <span className={reason.points < 0 ? "text-red-600 dark:text-red-400" : "text-muted"}>
              {reason.points > 0 ? `+${reason.points}` : reason.points}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
