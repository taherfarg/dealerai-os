"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useTenantApi } from "@/lib/api/context";
import { useMarkNotificationsRead, useNotifications } from "@/lib/api/hooks";
import { Sentence } from "@/components/Bidi";
import { Icon } from "@/components/Icon";
import { formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

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
  const locale = useLocale();
  const { slug } = useTenantApi();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
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
      // A menu, not a modal: Escape puts it away and hands focus back to the
      // bell, so the keyboard is where it was before the list opened.
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open) return;
        setOpen(false);
        button.current?.focus();
      }}
    >
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-label={unread ? `${t("notifications.title")} (${unread})` : t("notifications.title")}
        onClick={() => setOpen((was) => !was)}
        className="icon-btn"
      >
        <Icon name="bell" size={22} />
        {unread > 0 && <span className="badge absolute end-0.5 top-0.5">{unread}</span>}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t("notifications.title")}
          // Under the top row on a phone, across its width; beside the foot of
          // the rail on a desk, where the bell is. Fixed at both sizes: the rail
          // scrolls inside itself, and would cut off anything positioned in it.
          className="border-border bg-background fixed inset-x-3 top-14 z-20 max-h-96 overflow-y-auto rounded-lg border shadow-lg md:inset-x-auto md:start-24 md:top-auto md:bottom-3 md:w-80"
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
                      <Sentence className="text-sm font-medium">{row.title}</Sentence>
                      <time className="text-muted shrink-0 text-xs" dateTime={row.created_at}>
                        {formatRelative(row.created_at, locale)}
                      </time>
                    </span>
                    {row.body && (
                      <span className="text-muted block text-sm">
                        <Sentence>{row.body}</Sentence>
                      </span>
                    )}
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
                        className="hover:bg-surface block px-3 py-2"
                      >
                        {inside}
                      </Link>
                    ) : (
                      <button
                        type="button"
                        onClick={seen}
                        className="hover:bg-surface block w-full px-3 py-2 text-start"
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
