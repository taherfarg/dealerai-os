-- =============================================================================
-- 0006_sales_core — Sales S0: teams, customer identities, ownership, and the
-- settings the visibility policies read. See docs/sales/02-data-model.md.
-- =============================================================================

-- =============================================================================
-- TEAMS
-- =============================================================================
create table teams (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id) on delete cascade,
  name       text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, name)
);

-- A manager manages every team they belong to. No is_manager flag: the role
-- decides, and two sources for one fact drift.
create table team_members (
  tenant_id  uuid not null references tenants(id) on delete cascade,
  team_id    uuid not null references teams(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (team_id, user_id)
);
create index on team_members (tenant_id, user_id);

-- =============================================================================
-- CUSTOMER IDENTITIES
-- One row per way a customer can reach us. The unique index is what makes two
-- simultaneous webhooks from one new customer produce one contact, not two —
-- a jsonb of platform ids cannot enforce that.
-- =============================================================================
create table contact_identities (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  contact_id  uuid not null references contacts(id) on delete cascade,
  kind        text not null check (kind in
                ('whatsapp_user_id','phone','instagram_id','messenger_psid','email')),
  value       text not null,
  is_primary  boolean not null default false,
  verified_at timestamptz,
  created_at  timestamptz not null default now(),
  unique (tenant_id, kind, value),
  -- E.164 only. Voice gives +971…, WhatsApp gives 971…, people type 050…;
  -- normalising at the edge is the difference between one customer and three.
  constraint phone_is_e164 check (kind <> 'phone' or value ~ '^\+[1-9][0-9]{6,14}$')
);
create index on contact_identities (tenant_id, contact_id);
create unique index contact_identities_primary_uq
  on contact_identities (contact_id, kind) where is_primary;

-- Move what contacts held until now, then drop it. Nothing in the application
-- read these columns: the inbox and CRM code does not exist yet.
insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
  select tenant_id, id, 'phone', phone, true from contacts where phone is not null
  on conflict do nothing;
insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
  select tenant_id, id, 'email', lower(email), true from contacts where email is not null
  on conflict do nothing;

drop index if exists contacts_phone_uq;
drop index if exists contacts_external_refs_gin;
alter table contacts
  drop column if exists phone,
  drop column if exists email,
  drop column if exists external_refs,
  add column owner_id uuid references auth.users(id) on delete set null,
  add column team_id uuid references teams(id) on delete set null,
  add column profile jsonb not null default '{}'::jsonb,
  add column profile_updated_at timestamptz;
create index on contacts (tenant_id, owner_id);
create index on contacts (tenant_id, team_id) where owner_id is null;

-- =============================================================================
-- OWNERSHIP AND WAITING STATE
-- owner_id is denormalised onto conversations so a visibility policy reads one
-- row. app.reassign_contact, added with the CRM slice, will be the single writer
-- that keeps them equal, and brings the invariant test with it.
-- =============================================================================
alter table conversations
  add column owner_id uuid references auth.users(id) on delete set null,
  add column team_id uuid references teams(id) on delete set null,
  add column waiting_since timestamptz,
  add column sla_due_at timestamptz,
  add column first_response_at timestamptz,
  add column summary jsonb;
create index on conversations (tenant_id, owner_id);
create index on conversations (tenant_id, team_id, status) where assigned_to is null;
create index on conversations (tenant_id, sla_due_at) where waiting_since is not null;

alter table leads
  add column team_id uuid references teams(id) on delete set null;
create index on leads (tenant_id, owner_id);

-- =============================================================================
-- PEOPLE AND TENANT SETTINGS
-- =============================================================================
alter table memberships drop constraint memberships_role_check;
alter table memberships add constraint memberships_role_check
  check (role in ('owner','admin','manager','marketer','sales','viewer'));
alter table memberships
  add column languages text[] not null default '{}',
  add column accepting_chats boolean not null default true,
  add column last_assigned_at timestamptz,
  add column max_open_conversations int;
create index on memberships (tenant_id, last_assigned_at) where accepting_chats;

-- Read whole, never filtered on: jsonb, per docs/03-database-schema.md § 3.
-- Validated by the SalesSettings model at the application edge.
alter table tenants
  add column sales_settings jsonb not null default '{}'::jsonb;

-- =============================================================================
-- RLS for the new tables: the same loop and the same policy as 0001
-- =============================================================================
do $$
declare t text;
begin
  foreach t in array array['teams','team_members','contact_identities']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy tenant_isolation on %I
         using (app.has_tenant_access(tenant_id))
         with check (app.has_tenant_access(tenant_id))', t);
  end loop;
end $$;

create trigger teams_touch before update on teams
  for each row execute function app.touch_updated_at();
