// lib/sales/types.ts
// THE API CONTRACT between apps/web and the FastAPI backend.
// The backend returns exactly these shapes. Change only by agreement with the backend.

export type ID = string; // uuid
export type ISODate = string; // RFC 3339, UTC
export type Lang = "ar" | "en" | "fr";

/** 16500000 minor units = AED 165,000.00. Never a float, never a formatted string. */
export type Money = { amount_minor: number; currency: string };

export type Page<T> = { data: T[]; next_cursor: string | null };

/** RFC 9457 problem+json: the only error shape the API returns. */
export type Problem = { type: string; title: string; status: number; detail?: string; trace_id?: string };

// ---------- people, roles, visibility ----------
export type Role = "owner" | "admin" | "manager" | "sales" | "marketer" | "viewer";
/** owner/admin/viewer -> all · manager -> team · sales -> own (+ unassigned queue of their teams) */
export type Scope = "all" | "team" | "own";

export type Permission =
  | "inbox.assign"
  | "inbox.send"
  | "contacts.reassign"
  | "contacts.merge"
  | "leads.mark_won_lost"
  | "pipeline.edit_stages"
  | "dashboard.manager"
  | "settings.channels"
  | "settings.team"
  | "settings.routing"
  | "settings.quick_replies"
  | "settings.knowledge"
  | "settings.ai";

export type UserRef = { id: ID; name: string; avatar_url: string | null };

export type Me = {
  user: UserRef & { email: string };
  tenant: {
    id: ID;
    slug: string;
    name: string;
    timezone: string;
    currency: string;
    logo_url: string | null;
    accent_color: string | null;
  };
  role: Role;
  scope: Scope;
  team_ids: ID[];
  permissions: Permission[];
  accepting_chats: boolean;
};

export type Member = UserRef & {
  email: string;
  role: Role;
  team_ids: ID[];
  languages: Lang[];
  accepting_chats: boolean;
  open_conversations: number;
  last_active_at: ISODate | null;
};

export type Team = { id: ID; name: string; member_ids: ID[]; manager_ids: ID[] };

// ---------- channels, templates, quick replies ----------
export type ChannelPlatform = "whatsapp" | "instagram" | "messenger" | "website_chat" | "email";

export type Channel = {
  id: ID;
  platform: ChannelPlatform;
  name: string;
  handle: string; // "+971 50 266 7937"
  mode: "coexistence" | "cloud_api" | null; // WhatsApp only
  status: "connected" | "syncing" | "error" | "revoked";
  status_detail: string | null; // human-readable cause when not connected
  history_sync: { phase: 0 | 1 | 2; progress: number; completed_at: ISODate | null } | null; // progress 0..100
  quality_rating: "green" | "yellow" | "red" | null;
  connected_at: ISODate;
};

export type Template = {
  id: ID;
  channel_id: ID;
  name: string;
  language: Lang;
  category: "marketing" | "utility" | "authentication";
  status: "approved" | "pending" | "rejected" | "paused";
  body: string; // "Hi {{1}}, the {{2}} is now available."
  variables: string[]; // labels for {{1}}, {{2}} ...
  rejected_reason: string | null;
};

export type QuickReply = { id: ID; shortcut: string; title: string; body: Record<Lang, string | null> };

// ---------- inventory (read-only here) ----------
export type VehicleSummary = {
  id: ID;
  title: string; // "Toyota Hilux GR Sport"
  year: number;
  color: string | null;
  price: Money | null;
  status: "available" | "reserved" | "sold";
  photo_url: string | null;
  stock_days: number;
};

// ---------- contacts ----------
export type IdentityKind = "whatsapp_user_id" | "phone" | "instagram_id" | "messenger_psid" | "email";
export type Identity = { kind: IdentityKind; value: string; display: string; is_primary: boolean };

/** Each profile value remembers who set it and which message it came from. */
export type ProfileField<T> = {
  value: T;
  source: "ai" | "human";
  evidence_message_id: ID | null;
  updated_at: ISODate;
};

export type ContactProfile = {
  interest?: ProfileField<string>; // "Hilux GR Sport, white"
  vehicle_ids?: ProfileField<ID[]>;
  budget?: ProfileField<Money>;
  purchase_type?: ProfileField<"local" | "export">;
  destination_country?: ProfileField<string>; // ISO-2, e.g. "DZ"
  timeline?: ProfileField<string>;
  payment?: ProfileField<"cash" | "finance" | "unknown">;
  trade_in?: ProfileField<string>;
  objections?: ProfileField<string[]>;
};

