"use client";

import type { ContentDetail } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

type Publication = NonNullable<ContentDetail["publications"]>[number];

const STATE: Record<string, MessageKey> = {
  pending: "content.tryingAgain",
  publishing: "content.status.publishing",
  published: "content.status.published",
  failed: "content.status.failed",
};

/** Where a piece went, one account at a time (T4.3): the post where it went
 *  out, the platform's own words where it did not. */
export function Publications({ publications }: { publications: Publication[] }) {
  const t = useT();
  if (publications.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">{t("content.whereItWent")}</h2>
      <ul className="space-y-1 text-sm">
        {publications.map((p) => (
          <li
            key={`${p.platform}:${p.handle ?? ""}`}
            className="flex flex-wrap items-baseline gap-2"
          >
            <span className="font-medium capitalize">{p.platform}</span>
            {p.handle && <span className="text-muted">{p.handle}</span>}
            <span className={p.status === "failed" ? "text-danger" : "text-muted"}>
              {t(STATE[p.status] ?? "content.status.publishing")}
            </span>
            {p.permalink && (
              <a href={p.permalink} target="_blank" rel="noreferrer" className="underline">
                {t("content.openPost")}
              </a>
            )}
            {p.error && p.status !== "published" && (
              <span className="text-danger" dir="auto">
                {p.error}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
