"use client";

import Link from "next/link";
import { useState } from "react";
import { useTenantApi } from "@/lib/api/context";
import { useMarkNotificationsRead, useNotifications } from "@/lib/api/hooks";
import { formatRelative } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

/** Older than this and it is history, not news. */
const SHOWN = 20;

/**
 * What happened while you were looking somewhere else.
 *
 * Opening it reads nothing. Acting on an item reads that item, and the button
 * reads the lot — a badge that clears itself is a badge people learn to ignore.
 * Read notifications stay in the list: it is also the record of what you were
 * told, which is the first thing asked for after a customer was missed.
 */
export function NotificationsBell() {
  const t = useT();
  const { slug } = useTenantApi();
  const [open, setOpen] = useState(false);
  const notifications = useNotifications();
  const markRead = useMarkNotificationsRead();

  const unread = notifications.data?.unread ?? 0;
  const rows = notifications.data?.data.slice(0, SHOWN) ?? [];

  return (
    // Closing on focusout covers clicking away and tabbing away both, without
    // a document-wide listener that would outlive this popover.
    <div
      className="relative"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-label={unread ? `${t("notifications.title")} (${unread})` : t("notifications.title")}
        onClick={() => setOpen((was) => !was)}
        className="hover:bg-background relative min-h-11 rounded-md px-2 text-lg"
      >
        <span aria-hidden>🔔</span>
        {unread > 0 && (
          <span className="bg-accent absolute end-0 top-1 min-w-4 rounded-full px-1 text-[11px] font-medium leading-4 text-black">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t("notifications.title")}
          // Anchored to the start edge on desktop because the bell lives in the
          // sidebar: an end-anchored popover would open off the side of the
          // screen. On a phone it spans the width instead of overflowing it.
          className="border-border bg-surface fixed inset-x-3 top-16 z-20 max-h-96 overflow-y-auto rounded-md border shadow-lg md:absolute md:inset-x-auto md:start-0 md:top-full md:mt-1 md:w-80"
        >
          <div className="border-border flex items-center justify-between gap-2 border-b px-3 py-2">
            <span className="text-sm font-medium">{t("notifications.title")}</span>
            {unread > 0 && (
              <button
                type="button"
                onClick={() => markRead.mutate("all")}
                className="text-muted text-xs underline"
              >
                {t("notifications.markAllRead")}
              </button>
            )}
          </div>

          {rows.length === 0 ? (
            <p className="text-muted p-4 text-sm">{t("notifications.empty")}</p>
          ) : (
            <ul>
              {rows.map((row) => {
                const seen = () => {
                  if (!row.read_at) markRead.mutate([row.id]);
                  setOpen(false);
                };
                const inside = (
                  <>
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium">{row.title}</span>
                      <time className="text-muted shrink-0 text-xs" dateTime={row.created_at}>
                        {formatRelative(row.created_at)}
                      </time>
                    </span>
                    {row.body && <span className="text-muted block text-sm">{row.body}</span>}
                  </>
                );
                return (
                  <li
                    key={row.id}
                    data-read={row.read_at ? "yes" : "no"}
                    className={`border-border border-b last:border-b-0 ${
                      row.read_at ? "" : "bg-accent/10"
                    }`}
                  >
                    {row.href ? (
                      <Link
                        href={`/${slug}${row.href}`}
                        onClick={seen}
                        className="hover:bg-background block px-3 py-2"
                      >
                        {inside}
                      </Link>
                    ) : (
                      <button
                        type="button"
                        onClick={seen}
                        className="hover:bg-background block w-full px-3 py-2 text-start"
                      >
                        {inside}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
