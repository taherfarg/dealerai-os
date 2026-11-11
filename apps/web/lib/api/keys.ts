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
  pushKey: (tenantId: string) => ["push-key", tenantId] as const,
  pushDevices: (tenantId: string) => ["push-devices", tenantId] as const,
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
  /** One filtered stock list; `vehicleList` is its prefix. */
  vehicles: (tenantId: string, filters: string) => ["vehicles", tenantId, filters] as const,
  vehicleList: (tenantId: string) => ["vehicles", tenantId] as const,
  vehicle: (tenantId: string, id: string) => ["vehicle", tenantId, id] as const,
  /** The buy side. `buySide` is the prefix of everything below it, so a cost
   *  recorded anywhere refreshes every margin on screen. */
  buySide: (tenantId: string) => ["buy-side", tenantId] as const,
  economicsList: (tenantId: string) => ["buy-side", tenantId, "economics"] as const,
  buyingList: (tenantId: string) => ["buy-side", tenantId, "buying-list"] as const,
  /** Every content list; a filtered one is this plus its status. */
  contentList: (tenantId: string) => ["content", tenantId, "list"] as const,
  content: (tenantId: string, id: string) => ["content", tenantId, "item", id] as const,
  contentCalendar: (tenantId: string, from: string, to: string) =>
    ["content", tenantId, "calendar", from, to] as const,
  economics: (tenantId: string, id: string) => ["buy-side", tenantId, "economics", id] as const,
  costs: (tenantId: string, id: string) => ["buy-side", tenantId, "costs", id] as const,
  acquisition: (tenantId: string, id: string) =>
    ["buy-side", tenantId, "acquisition", id] as const,
  pricing: (tenantId: string, id: string) => ["buy-side", tenantId, "pricing", id] as const,
  pricingSettings: (tenantId: string) => ["pricing-settings", tenantId] as const,
  recon: (tenantId: string, id: string) => ["buy-side", tenantId, "recon", id] as const,
  reconSettings: (tenantId: string) => ["recon-settings", tenantId] as const,
  /** Under the buy side's prefix although a salesperson reads it too: a cost
   *  recorded anywhere changes what this car's landed cost is still missing. */
  inbound: (tenantId: string, id: string) => ["buy-side", tenantId, "inbound", id] as const,
  /** A car's orders. Under the buy side's prefix: each carries its margin. */
  orders: (tenantId: string, vehicleId: string) =>
    ["buy-side", tenantId, "orders", vehicleId] as const,
  exportFile: (tenantId: string, orderId: string) => ["export-file", tenantId, orderId] as const,
  invoice: (tenantId: string, orderId: string) => ["invoice", tenantId, orderId] as const,
  documentSettings: (tenantId: string) => ["document-settings", tenantId] as const,
};
