"use client";

import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { ApiError } from "@/lib/api/client";
import { useConversationCounts, useConversations, useMe, type ConversationView } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";
import { ConversationRow } from "./ConversationRow";

const VIEWS_BY_SCOPE: Record<string, ConversationView[]> = {
  own: ["mine", "unassigned"],
  team: ["mine", "unassigned", "team"],
  all: ["mine", "unassigned", "team", "all"],
};

const TAB_KEYS = {
  mine: "inbox.tabs.mine",
  unassigned: "inbox.tabs.unassigned",
  team: "inbox.tabs.team",
  all: "inbox.tabs.all",
} as const;

/**
 * The queue. The view and the search live in the URL, so a link to the inbox is
 * a link to the same inbox — and a reload keeps the tab a rep was working in.
 */
export function ConversationList() {
  const t = useT();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { tenant, conversationId } = useParams<{ tenant: string; conversationId?: string }>();

  const me = useMe();
  const scope = me.data?.scope ?? "own";
  const allowed = VIEWS_BY_SCOPE[scope] ?? VIEWS_BY_SCOPE.own;
  const requested = (params.get("view") ?? "mine") as ConversationView;
  const view = allowed.includes(requested) ? requested : "mine";
  const status = params.get("status") ?? "open";
  const q = params.get("q") ?? "";

  const counts = useConversationCounts();
  const searchTimer = useRef<number>(undefined);
  const conversations = useConversations({ view, status, q });
  const rows = conversations.data?.pages.flatMap((page) => page.data) ?? [];

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value && value !== "open") next.set(key, value);
    else next.delete(key);
    router.replace(`${pathname}?${next.toString()}`);
  };

  // Infinite scroll: load the next page when the end of the list comes into view.
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const target = end.current;
    if (!target || !conversations.hasNextPage) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !conversations.isFetchingNextPage) {
        void conversations.fetchNextPage();
      }
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, [conversations]);

  // The page's heading — or, beside an open conversation, the heading under
  // that customer's. Not shown: the tabs already say where one is.
  const Heading = conversationId ? "h2" : "h1";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Heading className="sr-only">{t("nav.inbox")}</Heading>
      <div className="border-b border-black/5 p-3 dark:border-white/10">
        <div role="tablist" aria-label={t("nav.inbox")} className="flex gap-1">
          {allowed.map((candidate) => {
            const count = counts.data?.[candidate];
            return (
              <button
                key={candidate}
                type="button"
                role="tab"
                aria-selected={candidate === view}
                onClick={() => setParam("view", candidate === "mine" ? "" : candidate)}
                className={`min-h-11 rounded-md px-3 text-sm transition-colors ${
                  candidate === view ? "bg-background font-medium" : "hover:bg-background"
                }`}
              >
                {t(TAB_KEYS[candidate])}
                {count && count.waiting > 0 ? (
                  <span className="text-muted ms-1 text-xs">{count.waiting}</span>
                ) : null}
              </button>
            );
          })}
        </div>
        <input
          type="search"
          defaultValue={q}
          placeholder={t("inbox.search")}
          aria-label={t("inbox.search")}
          onChange={(event) => {
            const value = event.target.value;
            window.clearTimeout(searchTimer.current);
            searchTimer.current = window.setTimeout(() => setParam("q", value), 300);
          }}
          className="mt-2 min-h-11 w-full rounded-md border border-black/10 px-3 text-sm dark:border-white/15"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {conversations.isPending && <ListSkeleton />}
        {conversations.isError && (
          <p className="p-4 text-sm text-red-600 dark:text-red-400">
            {conversations.error instanceof ApiError
              ? conversations.error.problem.detail ?? conversations.error.problem.title
              : t("inbox.retry")}
          </p>
        )}
        {conversations.isSuccess && rows.length === 0 && (
          <p className="text-muted p-4 text-sm">
            {view === "unassigned" ? t("inbox.emptyUnassigned") : t("inbox.empty")}
          </p>
        )}
        <ul>
          {rows.map((conversation) => (
            <ConversationRow
              key={conversation.id}
              conversation={conversation}
              href={`/${tenant}/inbox/${conversation.id}`}
              active={conversation.id === conversationId}
            />
          ))}
        </ul>
        <div ref={end} />
      </div>
    </div>
  );
}

function ListSkeleton() {
  return (
    <ul aria-hidden className="animate-pulse">
      {[0, 1, 2, 3].map((row) => (
        <li key={row} className="border-b border-black/5 px-3 py-4 dark:border-white/10">
          <div className="bg-muted/20 h-4 w-1/3 rounded" />
          <div className="bg-muted/10 mt-2 h-3 w-2/3 rounded" />
        </li>
      ))}
    </ul>
  );
}