export type LeadBand = "hot" | "warm" | "cold";

export type ContactSummary = {
  id: ID;
  name: string;
  avatar_url: string | null;
  primary_display: string; // phone, or "@username" when WhatsApp hides the number
  country: string | null; // ISO-2
  language: Lang | null;
  owner: UserRef | null;
  tags: string[];
  lead_band: LeadBand | null; // best open lead
  last_seen_at: ISODate;
};

export type Contact = ContactSummary & {
  identities: Identity[];
  profile: ContactProfile;
  consent: { marketing: boolean; opted_out_at: ISODate | null };
  open_leads: LeadSummary[];
  open_tasks: Task[];
  conversations: ConversationSummary[];
  created_at: ISODate;
};

// ---------- conversations & messages ----------
export type ConversationStatus = "open" | "waiting_customer" | "closed" | "spam";
export type ConversationView = "mine" | "unassigned" | "team" | "all";

export type MessageType =
  | "text"
  | "image"
  | "audio"
  | "video"
  | "document"
  | "location"
  | "sticker"
  | "template"
  | "interactive_reply"
  | "vehicle_card"
  | "unsupported";

/** customer = from the customer · inbox = sent from this app · phone_app = typed in the WhatsApp
 *  Business app on the phone · history = imported · system = generated */
export type MessageOrigin = "customer" | "inbox" | "phone_app" | "history" | "system";
export type MessageStatus = "queued" | "sent" | "delivered" | "read" | "failed";

export type ConversationSummary = {
  id: ID;
  channel: { id: ID; platform: ChannelPlatform; name: string };
  contact: ContactSummary;
  status: ConversationStatus;
  assignee: UserRef | null;
  team: { id: ID; name: string } | null;
  last_message: {
    // The words that arrived, or "" when none did: what kind of thing a photo or
    // a voice note is, the screen says from `type`, in its reader's language.
    preview: string;
    type: MessageType;
    direction: "in" | "out";
    origin: MessageOrigin;
    at: ISODate;
  };
  unread_count: number;
  waiting_since: ISODate | null; // set while the customer is waiting on us
  sla_due_at: ISODate | null;
  sla_state: "ok" | "due_soon" | "breached" | null;
  window_expires_at: ISODate | null; // WhatsApp 24h window; null or in the past = closed
  has_ai_draft: boolean;
};

export type Conversation = ConversationSummary & {
  summary: { text: string; next_action: string | null; updated_at: ISODate } | null;
  lead: LeadSummary | null;
};

export type ConversationCounts = Record<ConversationView, { waiting: number; unread: number }>;

export type Attachment = {
  url: string;
  mime: string;
  filename: string | null;
  size_bytes: number | null;
  duration_s: number | null; // audio / video
  width: number | null;
  height: number | null;
};

export type Message = {
  id: ID;
  conversation_id: ID;
  kind: "message" | "note" | "event"; // note = internal, never sent · event = timeline marker
  type: MessageType;
  direction: "in" | "out";
  origin: MessageOrigin;
  author: UserRef | null; // rep who sent it; null for customer and phone_app
  text: string | null;
  attachment: Attachment | null;
  transcript: { text: string; language: Lang } | null; // voice notes
  location: { lat: number; lng: number; name: string | null } | null;
  template: { name: string; language: Lang; rendered: string } | null;
  vehicle: VehicleSummary | null; // type = vehicle_card
  reply_to: { id: ID; preview: string } | null;
  reactions: { emoji: string; from: "customer" | "business" }[];
  status: MessageStatus | null; // outbound only
  error: { code: string; message: string } | null; // when status = failed
  event: {
    type:
      | "assigned" | "unassigned" | "closed" | "reopened" | "spam"
      | "lead_created" | "stage_change" | "conversation.reopened" | "history_imported";
    text?: string; // the sentence in English: what a screen shows for a type it has no words for
    name?: string; // who or what it happened to (the assignee, the stage), apart from the sentence
  } | null;
  referral: { source: "ad"; headline: string; ad_id: string } | null; // came from a Click-to-WhatsApp ad
  created_at: ISODate;
};

