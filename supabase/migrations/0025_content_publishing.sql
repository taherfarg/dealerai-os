-- =============================================================================
-- 0025_content_publishing — T4.3: a scheduled piece goes out when its slot is
-- due. See docs/05-workflows.md § 5 (W4) and docs/09-implementation-plan.md.
-- =============================================================================

-- What the worker looks for every few seconds, across every dealer: scheduled
-- and due. The (tenant_id, status, scheduled_at) index leads with the tenant,
-- which a cross-tenant read does not have.
create index content_items_due_idx on content_items (scheduled_at) where status = 'scheduled';

-- The worker cannot see content_items: under RLS a session with no tenant sees
-- none (db/session.py). This read is the exception, as app.tenant_clocks() is:
-- the ids of what is due, to the app role only. Publishing reads everything
-- else inside the tenant's own session.
create or replace function app.content_due(lim int default 200)
returns table (tenant_id uuid, id uuid, scheduled_at timestamptz)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select c.tenant_id, c.id, c.scheduled_at
    from content_items c
    join tenants t on t.id = c.tenant_id and t.status = 'active'
   where c.status = 'scheduled' and c.scheduled_at <= now()
   order by c.scheduled_at
   limit lim;
$$;

revoke all on function app.content_due(int) from public;
grant execute on function app.content_due(int) to dealerai_app;

-- publish_failed — a piece did not go out where it should have: the car is no
-- longer for sale, its price changed, or a channel refused it.
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready', 'task_due',
   'price_proposed', 'content_stale',
   'recon_approval', 'recon_overrun',
   'inbound_arrived', 'inbound_late',
   'price_below_floor', 'marketing_stopped',
   'publish_failed'));
