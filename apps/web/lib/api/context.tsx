"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createApiClient, type ApiClient } from "./client";

type TenantApi = {
  tenantId: string;
  slug: string;
  api: ApiClient;
  /** Spread into every call: `{ params: { header } }`. */
  header: { "X-Tenant-Id": string };
};

const TenantApiContext = createContext<TenantApi | null>(null);

export function TenantApiProvider({
  tenantId,
  slug,
  children,
}: {
  tenantId: string;
  slug: string;
  children: ReactNode;
}) {
  const value = useMemo(
    () => ({ tenantId, slug, api: createApiClient(), header: { "X-Tenant-Id": tenantId } }),
    [tenantId, slug],
  );
  return <TenantApiContext.Provider value={value}>{children}</TenantApiContext.Provider>;
}

export function useTenantApi(): TenantApi {
  const value = useContext(TenantApiContext);
  if (!value) throw new Error("useTenantApi must be used inside TenantApiProvider");
  return value;
}