export type SendMessageInput =
  | { type: "text"; text: string; reply_to_id?: ID; suggestion_id?: ID }
  | { type: "attachment"; upload_id: ID; caption?: string }
  | { type: "template"; template_id: ID; variables: string[] }
  | { type: "vehicle_card"; vehicle_id: ID; text?: string };

// ---------- AI copilot ----------
export type Intent =
  | "greeting"
  | "price"
  | "availability"
  | "specs"
  | "export_shipping"
  | "financing"
  | "trade_in"
  | "visit_test_drive"
  | "documents_payment"
  | "negotiation"
  | "complaint"
  | "human_request"
  | "opt_out"
  | "other";

export type SuggestionAction =
  | { kind: "create_lead"; pipeline_id: ID; vehicle_id: ID | null; label: string }
  | { kind: "move_stage"; lead_id: ID; stage_id: ID; label: string }
  | { kind: "create_task"; title: string; due_at: ISODate; label: string }
  | { kind: "update_profile"; field: keyof ContactProfile; value: unknown; label: string };

export type SuggestionSource =
  | { kind: "vehicle"; vehicle: VehicleSummary }
  | { kind: "document"; document_id: ID; title: string; excerpt: string };

export type Suggestion = {
  id: ID;
  conversation_id: ID;
  for_message_id: ID;
  status: "generating" | "ready" | "blocked" | "superseded";
  text: string | null; // null when a template is proposed, or when blocked
  template: { template_id: ID; variables: string[] } | null; // proposed when the 24h window is closed
  language: Lang;
  confidence: "high" | "medium" | "low";
  intent: Intent;
  sources: SuggestionSource[];
  actions: SuggestionAction[];
  needs_human: string | null; // e.g. "Customer asked for a final price"
  // Why no draft was shown: each refusal as "check: detail", joined by "; " — the
  // screen says which check it was in its reader's language. Null when the model
  // simply produced nothing.
  blocked_reason: string | null;
  created_at: ISODate;
};

export type SuggestionOutcome = {
  outcome: "sent" | "edited" | "discarded";
  final_text?: string;
  reason?: string;
};

// ---------- pipeline, leads, tasks ----------
export type Stage = { id: ID; name: string; position: number; category: "open" | "won" | "lost" };
export type Pipeline = { id: ID; name: string; stages: Stage[] };

export type LeadSource = "whatsapp" | "ad" | "instagram" | "walk_in" | "import" | "manual";

export type LeadSummary = {
  id: ID;
  contact: ContactSummary;
  pipeline_id: ID;
  stage: Stage;
  vehicle: VehicleSummary | null;
  budget: Money | null;
  score: number; // 0..100, computed by code from signals
  band: LeadBand;
  owner: UserRef | null;
  next_action: { title: string; due_at: ISODate } | null;
  source: LeadSource;
  stage_entered_at: ISODate;
  created_at: ISODate;
};

export type ScoreReason = { signal: string; label: string; points: number; evidence_message_id: ID | null };

export type Lead = LeadSummary & {
  score_reasons: ScoreReason[];
  stage_history: { stage: Stage; at: ISODate; by: UserRef | null }[];
  lost_reason: string | null;
  conversation_id: ID | null;
};

export type Task = {
  id: ID;
  title: string;
  kind: "follow_up" | "call" | "meeting" | "todo";
  due_at: ISODate;
  status: "open" | "done" | "cancelled";
  assignee: UserRef;
  contact: ContactSummary | null;
  lead_id: ID | null;
  conversation_id: ID | null;
  source: "human" | "ai" | "rule";
  /** Follow-up drafted by the AI: the reason to write, and a text or a template (window closed). */
  ai_draft: { reason: string; text: string | null; template_id: ID | null } | null;
  created_at: ISODate;
};

// ---------- notifications, dashboards ----------
export type Notification = {
  id: ID;
  kind: "new_conversation" | "assigned" | "sla_due" | "sla_breached" | "task_due" | "lead_hot" | "channel_error";
  title: string;
  body: string;
  href: string; // in-app path, e.g. "/pollux-motors/inbox/<id>"
  read_at: ISODate | null;
  created_at: ISODate;
};

export type DailyBrief = {
  generated_at: ISODate;
  headline: string;
  items: { text: string; href: string | null; severity: "info" | "warning" | "opportunity" }[];
};

