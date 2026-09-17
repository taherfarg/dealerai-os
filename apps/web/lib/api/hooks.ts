"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { unwrap } from "./client";
import { useTenantApi } from "./context";
import { keys } from "./keys";

export function useMe() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.me(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/me", { params: { header } })),
  });
}

export function useSetAcceptingChats() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (accepting_chats: boolean) =>
      unwrap(await api.PATCH("/v1/me", { params: { header }, body: { accepting_chats } })),
    onSuccess: (me) => queryClient.setQueryData(keys.me(tenantId), me),
  });
}
