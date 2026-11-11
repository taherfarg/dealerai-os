"use client";

import type { LeadDetail } from "@/lib/api/hooks";
import { Auto, Ltr } from "@/components/Bidi";
import { useT } from "@/lib/i18n-client";
import { word } from "@/lib/words";

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
            className="flex items-center justify-between gap-2 py-1 text-sm"
          >
            <span className="flex items-center gap-1">
              {/* The API sends the signal and its English label: the label is
                  for a signal this build has no words for yet. */}
              <Auto>{word(t, "score", reason.signal, reason.label)}</Auto>
              {reason.evidence_message_id && (
                <button
                  type="button"
                  onClick={() => onEvidence?.(reason.evidence_message_id as string)}
                  aria-label={t("lead.evidence")}
                  className="text-muted inline-flex min-h-11 min-w-11 items-center justify-center text-xs underline"
                >
                  ↗
                </button>
              )}
            </span>
            <Ltr className={reason.points < 0 ? "text-danger" : "text-muted"}>
              {reason.points > 0 ? `+${reason.points}` : reason.points}
            </Ltr>
          </li>
        ))}
      </ul>
    </section>
  );
}
