/** Every query key in one place, so an invalidation can never miss a spelling. */
export const keys = {
  me: (tenantId: string) => ["me", tenantId] as const,
  members: (tenantId: string) => ["members", tenantId] as const,
  teams: (tenantId: string) => ["teams", tenantId] as const,
  /** One filtered list. `conversationList` is its prefix, so a live event can
   *  invalidate every view at once without knowing which one is open. */
  conversations: (tenantId: string, view: string, filters: string) =>
    ["conversations", tenantId, view, filters] as const,
  conversationList: (tenantId: string) => ["conversations", tenantId] as const,
  counts: (tenantId: string) => ["conversation-counts", tenantId] as const,
  conversation: (tenantId: string, id: string) => ["conversation", tenantId, id] as const,
  messages: (tenantId: string, id: string) => ["messages", tenantId, id] as const,
  notifications: (tenantId: string) => ["notifications", tenantId] as const,
};
