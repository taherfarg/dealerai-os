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
  suggestion: (tenantId: string, conversationId: string) =>
    ["suggestion", tenantId, conversationId] as const,
  documents: (tenantId: string) => ["documents", tenantId] as const,
  notifications: (tenantId: string) => ["notifications", tenantId] as const,
  /** One filtered list; `customerList` is its prefix, so one invalidation
   *  reaches every filter somebody has open. Same shape for leads and tasks. */
  customers: (tenantId: string, filters: string) => ["customers", tenantId, filters] as const,
  customerList: (tenantId: string) => ["customers", tenantId] as const,
  customer: (tenantId: string, id: string) => ["customer", tenantId, id] as const,
  timeline: (tenantId: string, id: string) => ["timeline", tenantId, id] as const,
  pipelines: (tenantId: string) => ["pipelines", tenantId] as const,
  leads: (tenantId: string, filters: string) => ["leads", tenantId, filters] as const,
  leadList: (tenantId: string) => ["leads", tenantId] as const,
  lead: (tenantId: string, id: string) => ["lead", tenantId, id] as const,
  tasks: (tenantId: string, filters: string) => ["tasks", tenantId, filters] as const,
  taskList: (tenantId: string) => ["tasks", tenantId] as const,
  myDay: (tenantId: string) => ["my-day", tenantId] as const,
  /** One day's dashboard; `dashboardAll` is its prefix, so a live event
   *  refreshes whichever day is open. */
  dashboard: (tenantId: string, date: string) => ["dashboard", tenantId, date] as const,
  dashboardAll: (tenantId: string) => ["dashboard", tenantId] as const,
  salesSettings: (tenantId: string) => ["sales-settings", tenantId] as const,
  acceptance: (tenantId: string, days: number) => ["acceptance", tenantId, days] as const,
  quickReplies: (tenantId: string) => ["quick-replies", tenantId] as const,
  channels: (tenantId: string) => ["channels", tenantId] as const,
  templates: (tenantId: string, channelId: string) =>
    ["templates", tenantId, channelId] as const,
};
