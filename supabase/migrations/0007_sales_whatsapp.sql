-- =============================================================================
-- 0007_sales_whatsapp — Sales S1: the WhatsApp channel.
-- See docs/sales/03-whatsapp.md and docs/sales/02-data-model.md § 3.
-- =============================================================================

-- A phone number belongs to one tenant, ever. Webhooks route by it before any
-- tenant context exists, so uniqueness per tenant is not enough.
alter table channels
  add column mode text check (mode in ('cloud_api', 'coexistence')),
  add column account_id text,
  add column sync_state jsonb not null default '{}'::jsonb,
  add column quality_rating text check (quality_rating in ('green', 'yellow', 'red'));

alter table channels drop constraint channels_tenant_id_platform_external_id_key;
alter table channels add constraint channels_platform_external_id_key
  unique (platform, external_id);
create index on channels (platform, account_id);

-- One row shape for every WhatsApp type. `origin` is required: a thread that
-- cannot tell the customer from the phone app from the inbox is not an audit.
alter table messages drop constraint messages_status_check;
alter table messages add constraint messages_status_check check (status in
  ('draft', 'pending_approval', 'queued', 'sending', 'sent', 'delivered', 'read', 'failed'));

alter table messages
  add column kind text not null default 'message'
    check (kind in ('message', 'note', 'event')),
  add column type text not null default 'text'
    check (type in ('text', 'image', 'audio', 'video', 'document', 'location', 'sticker',
                    'template', 'interactive_reply', 'vehicle_card', 'unsupported')),
  add column origin text
    check (origin in ('customer', 'inbox', 'phone_app', 'history', 'system', 'ai')),
  add column author_user_id uuid references auth.users(id) on delete set null,
  add column transcript jsonb,
  add column location jsonb,
  add column template jsonb,
  add column reply_to_id uuid references messages(id) on delete set null,
  add column reactions jsonb not null default '[]'::jsonb,
  add column referral jsonb,
  add column pricing jsonb,
  add column event jsonb,
  add column delivered_at timestamptz,
  add column read_at timestamptz,
  add column locked_at timestamptz,
  add column idempotency_key text;

update messages set origin = case when direction = 'in' then 'customer' else 'inbox' end;
alter table messages alter column origin set not null;

-- {code, message}: Meta's error code and the readable cause the inbox shows.
alter table messages alter column error type jsonb
  using case when error is null then null
             else jsonb_build_object('code', 'unknown', 'message', error) end;

drop index messages_external_uq;
create unique index messages_external_uq on messages (tenant_id, external_id)
  where external_id is not null;
create unique index messages_idempotency_uq on messages (tenant_id, idempotency_key)
  where idempotency_key is not null;

create table message_templates (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  channel_id      uuid not null references channels(id) on delete cascade,
  external_id     text not null,
  name            text not null,
  language        text not null,
  category        text not null check (category in ('marketing', 'utility', 'authentication')),
  status          text not null
                    check (status in ('approved', 'pending', 'rejected', 'paused', 'disabled')),
  components      jsonb not null default '[]'::jsonb,
  body            text not null default '',
  variables       text[] not null default '{}',
  rejected_reason text,
  synced_at       timestamptz not null default now(),
  unique (channel_id, name, language)
);
create index on message_templates (tenant_id, channel_id, status);

alter table message_templates enable row level security;
alter table message_templates force row level security;
create policy tenant_isolation on message_templates
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));

revoke all on message_templates from anon, authenticated;

-- The only pre-tenant lookup: phone-level webhooks route by phone number;
-- account-level webhooks (template status) route by WABA id.
create or replace function app.route_whatsapp(p_phone_number_id text, p_account_id text)
returns table (tenant_id uuid, channel_id uuid)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select c.tenant_id, c.id
  from public.channels c
  where c.platform = 'whatsapp'
    and case when p_phone_number_id is not null then c.external_id = p_phone_number_id
             else c.account_id = p_account_id end
$$;

revoke all on function app.route_whatsapp(text, text) from public;
grant execute on function app.route_whatsapp(text, text) to dealerai_app;
