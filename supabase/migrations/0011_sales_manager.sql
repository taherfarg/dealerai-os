-- =============================================================================
-- 0011_sales_manager — Sales S6: the manager's morning, the settings screens,
-- and a customer's right to their data. See docs/sales/02-data-model.md § 2
-- and § 7, and docs/sales/05-workflows.md § 13–14.
-- =============================================================================

-- =============================================================================
-- A MISSED TARGET IS A FACT
-- Until now a miss was a notification and nothing else, and a notification is
-- somebody's, is deleted after 90 days, and goes when its reader does. The
-- dashboard counts misses per day and per salesperson, so a miss is a row. A
-- child of its conversation: visible exactly when the conversation is, erased
-- with it. One per wait — the check that writes it can run twice.
-- =============================================================================
create table sla_misses (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  -- Whoever had the customer when the target passed: the miss counts against them.
  assigned_to     uuid references auth.users(id) on delete set null,
  waiting_since   timestamptz not null,
  due_at          timestamptz not null,
  created_at      timestamptz not null default now(),
  unique (conversation_id, waiting_since)
);
create index on sla_misses (tenant_id, due_at);

alter table sla_misses enable row level security;
alter table sla_misses force row level security;
create policy tenant_visibility on sla_misses
  using (
    app.has_tenant_access(tenant_id)
    and exists (select 1 from public.conversations c where c.id = sla_misses.conversation_id)
  )
  with check (app.has_tenant_access(tenant_id));
revoke all on sla_misses from anon, authenticated;
grant select, insert, update, delete on sla_misses to dealerai_app;

-- =============================================================================
-- THE MORNING BRIEF — docs/sales/05-workflows.md § 13
-- One row per reader per day: a manager's brief is written from what that
-- manager may see, so two managers with different teams read different
-- numbers and neither learns anything from the other's. A headline in both UI
-- languages and the numbers it was written from — never a customer's name:
-- the model is not shown one (sales/dashboard.render_facts), so nothing here
-- outlives a customer's erasure.
-- =============================================================================
create table sales_briefs (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  brief_date  date not null,
  -- {"en": "...", "ar": "..."}; null when there was nothing to say, no budget,
  -- or a line the facts guard refused.
  headline    jsonb,
  facts       jsonb not null,
  created_at  timestamptz not null default now(),
  unique (tenant_id, user_id, brief_date)
);

alter table sales_briefs enable row level security;
alter table sales_briefs force row level security;
create policy own_rows on sales_briefs
  using (app.has_tenant_access(tenant_id)
         and (user_id = (select app.current_user_id())
              or (select app.current_user_id()) is null))
  with check (app.has_tenant_access(tenant_id));
revoke all on sales_briefs from anon, authenticated;
grant select, insert, update, delete on sales_briefs to dealerai_app;

-- =============================================================================
-- QUICK REPLIES — docs/sales/02-data-model.md § 2
-- Tenant-wide: every salesperson types the same shortcuts, and a manager edits
-- them for everybody. At least one of the three languages.
-- =============================================================================
create table quick_replies (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  shortcut    text not null check (shortcut ~ '^/[a-z0-9-]{1,30}$'),
  title       text not null check (length(title) between 1 and 80),
  body        jsonb not null check (jsonb_typeof(body) = 'object'
                                    and body ?| array['ar', 'en', 'fr']),
  created_by  uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, shortcut)
);

alter table quick_replies enable row level security;
alter table quick_replies force row level security;
create policy tenant_isolation on quick_replies
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));
revoke all on quick_replies from anon, authenticated;
grant select, insert, update, delete on quick_replies to dealerai_app;
create trigger quick_replies_touch before update on quick_replies
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- ACCEPTANCE, BY INTENT — docs/sales/04-ai-copilot.md § 3 and § 9
-- The pilot's S5 metric: (sent + edited with edit_ratio ≤ 0.2) / decided.
-- security_invoker, so it reads through the caller's visibility rather than
-- its owner's; tests/test_tenant_isolation.py requires that of every view.
-- =============================================================================
create view v_suggestion_acceptance with (security_invoker = true) as
select tenant_id,
       (created_at at time zone 'UTC')::date                             as day,
       intent,
       count(*) filter (where outcome is not null)                       as decided,
       count(*) filter (where outcome = 'sent')                          as sent,
       count(*) filter (where outcome = 'edited' and edit_ratio <= 0.2)  as lightly_edited,
       count(*) filter (where outcome = 'edited' and edit_ratio > 0.2)   as rewritten,
       count(*) filter (where outcome = 'discarded')                     as discarded
  from ai_suggestions
 group by tenant_id, (created_at at time zone 'UTC')::date, intent;