export type ManagerDashboard = {
  date: string; // YYYY-MM-DD in the tenant timezone
  tiles: {
    new_conversations: number;
    waiting_now: number;
    median_first_response_s: number | null;
    sla_breaches: number;
    new_leads: number;
    hot_leads: number;
    won: number;
    lost: number;
  };
  reps: {
    user: UserRef;
    accepting_chats: boolean;
    open: number;
    waiting: number;
    median_first_response_s: number | null;
    breaches: number;
    overdue_tasks: number;
    leads: Record<LeadBand, number>;
    won_this_month: number;
  }[];
  oldest_waiting: ConversationSummary[];
  pipelines: { pipeline_id: ID; name: string; stages: { stage: Stage; count: number; value: Money }[] }[];
  sources: { source: LeadSource; leads: number }[];
  reply_origin_share: { inbox: number; phone_app: number }; // fractions 0..1
  brief: DailyBrief | null;
};

export type MyDay = {
  waiting_on_me: ConversationSummary[];
  tasks_due: Task[];
  hot_leads: LeadSummary[];
  stats: { replied_today: number; median_first_response_s: number | null };
};

// ---------- settings ----------
export type SalesSettings = {
  timezone: string;
  business_hours: { day: 0 | 1 | 2 | 3 | 4 | 5 | 6; open: string; close: string }[]; // "09:00"; 0 = Sunday
  first_response_target_min: number;
  unassigned_visible_to_sales: boolean;
  default_team_id: ID;
  routing_rules: { id: ID; when: { language?: Lang; country?: string; ad_id?: string }; team_id: ID }[];
  ai: { drafts_enabled: boolean; arabic_register: "mirror_customer" | "msa"; follow_up_cadence_days: number[] };
};

export type KnowledgeDocument = {
  id: ID;
  title: string;
  filename: string;
  language: Lang | null;
  status: "processing" | "ready" | "failed";
  chunks: number;
  uploaded_by: UserRef;
  created_at: ISODate;
};

// ---------- live events (SSE /v1/stream): nudges only, the client refetches ----------
export type LiveEvent =
  | { type: "conversation.updated"; conversation_id: ID }
  | { type: "message.created"; conversation_id: ID; message_id: ID }
  | { type: "message.status"; conversation_id: ID; message_id: ID; status: MessageStatus }
  | { type: "suggestion.ready"; conversation_id: ID; suggestion_id: ID }
  | { type: "lead.updated"; lead_id: ID }
  | { type: "task.updated"; task_id: ID }
  | { type: "notification.created"; notification_id: ID }
  | { type: "channel.updated"; channel_id: ID };

// ---------- the API surface ----------
export interface SalesApi {
  me(): Promise<Me>;
  setAcceptingChats(value: boolean): Promise<Me>;

  // inbox
  listConversations(q: {
    view: ConversationView;
    status?: ConversationStatus;
    channel_id?: ID;
    q?: string;
    cursor?: string;
  }): Promise<Page<ConversationSummary>>;
  conversationCounts(): Promise<ConversationCounts>;
  getConversation(id: ID): Promise<Conversation>;
  listMessages(conversationId: ID, cursor?: string): Promise<Page<Message>>; // newest first
  sendMessage(conversationId: ID, input: SendMessageInput, idempotencyKey: string): Promise<Message>;
  addNote(conversationId: ID, text: string): Promise<Message>;
  assignConversation(conversationId: ID, userId: ID | null): Promise<Conversation>;
  setConversationStatus(conversationId: ID, status: ConversationStatus): Promise<Conversation>;
  markRead(conversationId: ID): Promise<void>;
  retryMessage(messageId: ID): Promise<Message>;
  uploadAttachment(file: File): Promise<{ upload_id: ID }>;
  getSuggestion(conversationId: ID): Promise<Suggestion | null>;
  regenerateSuggestion(conversationId: ID): Promise<Suggestion>;
  recordSuggestionOutcome(suggestionId: ID, outcome: SuggestionOutcome): Promise<void>;
  listTemplates(channelId: ID): Promise<Template[]>;
  listQuickReplies(): Promise<QuickReply[]>;
  searchVehicles(q: string): Promise<VehicleSummary[]>;

