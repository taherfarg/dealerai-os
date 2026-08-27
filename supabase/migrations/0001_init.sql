-- =============================================================================
-- DealerAI OS — 0001_init
-- MVP schema: tenancy, brand, vehicles, channels, content, inbox, CRM,
--             agent runtime, events, memory.
-- Ads + market intelligence live in 0002_growth.sql.
--
-- Conventions
--   * Every tenant-owned table has tenant_id uuid NOT NULL and RLS enabled.
--   * Money is stored as *_minor bigint (fils/cents) + currency char(3).
--     Never float. Never a bare "price" column.
--   * Timestamps are timestamptz, always UTC. Tenant-local display is a UI concern.
--   * Constrained string sets use text + CHECK, not enum types: adding or removing
--     a value is one DDL statement instead of a type rewrite.
--   * Embeddings are 1024-dim (multilingual model). Changing this is a migration.
-- =============================================================================

create extension if not exists pgcrypto;
create extension if not exists vector;

create schema if not exists app;

-- -----------------------------------------------------------------------------
-- Tenancy helpers
-- -----------------------------------------------------------------------------

-- Backend path: FastAPI connects as role dealerai_app (NOBYPASSRLS) and issues
--   SET LOCAL app.tenant_id = '<uuid>';
-- at the start of every transaction.
-- Browser path: supabase-js sends the user JWT; auth.uid() resolves membership.
-- Both paths go through this one function.
create or replace function app.has_tenant_access(t uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select
    coalesce(nullif(current_setting('app.tenant_id', true), '')::uuid = t, false)
    or exists (
      select 1 from public.memberships m
      where m.tenant_id = t and m.user_id = auth.uid()
    );
$$;

create or replace function app.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- =============================================================================
-- CORE
-- =============================================================================

create table tenants (
  id                    uuid primary key default gen_random_uuid(),
  slug                  text not null unique,
  name                  text not null,
  country               char(2) not null default 'AE',
  timezone              text not null default 'Asia/Dubai',
  currency              char(3) not null default 'AED',
  locales               text[] not null default '{en,ar}',
  plan                  text not null default 'starter'
                          check (plan in ('starter','growth','scale')),
  autonomy_mode         text not null default 'copilot'
                          check (autonomy_mode in ('copilot','assisted','autopilot')),
  -- numeric autonomy limits; see docs/02-agent-architecture.md § 5
  autonomy_rules        jsonb not null default '{}'::jsonb,
  monthly_ai_budget_usd numeric(10,2) not null default 150,
  status                text not null default 'active'
                          check (status in ('active','paused','churned')),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create table profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  full_name   text,
  email       text,
  avatar_url  text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table memberships (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  role        text not null default 'marketer'
                check (role in ('owner','admin','marketer','sales','viewer')),
  created_at  timestamptz not null default now(),
  unique (tenant_id, user_id)
);
create index on memberships (user_id);

create table audit_log (
  id           bigserial primary key,
  tenant_id    uuid not null references tenants(id) on delete cascade,
  actor_type   text not null check (actor_type in ('user','agent','system','webhook')),
  actor_id     text,
  action       text not null,
  entity_type  text,
  entity_id    uuid,
  before       jsonb,
  after        jsonb,
  meta         jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);
create index on audit_log (tenant_id, created_at desc);
create index on audit_log (tenant_id, entity_type, entity_id);

-- =============================================================================
-- BRAND BRAIN
-- =============================================================================

create table brand_profiles (
  tenant_id             uuid primary key references tenants(id) on delete cascade,
  legal_name            text,
  display_name          text,
  -- {"primary":"#0A2540","secondary":"#C8A15A","accent":"#E5484D","bg":"#FFFFFF","text":"#0A0A0A"}
  colors                jsonb not null default '{}'::jsonb,
  -- {"heading":{"family":"Inter","weight":700},"body":{...},"arabic":{"family":"IBM Plex Sans Arabic"}}
  typography            jsonb not null default '{}'::jsonb,
  logo_asset_id         uuid,
  logo_rules            jsonb not null default '{}'::jsonb,
  -- {"voice":"confident","person":"we","emoji":"sparse","formality":"medium"}
  tone                  jsonb not null default '{}'::jsonb,
  cta_styles            jsonb not null default '[]'::jsonb,
  hashtag_rules         jsonb not null default '{}'::jsonb,
  forbidden_terms       text[] not null default '{}',
  -- {"AE":"Prices exclude registration...","DZ":"..."}
  required_disclaimers  jsonb not null default '{}'::jsonb,
  photography_style     text,
  usps                  text[] not null default '{}',
  target_markets        text[] not null default '{AE}',
  buyer_personas        jsonb not null default '[]'::jsonb,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create table brand_assets (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  kind          text not null check (kind in
                  ('logo','logo_mono','logo_dark','font','watermark','audio','other')),
  storage_path  text not null,
  mime          text,
  meta          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index on brand_assets (tenant_id, kind);

alter table brand_profiles
  add constraint brand_profiles_logo_fk
  foreign key (logo_asset_id) references brand_assets(id) on delete set null;

-- tenant_id NULL = a global template available to every tenant.
create table creative_templates (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid references tenants(id) on delete cascade,
  template_key   text not null,
  name           text not null,
  kind           text not null check (kind in
                   ('hero','offer','specs','comparison','feature','educational','story','carousel')),
  aspect_ratios  text[] not null default '{1:1,4:5,9:16}',
  -- declared CSS custom properties the compositor must be given
  slots          jsonb not null default '{}'::jsonb,
  version        int not null default 1,
  is_active      boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique nulls not distinct (tenant_id, template_key, version)
);

-- =============================================================================
-- VEHICLE INTELLIGENCE
-- =============================================================================

create table vehicles (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  stock_number     text,
  vin              text,
  make             text not null,
  model            text not null,
  trim             text,
  model_year       int check (model_year between 1950 and 2100),
  body_type        text,
  vehicle_condition text not null default 'new'
                     check (vehicle_condition in ('new','used','certified')),
  mileage_km       int not null default 0,
  price_minor      bigint check (price_minor >= 0),
  -- discount floor. NEVER exposed to a customer or to a customer-facing agent.
  min_price_minor  bigint check (min_price_minor >= 0),
  currency         char(3) not null default 'AED',
  engine           text,
  power_hp         int,
  torque_nm        int,
  transmission     text,
  drivetrain       text,
  fuel             text,
  exterior_color   text,
  interior_color   text,
  seats            int,
  specs            jsonb not null default '{}'::jsonb,
  features         text[] not null default '{}',
  status           text not null default 'available'
                     check (status in ('draft','available','reserved','sold','archived')),
  target_markets   text[] not null default '{AE}',
  steering         text not null default 'lhd' check (steering in ('lhd','rhd')),
  location         text,
  listed_at        timestamptz not null default now(),
  sold_at          timestamptz,
  source           text not null default 'manual',
  external_id      text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create unique index vehicles_stock_uq on vehicles (tenant_id, stock_number)
  where stock_number is not null;
create unique index vehicles_vin_uq on vehicles (tenant_id, vin) where vin is not null;
create index on vehicles (tenant_id, status, listed_at);
create index on vehicles (tenant_id, make, model);

create table vehicle_media (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  vehicle_id    uuid not null references vehicles(id) on delete cascade,
  kind          text not null default 'photo' check (kind in ('photo','video','document')),
  storage_path  text not null,
  mime          text,
  width         int,
  height        int,
  bytes         bigint,
  angle         text not null default 'unknown' check (angle in
                  ('front','front_three_quarter','side','rear_three_quarter','rear',
                   'interior_front','interior_rear','dashboard','detail','engine',
                   'wheel','unknown')),
  quality_score numeric(3,2) check (quality_score between 0 and 1),
  is_hero       boolean not null default false,
  -- {"blur":0.08,"exposure":"ok","clutter":false,"rejected_reason":null}
  qa            jsonb not null default '{}'::jsonb,
  sort_order    int not null default 0,
  created_at    timestamptz not null default now()
);
create index on vehicle_media (tenant_id, vehicle_id, sort_order);

create table vehicle_price_history (
  id           bigserial primary key,
  tenant_id    uuid not null references tenants(id) on delete cascade,
  vehicle_id   uuid not null references vehicles(id) on delete cascade,
  price_minor  bigint not null,
  currency     char(3) not null default 'AED',
  reason       text,
  actor_type   text,
  actor_id     text,
  created_at   timestamptz not null default now()
);
create index on vehicle_price_history (tenant_id, vehicle_id, created_at desc);

-- =============================================================================
-- CHANNELS (connected platform accounts)
-- =============================================================================

create table channels (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             uuid not null references tenants(id) on delete cascade,
  platform              text not null check (platform in
                          ('instagram','facebook','whatsapp','tiktok',
                           'meta_ads','google_ads','website','email')),
  external_id           text not null,
  handle                text,
  display_name          text,
  -- envelope-encrypted at the application layer. Never a plaintext token.
  credentials           jsonb not null default '{}'::jsonb,
  scopes                text[] not null default '{}',
  status                text not null default 'connected'
                          check (status in ('connected','expired','revoked','error')),
  last_health_check_at  timestamptz,
  health                jsonb not null default '{}'::jsonb,
  connected_by          uuid references auth.users(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (tenant_id, platform, external_id)
);

-- =============================================================================
-- AGENT RUNTIME
-- (defined before content/inbox so those tables can reference run_id)
-- =============================================================================

create table agent_runs (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants(id) on delete cascade,
  trigger_type   text not null check (trigger_type in ('user','schedule','event','webhook')),
  triggered_by   uuid references auth.users(id),
  goal           text,
  goal_input     jsonb not null default '{}'::jsonb,
  plan           jsonb,
  status         text not null default 'planning' check (status in
                   ('planning','running','waiting_approval','completed','partial','failed','cancelled')),
  autonomy       text not null check (autonomy in ('copilot','assisted','autopilot')),
  cost_usd       numeric(12,4) not null default 0,
  summary        text,
  error          text,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  created_at     timestamptz not null default now()
);
create index on agent_runs (tenant_id, created_at desc);
create index on agent_runs (tenant_id, status);

create table agent_tasks (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id) on delete cascade,
  run_id       uuid not null references agent_runs(id) on delete cascade,
  task_key     text not null,
  agent        text not null,
  depends_on   text[] not null default '{}',
  input        jsonb not null default '{}'::jsonb,
  output       jsonb,
  status       text not null default 'pending' check (status in
                 ('pending','ready','running','waiting_approval','completed','skipped','failed')),
  attempts     int not null default 0,
  error        text,
  cost_usd     numeric(12,4) not null default 0,
  started_at   timestamptz,
  finished_at  timestamptz,
  created_at   timestamptz not null default now(),
  unique (run_id, task_key)
);
create index on agent_tasks (tenant_id, status);

create table agent_traces (
  id                 bigserial primary key,
  tenant_id          uuid not null references tenants(id) on delete cascade,
  run_id             uuid references agent_runs(id) on delete cascade,
  task_id            uuid references agent_tasks(id) on delete cascade,
  kind               text not null check (kind in ('model','tool','guard','connector')),
  name               text not null,
  model              text,
  input_tokens       int,
  output_tokens      int,
  cache_read_tokens  int,
  cache_write_tokens int,
  cost_usd           numeric(12,6),
  latency_ms         int,
  status             text,
  error              text,
  -- truncated arguments / result. Never full customer PII.
  payload            jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now()
);
create index on agent_traces (tenant_id, created_at desc);
create index on agent_traces (run_id);

create table approvals (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  run_id        uuid references agent_runs(id) on delete cascade,
  task_id       uuid references agent_tasks(id) on delete cascade,
  kind          text not null,
  entity_type   text,
  entity_id     uuid,
  summary       text not null,
  payload       jsonb not null default '{}'::jsonb,
  status        text not null default 'pending'
                  check (status in ('pending','approved','rejected','expired')),
  decided_by    uuid references auth.users(id),
  decided_at    timestamptz,
  decision_note text,
  expires_at    timestamptz,
  created_at    timestamptz not null default now()
);
create index on approvals (tenant_id, status, created_at desc);

-- The queue, the outbox, and the audit trail of intent, in one table.
-- Claimed with FOR UPDATE SKIP LOCKED. See docs/01-system-architecture.md § 3.
create table events (
  id            bigserial primary key,
  tenant_id     uuid references tenants(id) on delete cascade,
  event_type    text not null,
  payload       jsonb not null default '{}'::jsonb,
  dedupe_key    text,
  priority      int not null default 0,
  status        text not null default 'pending'
                  check (status in ('pending','processing','done','failed')),
  attempts      int not null default 0,
  max_attempts  int not null default 5,
  run_after     timestamptz not null default now(),
  locked_at     timestamptz,
  locked_by     text,
  error         text,
  dead_letter   boolean not null default false,
  created_at    timestamptz not null default now(),
  processed_at  timestamptz
);
create index events_claim_idx on events (run_after, priority desc, id)
  where status = 'pending';
create unique index events_dedupe_idx on events (tenant_id, event_type, dedupe_key)
  where dedupe_key is not null and status in ('pending','processing');
create index events_reaper_idx on events (locked_at) where status = 'processing';

-- Raw inbound webhooks, persisted before parsing. tenant_id is filled in after
-- the payload is resolved to a channel, so it is nullable here.
create table webhook_deliveries (
  id            bigserial primary key,
  tenant_id     uuid references tenants(id) on delete set null,
  platform      text not null,
  signature_ok  boolean not null,
  headers       jsonb not null default '{}'::jsonb,
  body          jsonb not null default '{}'::jsonb,
  event_id      bigint references events(id) on delete set null,
  received_at   timestamptz not null default now()
);
create index on webhook_deliveries (platform, received_at desc);

-- =============================================================================
-- CONTENT FACTORY
-- =============================================================================

create table content_items (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants(id) on delete cascade,
  vehicle_id        uuid references vehicles(id) on delete set null,
  run_id            uuid references agent_runs(id) on delete set null,
  kind              text not null check (kind in
                      ('post','story','reel','carousel','ad_creative')),
  concept           text,
  brief             jsonb not null default '{}'::jsonb,
  status            text not null default 'draft' check (status in
                      ('draft','rendering','pending_approval','approved','scheduled',
                       'publishing','published','rejected','failed','archived')),
  scheduled_at      timestamptz,
  published_at      timestamptz,
  approved_by       uuid references auth.users(id),
  approved_at       timestamptz,
  rejection_reason  text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index on content_items (tenant_id, status, scheduled_at);
create index on content_items (tenant_id, vehicle_id);

create table content_copy (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  content_item_id  uuid not null references content_items(id) on delete cascade,
  locale           text not null,
  hook             text,
  caption          text,
  cta              text,
  hashtags         text[] not null default '{}',
  alt_text         text,
  edited_by_human  boolean not null default false,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (content_item_id, locale)
);

create table content_assets (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  content_item_id  uuid not null references content_items(id) on delete cascade,
  aspect_ratio     text not null check (aspect_ratio in ('1:1','4:5','9:16','16:9')),
  storage_path     text not null,
  mime             text,
  width            int,
  height           int,
  bytes            bigint,
  duration_ms      int,
  template_id      uuid references creative_templates(id) on delete set null,
  render_meta      jsonb not null default '{}'::jsonb,
  sort_order       int not null default 0,
  created_at       timestamptz not null default now()
);
create index on content_assets (tenant_id, content_item_id, sort_order);

create table publications (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  content_item_id  uuid not null references content_items(id) on delete cascade,
  channel_id       uuid not null references channels(id) on delete cascade,
  external_id      text,
  permalink        text,
  status           text not null default 'pending'
                     check (status in ('pending','publishing','published','failed')),
  error            text,
  attempts         int not null default 0,
  published_at     timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (content_item_id, channel_id)
);
create index on publications (tenant_id, status);
create unique index publications_external_uq on publications (channel_id, external_id)
  where external_id is not null;

create table content_metrics (
  id              bigserial primary key,
  tenant_id       uuid not null references tenants(id) on delete cascade,
  publication_id  uuid not null references publications(id) on delete cascade,
  -- "window" is a reserved word; do not rename this back.
  metric_window   text not null check (metric_window in ('1h','24h','7d','30d','lifetime')),
  captured_at     timestamptz not null default now(),
  impressions     bigint not null default 0,
  reach           bigint not null default 0,
  likes           int not null default 0,
  comments        int not null default 0,
  shares          int not null default 0,
  saves           int not null default 0,
  video_views     bigint not null default 0,
  watch_time_ms   bigint not null default 0,
  profile_visits  int not null default 0,
  link_clicks     int not null default 0,
  raw             jsonb not null default '{}'::jsonb,
  unique (publication_id, metric_window, captured_at)
);
create index on content_metrics (tenant_id, captured_at desc);

-- =============================================================================
-- CUSTOMERS, INBOX, CRM
-- =============================================================================

create table contacts (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants(id) on delete cascade,
  full_name      text,
  phone          text,
  email          text,
  locale         text,
  city           text,
  country        char(2),
  source         text,
  -- {"instagram_id":"178...","wa_id":"9715...","facebook_id":"..."}
  external_refs  jsonb not null default '{}'::jsonb,
  tags           text[] not null default '{}',
  -- {"whatsapp_optin_at":"2026-01-01T00:00:00Z","marketing":true}
  consent        jsonb not null default '{}'::jsonb,
  notes          text,
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create unique index contacts_phone_uq on contacts (tenant_id, phone) where phone is not null;
create index on contacts (tenant_id, last_seen_at desc);
create index contacts_external_refs_gin on contacts using gin (external_refs jsonb_path_ops);

create table conversations (
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid not null references tenants(id) on delete cascade,
  contact_id          uuid references contacts(id) on delete set null,
  channel_id          uuid references channels(id) on delete set null,
  surface             text not null check (surface in
                        ('dm','comment','whatsapp','website_chat','email')),
  external_thread_id  text,
  subject_vehicle_id  uuid references vehicles(id) on delete set null,
  -- set when the conversation started as a comment on one of our posts
  content_item_id     uuid references content_items(id) on delete set null,
  status              text not null default 'open' check (status in
                        ('open','waiting_customer','escalated','closed','spam')),
  assigned_to         uuid references auth.users(id),
  -- true once a human takes over; the AI stops replying on this thread
  ai_paused           boolean not null default false,
  last_message_at     timestamptz,
  last_inbound_at     timestamptz,
  last_outbound_at    timestamptz,
  -- WhatsApp 24h customer service window. Outside it, templates only.
  wa_window_expires_at timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (tenant_id, channel_id, external_thread_id)
);
create index on conversations (tenant_id, status, last_message_at desc);
create index on conversations (tenant_id, contact_id);

create table messages (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  direction        text not null check (direction in ('in','out')),
  sender           text not null check (sender in ('customer','agent','human','system')),
  body             text,
  media            jsonb not null default '[]'::jsonb,
  external_id      text,
  intent           text,
  sentiment        text,
  language         text,
  is_spam          boolean not null default false,
  confidence       numeric(3,2),
  run_id           uuid references agent_runs(id) on delete set null,
  approved_by      uuid references auth.users(id),
  status           text not null default 'sent' check (status in
                     ('draft','pending_approval','queued','sent','delivered','read','failed')),
  error            text,
  created_at       timestamptz not null default now()
);
create index on messages (tenant_id, conversation_id, created_at);
create unique index messages_external_uq on messages (conversation_id, external_id)
  where external_id is not null;

create table leads (
  id                      uuid primary key default gen_random_uuid(),
  tenant_id               uuid not null references tenants(id) on delete cascade,
  contact_id              uuid not null references contacts(id) on delete cascade,
  conversation_id         uuid references conversations(id) on delete set null,
  vehicle_id              uuid references vehicles(id) on delete set null,
  source                  text,
  source_content_item_id  uuid references content_items(id) on delete set null,
  budget_minor            bigint,
  currency                char(3) not null default 'AED',
  intent_band             text check (intent_band in ('hot','warm','cold')),
  score                   int check (score between 0 and 100),
  score_reasons           jsonb not null default '[]'::jsonb,
  stage                   text not null default 'new' check (stage in
                            ('new','contacted','qualified','appointment','negotiation','won','lost')),
  lost_reason             text,
  owner_id                uuid references auth.users(id),
  next_action_at          timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create index on leads (tenant_id, stage, created_at desc);
create index on leads (tenant_id, next_action_at) where stage not in ('won','lost');

create table activities (
  id          bigserial primary key,
  tenant_id   uuid not null references tenants(id) on delete cascade,
  lead_id     uuid references leads(id) on delete cascade,
  contact_id  uuid references contacts(id) on delete cascade,
  kind        text not null check (kind in
                ('note','call','message','appointment','visit','offer_sent',
                 'test_drive','follow_up','stage_change')),
  body        text,
  meta        jsonb not null default '{}'::jsonb,
  occurs_at   timestamptz not null default now(),
  actor_type  text,
  actor_id    text,
  created_at  timestamptz not null default now()
);
create index on activities (tenant_id, lead_id, occurs_at desc);
create index on activities (tenant_id, kind, occurs_at desc);

create table deals (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  lead_id       uuid references leads(id) on delete set null,
  vehicle_id    uuid references vehicles(id) on delete set null,
  amount_minor  bigint not null check (amount_minor >= 0),
  currency      char(3) not null default 'AED',
  status        text not null default 'won'
                  check (status in ('won','cancelled','refunded')),
  -- {"first_touch":"content_item:uuid","last_touch":"campaign:uuid"}
  attribution   jsonb not null default '{}'::jsonb,
  closed_at     timestamptz not null default now(),
  closed_by     uuid references auth.users(id),
  created_at    timestamptz not null default now()
);
create index on deals (tenant_id, closed_at desc);

-- =============================================================================
-- MEMORY (see docs/04-memory-architecture.md)
-- =============================================================================

create table documents (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  kind          text not null check (kind in
                  ('brand_guide','policy','export_policy','faq','spec_sheet',
                   'price_list','competitor','market_report','transcript','other')),
  title         text,
  source        text,
  storage_path  text,
  uri           text,
  content       text,
  meta          jsonb not null default '{}'::jsonb,
  status        text not null default 'pending'
                  check (status in ('pending','processing','ready','failed')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index on documents (tenant_id, kind, status);

create table doc_chunks (
  id           bigserial primary key,
  tenant_id    uuid not null references tenants(id) on delete cascade,
  document_id  uuid not null references documents(id) on delete cascade,
  chunk_index  int not null,
  content      text not null,
  locale       text,
  embedding    vector(1024),
  meta         jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  unique (document_id, chunk_index)
);
create index doc_chunks_tenant_idx on doc_chunks (tenant_id);
create index doc_chunks_embedding_idx on doc_chunks
  using hnsw (embedding vector_cosine_ops);

-- Learned facts. One statement per row, with the evidence that produced it.
create table memories (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  scope           text not null check (scope in
                    ('brand','customer','content','sales','ads','market')),
  subject_type    text,
  subject_id      uuid,
  statement       text not null,
  evidence        jsonb not null default '{}'::jsonb,
  confidence      numeric(3,2) not null default 0.5 check (confidence between 0 and 1),
  sample_size     int,
  embedding       vector(1024),
  source_run_id   uuid references agent_runs(id) on delete set null,
  valid_from      timestamptz not null default now(),
  valid_until     timestamptz,
  superseded_by   uuid references memories(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index on memories (tenant_id, scope, subject_type, subject_id);
create index memories_embedding_idx on memories using hnsw (embedding vector_cosine_ops);
create index memories_active_idx on memories (tenant_id, scope)
  where superseded_by is null and valid_until is null;

-- Versioned, human-approved rules. The output of the Learning Agent.
create table playbooks (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants(id) on delete cascade,
  version              int not null,
  rules                jsonb not null default '[]'::jsonb,
  changelog            text,
  status               text not null default 'draft'
                         check (status in ('draft','proposed','active','superseded')),
  proposed_by_run_id   uuid references agent_runs(id) on delete set null,
  approved_by          uuid references auth.users(id),
  approved_at          timestamptz,
  created_at           timestamptz not null default now(),
  unique (tenant_id, version)
);
create unique index playbooks_one_active on playbooks (tenant_id) where status = 'active';

-- =============================================================================
-- VIEWS
-- security_invoker = true is mandatory: without it a view runs as its owner and
-- silently bypasses RLS.
-- =============================================================================

create view v_vehicle_stock with (security_invoker = true) as
select
  v.*,
  (current_date - v.listed_at::date)                            as days_in_stock,
  (select count(*) from content_items c
    where c.vehicle_id = v.id and c.status = 'published')        as published_content_count,
  (select max(c.published_at) from content_items c
    where c.vehicle_id = v.id and c.status = 'published')        as last_content_at
from vehicles v;

create view v_lead_funnel with (security_invoker = true) as
select
  l.tenant_id,
  date_trunc('day', l.created_at)                                as day,
  count(*)                                                       as leads,
  count(*) filter (where l.intent_band = 'hot')                  as hot_leads,
  count(*) filter (where l.stage in ('qualified','appointment','negotiation','won')) as qualified,
  count(*) filter (where l.stage = 'won')                        as won
from leads l
group by 1, 2;

-- =============================================================================
-- TRIGGERS: updated_at
-- =============================================================================

do $$
declare t text;
begin
  foreach t in array array[
    'tenants','profiles','brand_profiles','creative_templates','vehicles','channels',
    'content_items','content_copy','publications','contacts','conversations','leads',
    'documents','memories'
  ]
  loop
    execute format(
      'create trigger %I_touch before update on %I
         for each row execute function app.touch_updated_at()', t, t);
  end loop;
end $$;

-- =============================================================================
-- ROW LEVEL SECURITY
-- Every tenant table gets the same policy. There are no exceptions and no
-- table-specific variations — a variation is how a leak gets introduced.
-- =============================================================================

do $$
declare t text;
begin
  -- NOTE: 'events' and 'webhook_deliveries' are deliberately absent. See the
  -- "system tables" block below — they are backend-only and RLS on them would
  -- break the worker's claim query.
  foreach t in array array[
    'audit_log','brand_profiles','brand_assets','creative_templates','vehicles',
    'vehicle_media','vehicle_price_history','channels','agent_runs','agent_tasks',
    'agent_traces','approvals','content_items','content_copy',
    'content_assets','publications','content_metrics','contacts','conversations',
    'messages','leads','activities','deals','documents','doc_chunks','memories',
    'playbooks'
  ]
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy tenant_isolation on %I
         using (app.has_tenant_access(tenant_id))
         with check (app.has_tenant_access(tenant_id))', t);
  end loop;
end $$;

-- creative_templates additionally exposes global templates (tenant_id is null).
create policy global_templates_readable on creative_templates
  for select using (tenant_id is null);

-- tenants: readable by members, writable by owner/admin only.
alter table tenants enable row level security;
alter table tenants force row level security;
create policy tenant_self_read on tenants
  for select using (app.has_tenant_access(id));
create policy tenant_self_write on tenants
  for update using (
    exists (select 1 from memberships m
            where m.tenant_id = tenants.id and m.user_id = auth.uid()
              and m.role in ('owner','admin'))
    or coalesce(nullif(current_setting('app.tenant_id', true), '')::uuid = tenants.id, false)
  );

alter table memberships enable row level security;
alter table memberships force row level security;
create policy membership_visible on memberships
  for select using (user_id = auth.uid() or app.has_tenant_access(tenant_id));
create policy membership_managed on memberships
  for all using (
    exists (select 1 from memberships m
            where m.tenant_id = memberships.tenant_id and m.user_id = auth.uid()
              and m.role in ('owner','admin'))
    or coalesce(nullif(current_setting('app.tenant_id', true), '')::uuid = memberships.tenant_id, false)
  );

alter table profiles enable row level security;
alter table profiles force row level security;
create policy profile_self on profiles for all using (id = auth.uid());

-- -----------------------------------------------------------------------------
-- SYSTEM TABLES: events, webhook_deliveries
--
-- These get NO row level security, on purpose, and are isolated by GRANT instead.
--
-- The worker claims events *before* it knows which tenant they belong to — that
-- claim is the one legitimate cross-tenant read in the system. Under RLS it would
-- return zero rows and the queue would silently stop. Likewise a webhook is
-- persisted before its payload has been resolved to a channel, so tenant_id is
-- still null at insert time and any tenant predicate would reject the row.
--
-- They are not user-facing, so no browser role is ever granted access to them.
-- Reachability, not a policy, is the isolation boundary here.
--
-- Discipline this depends on: the worker resolves tenant_id from the claimed
-- event and does all subsequent work inside tenant_session(tenant_id). The claim
-- query is the only statement in the codebase that touches events without a
-- tenant context.
-- -----------------------------------------------------------------------------
-- (the actual REVOKE runs at the bottom of this file, after the blanket GRANTs)

-- =============================================================================
-- ROLES AND GRANTS
--
-- OPS STEP, run once per project with elevated privileges:
--
--   create role dealerai_app login password '<from secret manager>' nobypassrls;
--   grant usage on schema public, app to dealerai_app;
--   grant select, insert, update, delete on all tables in schema public to dealerai_app;
--   grant usage, select on all sequences in schema public to dealerai_app;
--   alter default privileges in schema public
--     grant select, insert, update, delete on tables to dealerai_app;
--
-- The FastAPI service connects as dealerai_app and NEVER as service_role.
-- service_role bypasses RLS and exists only for migrations.
-- =============================================================================

grant usage on schema app to authenticated, anon;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant usage, select on all sequences in schema public to authenticated;

-- Order matters: this must come after the blanket grants above.
-- The system tables are backend-only and are isolated by reachability, not RLS.
revoke all on events, webhook_deliveries from authenticated, anon;
revoke all on sequence events_id_seq, webhook_deliveries_id_seq from authenticated, anon;
