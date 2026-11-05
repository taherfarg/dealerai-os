-- =============================================================================
-- 0022_lifecycle_numbers — Lifecycle L8: how long the dealer's money was in a
-- car. See docs/lifecycle/README.md § L8.
-- =============================================================================

-- Holding starts when the money goes out, so from the purchase date; a car with
-- no acquisition recorded is held from the day it was listed. It ends when the
-- car is sold. Appended to the view rather than a second one: one place says
-- what a car cost, and now for how long.
create or replace view v_vehicle_economics with (security_invoker = true) as
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
  (a.vehicle_id is not null)                            as has_acquisition,
  coalesce(a.purchased_at, v.listed_at::date)           as held_from,
  v.sold_at,
  greatest(coalesce(v.sold_at::date, current_date)
           - coalesce(a.purchased_at, v.listed_at::date), 0) as days_held
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
