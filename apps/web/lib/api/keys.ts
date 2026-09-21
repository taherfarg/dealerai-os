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
  conversation: (tenantId: string, id: string) =>
    ["conversation", tenantId, id] as const,
  messages: (tenantId: string, id: string) =>
    ["messages", tenantId, id] as const,
  notifications: (tenantId: string) => ["notifications", tenantId] as const,
  /** One filtered list; `customerList` is its prefix, so one invalidation
   *  reaches every filter somebody has open. Same shape for leads and tasks. */
  customers: (tenantId: string, filters: string) =>
    ["customers", tenantId, filters] as const,
  customerList: (tenantId: string) => ["customers", tenantId] as const,
  customer: (tenantId: string, id: string) =>
    ["customer", tenantId, id] as const,
  timeline: (tenantId: string, id: string) =>
    ["timeline", tenantId, id] as const,
  pipelines: (tenantId: string) => ["pipelines", tenantId] as const,
  leads: (tenantId: string, filters: string) =>
    ["leads", tenantId, filters] as const,
  leadList: (tenantId: string) => ["leads", tenantId] as const,
  lead: (tenantId: string, id: string) => ["lead", tenantId, id] as const,
  tasks: (tenantId: string, filters: string) =>
    ["tasks", tenantId, filters] as const,
  taskList: (tenantId: string) => ["tasks", tenantId] as const,
  myDay: (tenantId: string) => ["my-day", tenantId] as const,
};
