"use client";

import { useCustomerTimeline, type TimelineEntry } from "@/lib/api/hooks";
import { Auto } from "@/components/Bidi";
import { formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

type Entry = TimelineEntry & { data: Record<string, unknown> };

function line(entry: Entry): { who: string; text: string } {
  const data = entry.data;
  if (entry.kind === "activity") {
    return { who: "·", text: String(data.body ?? data.activity_kind ?? "") };
  }
  const event = data.event as { text?: string } | null;
  if (event?.text) return { who: "·", text: event.text };
  const transcript = data.transcript as { text?: string } | null;
  const said = (data.body as string | null) ?? transcript?.text ?? "";
  // In and out, not left and right: these two arrows mean the same whichever
  // way the page runs.
  const who =
    data.direction === "in"
      ? "↙"
      : data.origin === "phone_app"
        ? "📱"
        : ((data.author as string | null) ?? "↗");
  return { who, text: said };
}

/**
 * Everything that has happened with this customer, newest first.
 *
 * Every channel and every lead move in one list, because "what did we say to
 * them" and "where did this go" are the same question asked twice.
 */
export function Timeline({ contactId }: { contactId: string }) {
  const t = useT();
  const locale = useLocale();
  const timeline = useCustomerTimeline(contactId);
  const entries = (timeline.data?.pages ?? []).flatMap((page) => page.data) as Entry[];

  if (timeline.isLoading) return <p className="text-muted p-4 text-sm">…</p>;
  if (entries.length === 0) {
    return <p className="text-muted p-4 text-sm">{t("customer.noTimeline")}</p>;
  }

  return (
    <div>
      <ol className="divide-y divide-black/5 dark:divide-white/10">
        {entries.map((entry) => {
          const { who, text } = line(entry);
          return (
            <li
              key={`${entry.kind}-${entry.id}`}
              className="flex gap-3 py-2"
              data-kind={entry.kind}
            >
              <span className="text-muted w-16 shrink-0 text-xs" aria-hidden>
                {who}
              </span>
              <Auto as="p" className="min-w-0 flex-1 whitespace-pre-wrap text-sm">
                {text}
              </Auto>
              <time className="text-muted shrink-0 text-xs" dateTime={entry.at}>
                {formatRelative(entry.at, locale)}
              </time>
            </li>
          );
        })}
      </ol>
      {timeline.hasNextPage && (
        <button
          type="button"
          onClick={() => timeline.fetchNextPage()}
          className="text-muted mx-auto mt-2 block min-h-11 px-3 text-xs underline"
        >
          {t("customer.loadMore")}
        </button>
      )}
    </div>
  );
}
