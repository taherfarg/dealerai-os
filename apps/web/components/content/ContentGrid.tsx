"use client";

import Link from "next/link";
import type { ContentItem } from "@/lib/api/hooks";
import { formatRelative } from "@/lib/format";
import { mediaSrc } from "@/lib/media";
import type { MessageKey } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/i18n-client";

export const STATUS: Record<string, MessageKey> = {
  draft: "content.status.draft",
  rendering: "content.status.rendering",
  pending_approval: "content.status.pending_approval",
  approved: "content.status.approved",
  scheduled: "content.status.scheduled",
  publishing: "content.status.publishing",
  published: "content.status.published",
  rejected: "content.status.rejected",
  failed: "content.status.failed",
  archived: "content.status.archived",
};

const TONE: Record<string, string> = {
  pending_approval: "text-warning",
  approved: "text-success",
  rejected: "text-danger",
  failed: "text-danger",
};

/** Marketer and up review content; everyone else may look. The API decides. */
export function mayReview(role: string | undefined): boolean {
  return ["marketer", "manager", "admin", "owner"].includes(role ?? "");
}

/** "just_arrived" → "just arrived": the strategist's concept, readable. */
export function concept(item: Pick<ContentItem, "concept" | "kind">): string {
  return (item.concept ?? item.kind).replaceAll("_", " ");
}

/** Every piece as a card: its first image, what it is for, and where it stands. */
export function ContentGrid({ items, tenant }: { items: ContentItem[]; tenant: string }) {
  const t = useT();
  const locale = useLocale();
  if (items.length === 0) return <p className="text-muted text-sm">{t("content.empty")}</p>;
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/${tenant}/content/${item.id}`}
            className="bg-surface hover:ring-accent block overflow-hidden rounded-2xl hover:ring-2"
          >
            <div className="bg-background aspect-[4/5] w-full">
              {item.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- a signed link the image optimiser cannot fetch
                <img
                  src={mediaSrc(item.thumbnail_url)}
                  alt={concept(item)}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="text-muted flex h-full items-center justify-center text-xs">
                  {t(STATUS[item.status] ?? "content.status.draft")}
                </div>
              )}
            </div>
            <div className="space-y-0.5 p-2 text-xs">
              <p className="truncate font-medium capitalize">{concept(item)}</p>
              {item.vehicle && <p className="text-muted truncate">{item.vehicle}</p>}
              <p className="flex justify-between gap-2">
                <span className={TONE[item.status] ?? "text-muted"}>
                  {t(STATUS[item.status] ?? "content.status.draft")}
                </span>
                <span className="text-muted">{formatRelative(item.created_at, locale)}</span>
              </p>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
