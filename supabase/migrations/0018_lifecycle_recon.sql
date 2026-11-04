-- =============================================================================
-- 0018_lifecycle_recon — Lifecycle L3: getting a car ready to sell, inside a
-- budget. See docs/lifecycle/README.md § L3.
-- =============================================================================

-- The dealer's reconditioning rules: the budget a new car starts with, and a
-- rate card per operation that turns "two panels to paint" into an estimate.
-- Empty means no default budget and no rates — every estimate is typed, and
-- every repair asks for approval until somebody sets a budget.
alter table tenants
  add column recon_settings jsonb not null default '{}'::jsonb;

-- =============================================================================
-- ONE RECONDITIONING RECORD PER CAR
-- The budget is in the dealer's currency, like every sum on the buy side. Null
-- is "nobody set one", and spends like zero: nothing is committed without
-- somebody allowed to decide having said how much.
-- =============================================================================
create table vehicle_recon (
  vehicle_id    uuid primary key references vehicles(id) on delete cascade,
  tenant_id     uuid not null references tenants(id) on delete cascade,
  budget_minor  bigint check (budget_minor >= 0),
  -- When the dealer expects it on the lot, and when it got there.
  ready_by      date,
  ready_at      timestamptz,
  notes         text check (length(notes) <= 2000),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger vehicle_recon_touch before update on vehicle_recon
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- WORK ITEMS
-- proposed → (committed) → approved | awaiting_approval → approved → done.
-- Declined from anywhere before done. An approved item carries an estimate
-- line in vehicle_costs, so the landed cost — and with it tomorrow's price —
-- counts work the dealer has agreed to before the bill arrives; done turns that
-- line into the actual amount.
-- =============================================================================
create table recon_items (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants(id) on delete cascade,
  vehicle_id     uuid not null references vehicles(id) on delete cascade,
  area           text not null check (area in
                   ('exterior','interior','mechanical','tyres_wheels','glass','electrical',
                    'other')),
  operation      text not null check (operation in
                   ('paint_panel','dent_repair','scratch_polish','replace_part','tyre',
                    'windscreen','wheel_refurb','interior_clean','upholstery','mechanical',
                    'service','detailing','other')),
  quantity       int not null default 1 check (quantity between 1 and 50),
  description    text not null check (length(description) between 1 and 300),
  severity       text check (severity in ('minor','moderate','major')),
  vendor         text check (length(vendor) <= 200),
  estimate_minor bigint check (estimate_minor >= 0),
  actual_minor   bigint check (actual_minor >= 0),
  status         text not null default 'proposed' check (status in
                   ('proposed','awaiting_approval','approved','done','declined')),
  source         text not null default 'manual' check (source in ('manual','photo')),
  -- The inspection photo a finding was read from, in storage. Same reasoning
  -- as an invoice: kept on the line, not in the tenant-wide `documents`.
  photo_path     text check (length(photo_path) <= 500),
  cost_id        uuid references vehicle_costs(id) on delete set null,
  approval_id    uuid references approvals(id) on delete set null,
  created_by     uuid references auth.users(id) on delete set null,
  done_at        timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  check (status <> 'done' or actual_minor is not null),
  check (status not in ('awaiting_approval','approved','done') or estimate_minor is not null)
);
create index on recon_items (tenant_id, vehicle_id);
-- "What did the last few paint jobs cost us?" — the estimate from history.
create index on recon_items (tenant_id, operation, done_at desc) where status = 'done';

create trigger recon_items_touch before update on recon_items
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- RLS — tenant, and cleared for the buy side: an estimate is what the dealer
-- will pay, and that is the number a salesperson must not know.
-- =============================================================================
alter table vehicle_recon enable row level security;
alter table vehicle_recon force row level security;
create policy buy_side on vehicle_recon
  using (app.has_tenant_access(tenant_id) and app.buy_side_cleared())
  with check (app.has_tenant_access(tenant_id) and app.buy_side_cleared());

alter table recon_items enable row level security;
alter table recon_items force row level security;
create policy buy_side on recon_items
  using (app.has_tenant_access(tenant_id) and app.buy_side_cleared())
  with check (app.has_tenant_access(tenant_id) and app.buy_side_cleared());

revoke all on vehicle_recon, recon_items from anon, authenticated;
grant select, insert, update, delete on vehicle_recon, recon_items to dealerai_app;

-- An approval to spend over a repair budget names the amount — so it sits
-- behind the same wall. Restrictive: it narrows tenant_isolation, never widens
-- it. Every other kind of approval is unaffected.
create policy buy_side_kinds on approvals as restrictive
  using (kind <> 'recon_over_budget' or app.buy_side_cleared())
  with check (kind <> 'recon_over_budget' or app.buy_side_cleared());

-- Two things worth telling somebody about:
--   recon_approval — a repair would take a car over its budget, and an
--                    approval is waiting for whoever may decide;
--   recon_overrun  — a repair came in above its estimate and the car is now
--                    over budget: the money is spent, and the owner should know.
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready', 'task_due',
   'price_proposed', 'content_stale',
   'recon_approval', 'recon_overrun'));
