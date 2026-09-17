"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { TenantApiProvider } from "@/lib/api/context";
import type { Locale } from "@/lib/i18n";
import { LocaleProvider } from "@/lib/i18n-client";

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
        <LocaleProvider locale={locale}>{children}</LocaleProvider>
      </TenantApiProvider>
    </QueryClientProvider>
  );
}