revoke all on v_suggestion_acceptance from anon, authenticated;
grant select on v_suggestion_acceptance to dealerai_app;

-- =============================================================================
-- A CLOCK FOR EVERY DEALERSHIP
-- The brief is at 08:00 and retention at 03:00 in each tenant's own timezone,
-- and the worker cannot list tenants: under RLS a session with no tenant sees
-- none (db/session.py). This one read is the exception, as tenants_for_user
-- is: ids and timezones and nothing else, to the app role only.
-- =============================================================================
create or replace function app.tenant_clocks()
returns table (id uuid, timezone text)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select t.id, t.timezone from tenants t where t.status = 'active' order by t.id;
$$;

revoke all on function app.tenant_clocks() from public;
grant execute on function app.tenant_clocks() to dealerai_app;

-- =============================================================================
-- ERASURE — docs/sales/05-workflows.md § 14, the UAE PDPL
-- One function for both ways a customer leaves: an owner's DELETE, and the
-- nightly retention pass. Three things do not cascade from a contact and are
-- deleted by hand here: conversations (0001: on delete set null — deleting
-- the contact alone would orphan every message), tasks (set null), and
-- notifications (they name the customer in a title). A merge left a snapshot
-- of both records in audit_log (0009); the who and when stay, the what goes.
-- Returns the media paths, which only the worker can delete: Storage is not SQL.
--
-- Invoker's rights, so it runs under RLS: the caller's session must see the
-- whole customer. The route and the retention job both call it in a session
-- with no user, the one that reaches every colleague's notifications.
-- =============================================================================
create or replace function app.erase_contact(p_contact uuid, p_actor uuid, p_reason text)
returns text[]
language plpgsql
set search_path = public, pg_temp
as $fn$
declare
  v_tenant        uuid;
  v_conversations uuid[];
  v_leads         uuid[];
  v_tasks         uuid[];
  v_ids           text[];
  v_paths         text[];
begin
  select tenant_id into v_tenant from contacts where id = p_contact for update;
  if v_tenant is null then
    return null;
  end if;

  select coalesce(array_agg(id), '{}') into v_conversations
    from conversations where contact_id = p_contact;
  select coalesce(array_agg(id), '{}') into v_leads
    from leads where contact_id = p_contact;
  select coalesce(array_agg(id), '{}') into v_tasks
    from tasks
   where contact_id = p_contact
      or lead_id = any (v_leads)
      or conversation_id = any (v_conversations);
  v_ids := (v_conversations || v_leads || v_tasks || p_contact)::text[];

  select coalesce(array_agg(distinct asset->>'storage_path'), '{}') into v_paths
    from messages m
    cross join lateral jsonb_array_elements(m.media) asset
   where m.conversation_id = any (v_conversations)
     and asset->>'storage_path' is not null;

  -- What the models were shown about them: the runs, and their traces with them.
  delete from agent_runs
   where tenant_id = v_tenant
     and (goal_input->>'conversation_id' = any (v_ids)
          or goal_input->>'lead_id' = any (v_ids));
  -- Work still queued about them would run against rows that are gone.
  delete from events
   where tenant_id = v_tenant and status = 'pending'
     and (payload->>'conversation_id' = any (v_ids)
          or payload->>'lead_id' = any (v_ids)
          or payload->>'contact_id' = any (v_ids));
  delete from notifications where entity->>'id' = any (v_ids);
  delete from tasks where id = any (v_tasks);
  -- Messages, reads, drafts and misses go with their conversations.
  delete from conversations where id = any (v_conversations);
  update audit_log set before = null, after = null
   where entity_type = 'contact'
     and (entity_id = p_contact or meta->>'keep_id' = p_contact::text);
  -- Identities, leads and activities go with the contact.
  delete from contacts where id = p_contact;

  insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type, entity_id, meta)
  values (v_tenant,
          case when p_actor is null then 'system' else 'user' end,
          p_actor::text,
          'contact.erased', 'contact', p_contact,
          jsonb_build_object('reason', p_reason));
  return v_paths;
end $fn$;

revoke all on function app.erase_contact(uuid, uuid, text) from public;
grant execute on function app.erase_contact(uuid, uuid, text) to dealerai_app;

-- =============================================================================
-- ONE MORE THING WORTH INTERRUPTING SOMEBODY FOR
-- =============================================================================
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready'));
