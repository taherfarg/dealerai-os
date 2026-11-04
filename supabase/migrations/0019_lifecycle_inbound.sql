-- =============================================================================
-- 0019_lifecycle_inbound — Lifecycle L4: getting a bought car to the lot, with
-- its papers and its fees. See docs/lifecycle/README.md § L4.
-- =============================================================================

-- =============================================================================
-- THE JOURNEY — one per car
-- Where a car is, and when it should be here, is not the buy side: the
-- salesperson telling a customer "it lands on the 20th" needs it. So these two
-- tables are tenant-wide, like the vehicle they belong to.
-- =============================================================================
create table vehicle_inbound (
  vehicle_id         uuid primary key references vehicles(id) on delete cascade,
  tenant_id          uuid not null references tenants(id) on delete cascade,
  -- An import crosses a border (a US auction car to Jebel Ali); a local car is
  -- collected. The route decides which milestones and papers it needs.
  route              text not null check (route in ('import','local')),
  origin_country     char(2),
  carrier            text check (length(carrier) <= 120),
  -- Bill of lading or booking number.
  reference          text check (length(reference) <= 120),
  vessel             text check (length(vessel) <= 120),
  container          text check (length(container) <= 40),
  port_of_loading    text check (length(port_of_loading) <= 120),
  port_of_discharge  text check (length(port_of_discharge) <= 120),
  eta                date,
  arrived_at         timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create trigger vehicle_inbound_touch before update on vehicle_inbound
  for each row execute function app.touch_updated_at();

create table inbound_milestones (
  vehicle_id   uuid not null references vehicles(id) on delete cascade,
  tenant_id    uuid not null references tenants(id) on delete cascade,
  code         text not null check (code in
                 ('purchased','paid','picked_up','at_origin_port','departed','arrived_port',
                  'customs_cleared','delivered','collected','registered')),
  position     int not null,
  -- Skipped: an export car is never registered here.
  status       text not null default 'pending' check (status in ('pending','done','skipped')),
  expected_on  date,
  done_on      date,
  note         text check (length(note) <= 500),
  updated_at   timestamptz not null default now(),
  primary key (vehicle_id, code),
  check (status <> 'done' or done_on is not null)
);
create index on inbound_milestones (tenant_id, status);

create trigger inbound_milestones_touch before update on inbound_milestones
  for each row execute function app.touch_updated_at();

alter table vehicle_inbound enable row level security;
alter table vehicle_inbound force row level security;
create policy tenant_isolation on vehicle_inbound
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));

alter table inbound_milestones enable row level security;
alter table inbound_milestones force row level security;
create policy tenant_isolation on inbound_milestones
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));

-- =============================================================================
-- THE PAPERS — buy side
-- A bill of sale is what the dealer paid, printed. The checklist and the files
-- sit behind the same wall as the cost ledger.
-- =============================================================================
create table inbound_documents (
  vehicle_id     uuid not null references vehicles(id) on delete cascade,
  tenant_id      uuid not null references tenants(id) on delete cascade,
  code           text not null check (code in
                   ('bill_of_sale','title','bill_of_lading','customs_declaration',
                    'customs_certificate','registration_card')),
  position       int not null,
  status         text not null default 'missing' check (status in
                   ('missing','received','not_needed')),
  -- In storage, under {tenant}/inbound/ or {tenant}/invoices/ when the paper
  -- was also read for its fees. Kept off `documents` for the reason invoices are.
  document_path  text check (length(document_path) <= 500),
  received_on    date,
  updated_at     timestamptz not null default now(),
  primary key (vehicle_id, code)
);

create trigger inbound_documents_touch before update on inbound_documents
  for each row execute function app.touch_updated_at();

alter table inbound_documents enable row level security;
alter table inbound_documents force row level security;
create policy buy_side on inbound_documents
  using (app.has_tenant_access(tenant_id) and app.buy_side_cleared())
  with check (app.has_tenant_access(tenant_id) and app.buy_side_cleared());

revoke all on vehicle_inbound, inbound_milestones, inbound_documents from anon, authenticated;
grant select, insert, update, delete on vehicle_inbound, inbound_milestones, inbound_documents
  to dealerai_app;

-- Two things worth telling somebody about:
--   inbound_arrived — a car reached the lot, with what is still missing from its
--                     papers and its landed cost;
--   inbound_late    — cars past their ETA, once a morning.
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready', 'task_due',
   'price_proposed', 'content_stale',
   'recon_approval', 'recon_overrun',
   'inbound_arrived', 'inbound_late'));
