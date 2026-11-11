-- =============================================================================
-- 0016_lifecycle_acquisition — Lifecycle L1: how a car was bought and what it
-- cost. See docs/lifecycle/README.md § L1.
-- =============================================================================

-- =============================================================================
-- THE BUY SIDE IS NEED-TO-KNOW
-- What a dealer paid for a car is the most sensitive number in the business: a
-- salesperson who can see it negotiates down to it. So the rows are invisible
-- in Postgres to any person's session that the API has not cleared, the same
-- way tenancy and sales visibility are — a missing WHERE must not be a leak.
--
-- The worker has no person (app.user_id is empty) and sees everything, as it
-- does for every other table: it acts on rows that were already authorised.
-- =============================================================================

create or replace function app.buy_side_cleared()
returns boolean
language sql
stable
set search_path = public, pg_temp
as $$
  select coalesce(current_setting('app.buy_side', true), '') = 'on'
      or app.current_user_id() is null
$$;

revoke all on function app.buy_side_cleared() from public;
grant execute on function app.buy_side_cleared() to dealerai_app;

-- =============================================================================
-- ACQUISITIONS — one per vehicle
-- Where the car came from and when. The price is not here: it is the
-- 'purchase' line in vehicle_costs, so there is one ledger and one sum.
-- =============================================================================
create table vehicle_acquisitions (
  vehicle_id    uuid primary key references vehicles(id) on delete cascade,
  tenant_id     uuid not null references tenants(id) on delete cascade,
  source        text not null check (source in
                  ('auction','trade_in','private','dealer','import','other')),
  -- An auction house or a dealer. A private seller is a person, and belongs in
  -- contacts once the deal desk links trade-ins to customers (L6).
  seller        text check (length(seller) <= 200),
  -- Lot number, stock number at the source, or the invoice number.
  reference     text check (length(reference) <= 120),
  purchased_at  date not null,
  notes         text check (length(notes) <= 2000),
  created_by    uuid references auth.users(id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index on vehicle_acquisitions (tenant_id, purchased_at desc);

create trigger vehicle_acquisitions_touch before update on vehicle_acquisitions
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- THE COST LEDGER
-- Amounts are kept as the document says them, in its currency, and converted
-- once into the dealer's currency at a rate somebody supplied. Summing a column
-- of mixed currencies is the bug this layout makes impossible: only
-- amount_tenant_minor is ever added up.
-- =============================================================================
create table vehicle_costs (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants(id) on delete cascade,
  vehicle_id           uuid not null references vehicles(id) on delete cascade,
  category             text not null check (category in
                         ('purchase','auction_fee','transport','shipping','customs',
                          'registration','inspection','repair','parts','detailing',
                          'photography','storage','commission','other')),
  description          text check (length(description) <= 300),
  vendor               text check (length(vendor) <= 200),
  amount_minor         bigint not null check (amount_minor >= 0),
  currency             char(3) not null,
  -- Units of the dealer's currency per one unit of `currency`. Exactly 1 when
  -- they are the same; supplied by a person or printed on the document
  -- otherwise. Never a model's memory of an exchange rate.
  fx_rate              numeric(18,8) not null check (fx_rate > 0),
  amount_tenant_minor  bigint not null check (amount_tenant_minor >= 0),
  incurred_at          date not null,
  status               text not null default 'actual' check (status in ('estimate','actual')),
  source               text not null default 'manual' check (source in ('manual','document')),
  -- The invoice this line was read from, in storage. Deliberately not a row in
  -- `documents`: that table is tenant-wide and feeds the copilot's knowledge
  -- pipeline, so a workshop bill there would put the buy side within reach of
  -- every salesperson and of a draft reply to a customer.
  document_path        text check (length(document_path) <= 500),
  created_by           uuid references auth.users(id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index on vehicle_costs (tenant_id, vehicle_id);
create index on vehicle_costs (tenant_id, incurred_at desc);

create trigger vehicle_costs_touch before update on vehicle_costs
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- RLS — tenant, and cleared for the buy side
-- =============================================================================
alter table vehicle_acquisitions enable row level security;
alter table vehicle_acquisitions force row level security;
create policy buy_side on vehicle_acquisitions
  using (app.has_tenant_access(tenant_id) and app.buy_side_cleared())
  with check (app.has_tenant_access(tenant_id) and app.buy_side_cleared());

alter table vehicle_costs enable row level security;
alter table vehicle_costs force row level security;
create policy buy_side on vehicle_costs
  using (app.has_tenant_access(tenant_id) and app.buy_side_cleared())
  with check (app.has_tenant_access(tenant_id) and app.buy_side_cleared());

revoke all on vehicle_acquisitions, vehicle_costs from anon, authenticated;
grant select, insert, update, delete on vehicle_acquisitions, vehicle_costs to dealerai_app;

-- =============================================================================
-- UNIT ECONOMICS
-- security_invoker, so the buy-side policy applies through the view: an
-- uncleared session sees the cars and a cost of nothing — which is why the API
-- never serves this view to one.
-- =============================================================================
create view v_vehicle_economics with (security_invoker = true) as
select
  v.id                                                  as vehicle_id,
  v.tenant_id,
  v.status,
  v.currency,
  v.price_minor,
  v.min_price_minor,
  (current_date - v.listed_at::date)                    as days_in_stock,
  coalesce(c.actual_minor, 0)                           as cost_actual_minor,
  coalesce(c.estimate_minor, 0)                         as cost_estimate_minor,
  coalesce(c.actual_minor, 0) + coalesce(c.estimate_minor, 0) as landed_cost_minor,
  coalesce(c.lines, 0)                                  as cost_lines,
  (a.vehicle_id is not null)                            as has_acquisition
from vehicles v
left join (
  select vehicle_id,
         sum(amount_tenant_minor) filter (where status = 'actual')   as actual_minor,
         sum(amount_tenant_minor) filter (where status = 'estimate') as estimate_minor,
         count(*)                                                    as lines
  from vehicle_costs
  group by vehicle_id
) c on c.vehicle_id = v.id
left join vehicle_acquisitions a on a.vehicle_id = v.id;

grant select on v_vehicle_economics to dealerai_app;
revoke all on v_vehicle_economics from anon, authenticated;
