"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { TenantApiProvider } from "@/lib/api/context";
import { useNotifications } from "@/lib/api/hooks";
import type { Locale } from "@/lib/i18n";
import { LiveEvents } from "@/lib/live";
import { LocaleProvider } from "@/lib/i18n-client";
import { titleWithUnread } from "@/lib/title";

/**
 * The unread count in the tab title, so a salesperson working in another tab
 * still sees that something arrived.
 *
 * Next writes the title itself from each page's metadata, and does it after
 * this effect on a navigation — so the count has to be put back whenever the
 * title changes under us, not only when the count does.
 */
function UnreadInTitle() {
  const { data } = useNotifications();
  const unread = data?.unread ?? 0;
  useEffect(() => {
    const apply = () => {
      // Writing the title is itself a mutation: only write a different one, or
      // the observer feeds itself.
      const next = titleWithUnread(unread, document.title);
      if (document.title !== next) document.title = next;
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { subtree: true, childList: true, characterData: true });
    return () => observer.disconnect();
  }, [unread]);
  return null;
}

export function Providers({
  tenantId,
  slug,
  locale,
  children,
}: {
  tenantId: string;
  slug: string;
  locale: Locale;
  children: ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // A 403 or 404 will not turn into a 200 by asking again.
            retry: (count, error) =>
              !(error instanceof ApiError && error.problem.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <TenantApiProvider tenantId={tenantId} slug={slug}>
        <LocaleProvider locale={locale}>
          <LiveEvents />
          <UnreadInTitle />
          {children}
        </LocaleProvider>
      </TenantApiProvider>
    </QueryClientProvider>
  );
}
