-- =============================================================================
-- 0008_sales_inbox — Sales S2: read cursors, notifications and live updates.
-- See docs/sales/02-data-model.md § 2 and § 5.
-- =============================================================================

-- =============================================================================
-- WHO HAS READ WHAT
-- One row per person per conversation. An unread count is then "inbound
-- messages newer than my cursor" — not a flag per message, which would be a row
-- per person per message.
-- =============================================================================
create table conversation_reads (
  tenant_id       uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id         uuid not null references auth.users(id) on delete cascade,
  last_read_at    timestamptz not null default now(),
  primary key (conversation_id, user_id)
);
create index on conversation_reads (tenant_id, user_id);

-- =============================================================================
-- NOTIFICATIONS
-- dedupe_key is what makes "once" true: the event queue only dedupes events
-- that are still pending, so a check that runs again would otherwise tell the
-- manager a second time the moment the first event finished.
-- =============================================================================
create table notifications (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  kind       text not null check (kind in
               ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
                'unassigned_waiting', 'template_rejected', 'channel_disconnected',
                'channel_quality')),
  title      text not null,
  body       text,
  href       text,
  entity     jsonb not null default '{}'::jsonb,
  dedupe_key text,
  read_at    timestamptz,
  created_at timestamptz not null default now()
);
create index on notifications (tenant_id, user_id, created_at desc);
create index on notifications (tenant_id, user_id) where read_at is null;
create unique index notifications_dedupe_uq on notifications (tenant_id, user_id, dedupe_key)
  where dedupe_key is not null;

-- Both tables hold the caller's own rows, never a colleague's. The worker has no
-- user in its session and writes notifications for other people, so a null
-- current user reads everything and WITH CHECK stays tenant-only.
do $$
declare t text;
begin
  foreach t in array array['conversation_reads', 'notifications']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy own_rows on %I
         using (app.has_tenant_access(tenant_id)
                and (user_id = (select app.current_user_id())
                     or (select app.current_user_id()) is null))
         with check (app.has_tenant_access(tenant_id))', t);
    execute format('revoke all on %I from anon, authenticated', t);
  end loop;
end $$;

-- =============================================================================
-- INDEXES THE INBOX QUERIES NEED (docs/sales/02-data-model.md § 6)
-- =============================================================================
create index on conversations (tenant_id, assigned_to, status, last_message_at desc);
create index on conversations (tenant_id, status, last_message_at desc)
  where assigned_to is null;

-- One index for three languages. `simple`, not english: a tenant's messages mix
-- Arabic, English and French, and stemming for one mangles the other two.
create index messages_search_idx on messages using gin (
  to_tsvector('simple', coalesce(body, '') || ' ' || coalesce(transcript->>'text', ''))
);

-- =============================================================================
-- LIVE UPDATES
-- A trigger, not a call in each write path: a path added later cannot forget it.
-- The payload is ids plus the columns the stream filters on — never content,
-- which would put customer messages in Postgres's global notification queue.
-- =============================================================================
create or replace function app.notify_rt()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  row_json jsonb := to_jsonb(new);
  conversation public.conversations%rowtype;
  payload jsonb;
begin
  -- Bulk work (the history import) sets this and emits one summary itself.
  if coalesce(current_setting('app.suppress_rt', true), '') = 'on' then
    return null;
  end if;

  if tg_table_name = 'messages' then
    select * into conversation from public.conversations c where c.id = new.conversation_id;
  elsif tg_table_name = 'conversations' then
    conversation := new;
  end if;

  payload := jsonb_build_object(
    'tenant_id', row_json->>'tenant_id',
    'type', tg_argv[0],
    'id', row_json->>'id',
    'conversation_id', coalesce(row_json->>'conversation_id', conversation.id::text),
    'owner_id', conversation.owner_id,
    'assigned_to', conversation.assigned_to,
    'team_id', conversation.team_id,
    'user_id', row_json->>'user_id'
  );
  perform pg_notify('rt', payload::text);
  return null;
end $$;

revoke all on function app.notify_rt() from public;

create trigger conversations_rt after insert or update on conversations
  for each row execute function app.notify_rt('conversation.updated');
create trigger messages_rt_insert after insert on messages
  for each row execute function app.notify_rt('message.created');
create trigger messages_rt_update after update on messages
  for each row execute function app.notify_rt('message.updated');
create trigger notifications_rt after insert on notifications
  for each row execute function app.notify_rt('notification.created');
