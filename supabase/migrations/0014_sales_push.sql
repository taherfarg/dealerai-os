-- =============================================================================
-- 0014_sales_push — S7 Part B: a notification that reaches a phone.
-- Where a push goes (a device somebody subscribed), and the one notification
-- the product never wrote: a task falling due. See docs/sales/07-frontend.md
-- § 8 and docs/sales/02-data-model.md § 4.
-- =============================================================================

create table push_subscriptions (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  user_id         uuid not null references auth.users(id) on delete cascade,
  -- The push service's address for one browser on one device.
  -- ponytail: unique across workspaces, so somebody in two of them hears from
  -- the one this device was turned on in last. Make it (tenant_id, endpoint)
  -- when a second tenant shares people with the first.
  endpoint        text not null unique,
  p256dh          text not null,
  auth            text not null,
  user_agent      text,
  failure_count   int not null default 0,
  last_success_at timestamptz,
  created_at      timestamptz not null default now()
);
create index on push_subscriptions (tenant_id, user_id);

-- The caller's own devices, never a colleague's. The worker has no user in its
-- session and reads everybody's, to send — as with notifications (0008).
alter table push_subscriptions enable row level security;
alter table push_subscriptions force row level security;
create policy own_rows on push_subscriptions
  using (app.has_tenant_access(tenant_id)
         and (user_id = (select app.current_user_id())
              or (select app.current_user_id()) is null))
  with check (app.has_tenant_access(tenant_id));
revoke all on push_subscriptions from anon, authenticated;

-- A device belongs to whoever subscribed it last: a shared phone that changes
-- hands must not keep telling the last person. The row it replaces may be
-- somebody else's, which the caller cannot see — hence definer.
create or replace function app.remember_push_subscription(
    p_tenant     uuid,
    p_user       uuid,
    p_endpoint   text,
    p_p256dh     text,
    p_auth       text,
    p_user_agent text
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    subscription uuid;
begin
    delete from push_subscriptions where endpoint = p_endpoint;
    insert into push_subscriptions (tenant_id, user_id, endpoint, p256dh, auth, user_agent)
    values (p_tenant, p_user, p_endpoint, p_p256dh, p_auth, p_user_agent)
    returning id into subscription;
    return subscription;
end;
$$;

revoke all on function app.remember_push_subscription(uuid, uuid, text, text, text, text)
    from public;
grant execute on function app.remember_push_subscription(uuid, uuid, text, text, text, text)
    to dealerai_app;

-- A task falling due tells its assignee: one more kind for the bell, and the
-- push that follows it.
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready', 'task_due'));

-- Every way a task is written — the tasks API, a hand-over, the seed — passes
-- here, so here is where its due time is booked: a check at that moment, which
-- does nothing if the task was done, cancelled or moved by then
-- (events/handlers/crm.py). An AI follow-up is due at once and already
-- announces itself (followup_ready). A task changing hands books nothing: the
-- check reads whose it is when it runs.
create or replace function app.book_task_due()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    if new.status = 'open' and new.source <> 'ai' then
        insert into events (tenant_id, event_type, payload, dedupe_key, priority, run_after)
        values (new.tenant_id, 'task.due_check',
                jsonb_build_object('task_id', new.id, 'due_at', new.due_at),
                'task-due:' || new.id || ':' || extract(epoch from new.due_at)::bigint,
                5, new.due_at)
        on conflict do nothing;
    end if;
    return null;
end;
$$;

revoke all on function app.book_task_due() from public;

create trigger tasks_book_due after insert or update of due_at, status on tasks
  for each row execute function app.book_task_due();
