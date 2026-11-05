-- =============================================================================
-- 0024_lifecycle_sourcing_backfill — Lifecycle L5: read the interests recorded
-- before 0023 existed. See docs/lifecycle/README.md § L5.
-- =============================================================================

-- 0023's trigger books a read only when an interest changes, so a customer who
-- asked last week would never reach the buying list. Book one read for every
-- interest asked within the list's 30 days, as the trigger would have. Run
-- again, it books nothing a pending read already covers.
insert into events (tenant_id, event_type, payload, dedupe_key)
select c.tenant_id, 'sourcing.interest_changed', jsonb_build_object('contact_id', c.id),
       'interest:' || c.id
  from contacts c
 where nullif(c.profile -> 'interest' ->> 'value', '') is not null
   and coalesce((c.profile -> 'interest' ->> 'updated_at')::timestamptz, c.profile_updated_at)
       > now() - interval '30 days'
   and not exists (select 1 from customer_wants w where w.contact_id = c.id)
on conflict do nothing;
