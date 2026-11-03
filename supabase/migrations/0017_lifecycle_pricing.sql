-- =============================================================================
-- 0017_lifecycle_pricing — Lifecycle L2: what a car should be priced at, and
-- telling somebody when it should change. See docs/lifecycle/README.md § L2.
-- =============================================================================

-- The dealer's own pricing rules: target margin, the floor's margin, rounding,
-- and the aging ladder. Empty means the defaults in lifecycle/pricing.py — a
-- dealership that never opens the settings still gets sensible proposals.
alter table tenants
  add column pricing_settings jsonb not null default '{}'::jsonb;

-- Two things worth telling somebody about:
--   price_proposed — the pricing sweep thinks a car should move, and an
--                    approval is waiting for whoever may change prices;
--   content_stale  — a price changed and published content still quotes the
--                    old one, which nothing here can take down by itself.
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready', 'task_due',
   'price_proposed', 'content_stale'));

-- The sweep asks "is a price proposal already waiting for this car?" once per
-- car per day; this keeps that a lookup rather than a scan of every approval.
create index if not exists approvals_pending_entity_idx
  on approvals (tenant_id, entity_id, kind) where status = 'pending';