  // customers
  listContacts(q: {
    q?: string;
    owner_id?: ID;
    band?: LeadBand;
    country?: string;
    tag?: string;
    cursor?: string;
  }): Promise<Page<ContactSummary>>;
  getContact(id: ID): Promise<Contact>;
  getContactTimeline(id: ID, cursor?: string): Promise<Page<Message>>; // all channels, newest first
  updateContact(
    id: ID,
    patch: { name?: string; tags?: string[]; profile?: Partial<Record<keyof ContactProfile, unknown>> },
  ): Promise<Contact>;
  reassignContact(id: ID, ownerId: ID): Promise<Contact>; // also moves open conversations, leads and tasks
  mergeContacts(keepId: ID, mergeId: ID): Promise<Contact>;

  // pipeline
  listPipelines(): Promise<Pipeline[]>;
  listLeads(q: { pipeline_id: ID; owner_id?: ID; band?: LeadBand; q?: string }): Promise<LeadSummary[]>;
  getLead(id: ID): Promise<Lead>;
  createLead(input: { contact_id: ID; pipeline_id: ID; vehicle_id?: ID; budget?: Money }): Promise<Lead>;
  updateLead(
    id: ID,
    patch: { stage_id?: ID; owner_id?: ID; vehicle_id?: ID | null; budget?: Money | null; lost_reason?: string },
  ): Promise<Lead>;

  // tasks
  listTasks(q: { assignee: "me" | "team" | ID; bucket: "overdue" | "today" | "upcoming" | "done" }): Promise<Task[]>;
  createTask(input: {
    title: string;
    kind: Task["kind"];
    due_at: ISODate;
    assignee_id: ID;
    contact_id?: ID;
    lead_id?: ID;
  }): Promise<Task>;
  updateTask(id: ID, patch: { status?: Task["status"]; due_at?: ISODate; title?: string }): Promise<Task>;
  sendTaskDraft(id: ID, idempotencyKey: string): Promise<Message>;

  // dashboards & notifications
  managerDashboard(date?: string): Promise<ManagerDashboard>;
  myDay(): Promise<MyDay>;
  listNotifications(): Promise<Notification[]>;
  markNotificationsRead(ids: ID[]): Promise<void>;

  // settings
  listChannels(): Promise<Channel[]>;
  connectWhatsApp(): Promise<Channel>; // real: Meta Embedded Signup · mock: simulated flow + sync progress
  listMembers(): Promise<Member[]>;
  updateMember(
    id: ID,
    patch: { role?: Role; team_ids?: ID[]; languages?: Lang[]; accepting_chats?: boolean },
  ): Promise<Member>;
  inviteMember(input: { email: string; role: Role; team_ids: ID[] }): Promise<void>;
  listTeams(): Promise<Team[]>;
  getSalesSettings(): Promise<SalesSettings>;
  updateSalesSettings(patch: Partial<SalesSettings>): Promise<SalesSettings>;
  updatePipelineStages(pipelineId: ID, stages: Array<Omit<Stage, "id"> & { id?: ID }>): Promise<Pipeline>;
  saveQuickReply(input: Omit<QuickReply, "id"> & { id?: ID }): Promise<QuickReply>;
  deleteQuickReply(id: ID): Promise<void>;
  listDocuments(): Promise<KnowledgeDocument[]>;
  uploadDocument(file: File): Promise<KnowledgeDocument>;
  deleteDocument(id: ID): Promise<void>;

  createTeam(input: { name: string; member_ids: ID[] }): Promise<Team>;
  updateTeam(id: ID, patch: { name?: string; member_ids?: ID[] }): Promise<Team>;
  deleteTeam(id: ID): Promise<void>;
  syncChannelTemplates(channelId: ID): Promise<Template[]>;
  checkChannelHealth(channelId: ID): Promise<Channel>;
  /** After a coexistence history import: the backlog to distribute. */
  listImportedCustomers(channelId: ID, cursor?: string): Promise<Page<ContactSummary>>;
  assignImportedCustomers(channelId: ID, input: { contact_ids: ID[]; owner_id: ID }): Promise<void>;
  todayBrief(): Promise<DailyBrief | null>;
  /** UAE PDPL: export everything held about one customer, then erase on request. */
  exportCustomer(id: ID): Promise<{ download_url: string }>;
  deleteCustomer(id: ID): Promise<void>;
  savePushSubscription(input: {
    endpoint: string;
    p256dh: string;
    auth: string;
    user_agent: string;
  }): Promise<{ id: ID }>;
  deletePushSubscription(id: ID): Promise<void>;

  // live updates
  subscribe(onEvent: (event: LiveEvent) => void): () => void;
}
