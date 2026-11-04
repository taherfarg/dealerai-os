-- =============================================================================
-- 0020_lifecycle_deals — Lifecycle L6: the deal desk. An order for a car, the
-- invoice it is priced on, and the payments that reserve and then sell it.
-- See docs/lifecycle/README.md § L6.
-- =============================================================================

-- =============================================================================
-- ORDERS
-- Quoted to a buyer, reserved by a deposit, completed when it is paid for.
-- Several buyers can be quoted the same car; only one can hold it.
-- =============================================================================
create table sale_orders (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants(id) on delete cascade,
  vehicle_id           uuid not null references vehicles(id) on delete cascade,
  lead_id              uuid references leads(id) on delete set null,
  contact_id           uuid references contacts(id) on delete set null,
  buyer_name           text not null check (length(buyer_name) between 1 and 200),
  purchase_type        text not null check (purchase_type in ('local','export')),
  -- Where an export car is going: a two-letter country code.
  destination          char(2),
  -- The dealer's currency; every charge is in it. A payment may not be.
  currency             char(3) not null,
  deposit_minor        bigint not null check (deposit_minor >= 0),
  status               text not null default 'quoted' check (status in
                         ('quoted','reserved','completed','cancelled')),
  -- A price under the car's floor is cleared only by an owner or admin, and
  -- only at the price they saw: change it and it needs clearing again.
  approved_price_minor bigint,
  approval_id          uuid references approvals(id) on delete set null,
  reserved_at          timestamptz,
  completed_at         timestamptz,
  cancelled_at         timestamptz,
  cancel_reason        text check (length(cancel_reason) <= 500),
  created_by           uuid references auth.users(id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  check (purchase_type = 'local' or destination is not null)
);
create index on sale_orders (tenant_id, status, created_at desc);
create index on sale_orders (vehicle_id);
-- One buyer holds a car at a time. Postgres says so, not a check in code that
-- two clicks at once could both pass.
create unique index sale_orders_one_reservation on sale_orders (vehicle_id)
  where status in ('reserved','completed');

create trigger sale_orders_touch before update on sale_orders
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- THE INVOICE — price, fees, freight and duties, each its own line
-- =============================================================================
create table sale_charges (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  order_id      uuid not null references sale_orders(id) on delete cascade,
  kind          text not null check (kind in ('vehicle','fee','freight','duties','other')),
  description   text check (length(description) <= 300),
  amount_minor  bigint not null check (amount_minor >= 0),
  position      int not null
);
create index on sale_charges (order_id);
create unique index sale_charges_one_vehicle on sale_charges (order_id) where kind = 'vehicle';

-- =============================================================================
-- PAYMENTS — as received, in whatever currency, counted in the dealer's
-- =============================================================================
create table sale_payments (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants(id) on delete cascade,
  order_id             uuid not null references sale_orders(id) on delete cascade,
  stage                text not null check (stage in ('deposit','balance','logistics')),
  amount_minor         bigint not null check (amount_minor > 0),
  currency             char(3) not null,
  fx_rate              numeric(18,8) not null check (fx_rate > 0),
  amount_tenant_minor  bigint not null check (amount_tenant_minor > 0),
  received_on          date not null,
  method               text not null check (method in ('bank_transfer','cash','card','other')),
  reference            text check (length(reference) <= 120),
  -- A transfer receipt, in storage under {tenant}/payments/.
  document_path        text check (length(document_path) <= 500),
  source               text not null default 'manual' check (source in ('manual','document')),
  recorded_by          uuid references auth.users(id) on delete set null,
  created_at           timestamptz not null default now()
);
create index on sale_payments (order_id);

-- =============================================================================
-- RLS — tenant. An order is what a buyer agreed to pay, not what the dealer
-- paid: the salesperson who made it reads it. The margin on it is computed from
-- the buy side, through the buy-side wall, for those cleared to see it.
-- =============================================================================
alter table sale_orders enable row level security;
alter table sale_orders force row level security;
create policy tenant_isolation on sale_orders
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

alter table sale_charges enable row level security;
alter table sale_charges force row level security;
create policy tenant_isolation on sale_charges
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

alter table sale_payments enable row level security;
alter table sale_payments force row level security;
create policy tenant_isolation on sale_payments
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

revoke all on sale_orders, sale_charges, sale_payments from anon, authenticated;
grant select, insert, update, delete on sale_orders, sale_charges, sale_payments to dealerai_app;

-- Two things worth telling somebody about:
--   price_below_floor  — an order priced under the car's floor waits for an
--                        owner or admin;
--   marketing_stopped  — a car was reserved or sold and published posts still
--                        advertise it, which nothing here can take down.
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready', 'task_due',
   'price_proposed', 'content_stale',
   'recon_approval', 'recon_overrun',
   'inbound_arrived', 'inbound_late',
   'price_below_floor', 'marketing_stopped'));
