-- =============================================================================
-- 0021_lifecycle_export — Lifecycle L7: the export file. Pollux's own procedure
-- per destination, the papers each step produces, and the commercial invoice
-- drafted from the record and signed by a person. See docs/lifecycle/README.md
-- § L7 and docs/lifecycle/pollux.md.
-- =============================================================================

-- Who the documents say sold the car: legal name, address, telephone, email,
-- tax registration number, and the prefix of the invoice numbers. Empty means
-- the tenant's name alone, which a commercial invoice can be signed without
-- only if somebody has looked at it — see lifecycle/export.py.
alter table tenants
  add column document_settings jsonb not null default '{}'::jsonb;

-- Who receives the car, where, and how it travels. Asked of the buyer in the
-- first step of every procedure: "recipient information, delivery address".
alter table sale_orders
  add column consignee_name     text check (length(consignee_name) <= 200),
  add column consignee_address  text check (length(consignee_address) <= 500),
  add column consignee_phone    text check (length(consignee_phone) <= 40),
  add column port_of_discharge  text check (length(port_of_discharge) <= 120),
  add column shipping_method    text check (shipping_method in
                                  ('container','shared_container','roro','air')),
  -- The signed commercial invoice: its number, and what it said when it was
  -- signed. A later change to the order does not change a signed document.
  add column invoice_number     text,
  add column invoice            jsonb,
  add column invoice_signed_by  uuid references auth.users(id) on delete set null,
  add column invoice_signed_at  timestamptz;
create unique index sale_orders_invoice_number on sale_orders (tenant_id, invoice_number)
  where invoice_number is not null;

-- =============================================================================
-- THE PROCEDURE — one row per step, in the order the destination needs them
-- =============================================================================
create table order_steps (
  order_id       uuid not null references sale_orders(id) on delete cascade,
  tenant_id      uuid not null references tenants(id) on delete cascade,
  code           text not null check (code in
                   ('customer_documents','assign_vehicle','customs_card','book_shipping',
                    'export_inspection','export_plates','deliver_to_carrier',
                    'export_certificate','bl_draft_confirmed','bl_original',
                    'chamber_certificate','commercial_invoice','file_delivered',
                    'rta_registration','delivered')),
  position       int not null,
  status         text not null default 'pending' check (status in ('pending','done','skipped')),
  done_on        date,
  note           text check (length(note) <= 500),
  -- The paper the step produced, in storage under {tenant}/exports/.
  document_path  text check (length(document_path) <= 500),
  updated_at     timestamptz not null default now(),
  primary key (order_id, code),
  check (status <> 'done' or done_on is not null)
);

create trigger order_steps_touch before update on order_steps
  for each row execute function app.touch_updated_at();

alter table order_steps enable row level security;
alter table order_steps force row level security;
create policy tenant_isolation on order_steps
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

revoke all on order_steps from anon, authenticated;
grant select, insert, update, delete on order_steps to dealerai_app;
