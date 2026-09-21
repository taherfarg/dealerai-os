-- =============================================================================
-- 0009_sales_crm — Sales S3: pipelines, stages, tasks, and leads that sit on
-- them; the two writes that move a customer's whole world.
-- See docs/sales/02-data-model.md § 2-§ 6 and 05-workflows.md § 9-§ 10.
-- =============================================================================

-- =============================================================================
-- PIPELINES
-- A stage is a row because every dealership sorts its work differently, and
-- Pollux needs two boards on day one. "At least one lost stage" and "a stage
-- with leads cannot be deleted" are checked in the API, with the count in the
-- error: a deferred constraint trigger for a rule one endpoint can break is not
-- worth its weight.
-- =============================================================================
create table pipelines (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  name        text not null,
  position    int not null default 0,
  is_default  boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, name)
);
create unique index pipelines_default_uq on pipelines (tenant_id) where is_default;

create table pipeline_stages (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  pipeline_id uuid not null references pipelines(id) on delete cascade,
  name        text not null,
  position    int not null default 0,
  category    text not null check (category in ('open', 'won', 'lost')),
  created_at  timestamptz not null default now(),
  unique (pipeline_id, name)
);
create unique index pipeline_stages_won_uq on pipeline_stages (pipeline_id)
  where category = 'won';
create index on pipeline_stages (tenant_id, pipeline_id, position);

-- =============================================================================
-- TASKS
-- assignee_id is the visibility column: a task is somebody's, always.
-- A lead's "next action" is its earliest open task — computed, never stored,
-- which is why leads.next_action_at goes below.
-- =============================================================================
create table tasks (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  title           text not null,
  kind            text not null default 'todo'
                    check (kind in ('follow_up', 'call', 'meeting', 'todo')),
  due_at          timestamptz not null,
  status          text not null default 'open'
                    check (status in ('open', 'done', 'cancelled')),
  completed_at    timestamptz,
  cancel_reason   text,
  assignee_id     uuid not null references auth.users(id) on delete cascade,
  created_by      uuid references auth.users(id) on delete set null,
  contact_id      uuid references contacts(id) on delete set null,
  lead_id         uuid references leads(id) on delete set null,
  conversation_id uuid references conversations(id) on delete set null,
  source          text not null default 'human' check (source in ('human', 'ai', 'rule')),
  ai_draft        jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index on tasks (tenant_id, assignee_id, status, due_at);
create index on tasks (tenant_id, due_at) where status = 'open';
create index on tasks (tenant_id, lead_id, due_at) where status = 'open';

create trigger tasks_touch before update on tasks
  for each row execute function app.touch_updated_at();
create trigger pipelines_touch before update on pipelines
  for each row execute function app.touch_updated_at();

-- =============================================================================
-- LEADS MOVE ONTO A PIPELINE
-- The view depends on the column being dropped, so it goes first and comes back
-- at the end over pipeline_stages.category.
-- =============================================================================
drop view if exists v_lead_funnel;

alter table leads
  add column pipeline_id      uuid references pipelines(id) on delete restrict,
  add column stage_id         uuid references pipeline_stages(id) on delete restrict,
  add column stage_entered_at timestamptz not null default now(),
  add column score_signals    jsonb not null default '[]'::jsonb;

-- Every existing tenant gets the default pipeline its leads already implied,
-- and each lead lands on the stage its enum named.
do $$
declare
  t record;
  pipeline uuid;
  stage record;
begin
  for t in select id from tenants loop
    insert into pipelines (tenant_id, name, position, is_default)
      values (t.id, 'Sales', 0, true)
      returning id into pipeline;
    for stage in
      select * from (values
        ('New', 0, 'open'), ('Contacted', 1, 'open'), ('Qualified', 2, 'open'),
        ('Appointment', 3, 'open'), ('Negotiation', 4, 'open'),
        ('Won', 5, 'won'), ('Lost', 6, 'lost')
      ) as s(name, position, category)
    loop
      insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
        values (t.id, pipeline, stage.name, stage.position, stage.category);
    end loop;
    update leads l set
      pipeline_id = pipeline,
      stage_id = (select s.id from pipeline_stages s
                   where s.pipeline_id = pipeline and lower(s.name) = l.stage)
    where l.tenant_id = t.id;
  end loop;
end $$;

alter table leads
  alter column pipeline_id set not null,
  alter column stage_id set not null,
  drop column stage,
  drop column next_action_at;

create index on leads (tenant_id, pipeline_id, stage_id);

-- "Qualified" was the third of seven fixed stages; with configurable stages the
-- nearest honest definition is "past the first two columns and not lost". The
-- view belongs to marketing's reporting, which is why it keeps its old shape.
create view v_lead_funnel with (security_invoker = true) as
select
  l.tenant_id,
  date_trunc('day', l.created_at)                                 as day,
  count(*)                                                        as leads,
  count(*) filter (where l.intent_band = 'hot')                   as hot_leads,
  count(*) filter (where s.category <> 'lost' and s.position >= 2) as qualified,
  count(*) filter (where s.category = 'won')                      as won
from leads l
join pipeline_stages s on s.id = l.stage_id
group by 1, 2;

-- =============================================================================
-- VISIBILITY (docs/sales/02-data-model.md § 4)
-- A pipeline is the workspace's shape, so it is tenant-wide. A task is one
-- person's work, so it follows the same owner rule as everything else.
-- =============================================================================
alter table pipelines enable row level security;
alter table pipelines force row level security;
create policy tenant_isolation on pipelines
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

alter table pipeline_stages enable row level security;
alter table pipeline_stages force row level security;
create policy tenant_isolation on pipeline_stages
  using (app.has_tenant_access(tenant_id)) with check (app.has_tenant_access(tenant_id));

-- A worker session has no user, and writes tasks for other people: a null
-- current user sees everything, exactly as notifications do.
alter table tasks enable row level security;
alter table tasks force row level security;
create policy tenant_visibility on tasks
  using (
    app.has_tenant_access(tenant_id)
    and (
      (select app.visible_owner_ids()) is null
      or assignee_id = any (coalesce((select app.visible_owner_ids()), '{}'))
    )
  )
  with check (app.has_tenant_access(tenant_id));

revoke all on pipelines, pipeline_stages, tasks from anon, authenticated;
grant select, insert, update, delete on pipelines, pipeline_stages, tasks to dealerai_app;

-- =============================================================================
-- LIVE UPDATES
-- A lead and a task carry their own owner, so the payload reads the row before
-- it reads the conversation. Same trigger function, two more tables, nothing
-- for a new write path to forget.
-- =============================================================================
create or replace function app.notify_rt()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
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
    'owner_id', coalesce(row_json->>'owner_id', conversation.owner_id::text),
    'assigned_to', coalesce(row_json->>'assigned_to', row_json->>'assignee_id',
                            conversation.assigned_to::text),
    'team_id', coalesce(row_json->>'team_id', conversation.team_id::text),
    'user_id', row_json->>'user_id'
  );
  perform pg_notify('rt', payload::text);
  return null;
end $fn$;

revoke all on function app.notify_rt() from public;

create trigger leads_rt after insert or update on leads
  for each row execute function app.notify_rt('lead.updated');
create trigger tasks_rt after insert or update on tasks
  for each row execute function app.notify_rt('task.updated');

-- =============================================================================
-- SINGLE WRITERS (docs/sales/02-data-model.md § 4, 05-workflows.md § 9-§ 10)
-- SECURITY DEFINER because they must move rows the caller cannot see: a
-- salesperson hands a customer to a colleague whose rows are invisible to them.
-- The route decides who may call; the function decides what moving means.
-- =============================================================================
create or replace function app.reassign_contact(
  p_contact_id uuid, p_new_owner uuid, p_actor uuid
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_tenant uuid;
  v_old_owner uuid;
  v_owner_name text;
  v_conversation record;
begin
  select tenant_id, owner_id into v_tenant, v_old_owner
    from contacts where id = p_contact_id for update;
  if v_tenant is null then
    raise exception 'no such contact' using errcode = 'no_data_found';
  end if;
  select full_name into v_owner_name from profiles where id = p_new_owner;

  update contacts set owner_id = p_new_owner where id = p_contact_id;

  -- owner_id and assigned_to move together: a conversation owned by one person
  -- and answered by another is the state the inbox cannot explain.
  for v_conversation in
    select id from conversations where contact_id = p_contact_id and status = 'open'
  loop
    update conversations
       set owner_id = p_new_owner, assigned_to = p_new_owner
     where id = v_conversation.id;
    -- A grey line in the thread, the same shape the API writes
    -- (routes/inbox.py _thread_event): a conversation keeps its own history.
    insert into messages (tenant_id, conversation_id, kind, type, direction, sender, origin, event)
      values (v_tenant, v_conversation.id, 'event', 'text', 'out', 'system', 'system',
              jsonb_build_object(
                'type', 'reassigned',
                'text', 'Reassigned to ' || coalesce(v_owner_name, 'a colleague'),
                'to', p_new_owner::text));
  end loop;

  -- Won and lost leads stay with whoever closed them: moving them would rewrite
  -- somebody's month.
  update leads l set owner_id = p_new_owner
    from pipeline_stages s
   where s.id = l.stage_id and l.contact_id = p_contact_id and s.category = 'open';
  update tasks set assignee_id = p_new_owner
   where contact_id = p_contact_id and status = 'open';

  insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type, entity_id,
                         before, after)
    values (v_tenant, 'user', p_actor::text, 'contact.reassigned', 'contact', p_contact_id,
            jsonb_build_object('owner_id', v_old_owner),
            jsonb_build_object('owner_id', p_new_owner));
end $fn$;

create or replace function app.merge_contacts(
  p_keep_id uuid, p_merge_id uuid, p_actor uuid
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_tenant uuid;
  v_keep jsonb;
  v_merged jsonb;
begin
  if p_keep_id = p_merge_id then
    raise exception 'a customer cannot be merged into itself' using errcode = 'check_violation';
  end if;
  select tenant_id into v_tenant from contacts where id = p_keep_id for update;
  select to_jsonb(c) into v_merged from contacts c where c.id = p_merge_id for update;
  if v_tenant is null or v_merged is null then
    raise exception 'no such contact' using errcode = 'no_data_found';
  end if;
  if (v_merged->>'tenant_id')::uuid <> v_tenant then
    raise exception 'customers are in different workspaces' using errcode = 'check_violation';
  end if;
  select to_jsonb(c) into v_keep from contacts c where c.id = p_keep_id;

  -- Identities move wholesale, and none of them arrives primary: unique
  -- (tenant_id, kind, value) means two customers in one workspace can never
  -- hold the same number, so there is nothing to collide with — and the kept
  -- customer's own primary number stays the primary one.
  update contact_identities set contact_id = p_keep_id, is_primary = false
   where contact_id = p_merge_id;

  update conversations set contact_id = p_keep_id where contact_id = p_merge_id;
  update leads set contact_id = p_keep_id where contact_id = p_merge_id;
  update tasks set contact_id = p_keep_id where contact_id = p_merge_id;
  update activities set contact_id = p_keep_id where contact_id = p_merge_id;

  -- docs/sales/05-workflows.md § 10: the kept customer's human values win, then
  -- its AI ones, then whatever only the duplicate knew. jsonb_object_agg keeps
  -- the last value for a key, so the union runs in order of increasing
  -- authority. The cost is real and deliberate: a person's answer on the
  -- duplicate loses to a guess on the keeper. The merge dialog shows both sides
  -- before anyone confirms, and the audit row keeps what lost.
  update contacts set
    profile = (
      select coalesce(jsonb_object_agg(key, value), '{}'::jsonb)
        from (
          select key, value from jsonb_each(coalesce(v_merged->'profile', '{}'::jsonb))
          union all
          select key, value from jsonb_each(coalesce(v_keep->'profile', '{}'::jsonb))
           where value->>'source' is distinct from 'human'
          union all
          select key, value from jsonb_each(coalesce(v_keep->'profile', '{}'::jsonb))
           where value->>'source' = 'human'
        ) merged_fields
    ),
    profile_updated_at = now(),
    -- jsonb functions, not a cast: to_jsonb turned tags into a JSON array, and
    -- ["vip"] is not a Postgres array literal.
    tags = (select coalesce(array_agg(distinct tag), '{}'::text[])
              from (
                select jsonb_array_elements_text(coalesce(v_keep->'tags', '[]'::jsonb)) as tag
                union
                select jsonb_array_elements_text(coalesce(v_merged->'tags', '[]'::jsonb))
              ) both_records)
  where id = p_keep_id;

  delete from contacts where id = p_merge_id;

  -- Not undoable, so the snapshot of both sides is what a manual repair would
  -- start from — and what the old URL reads to say where the customer went.
  insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type, entity_id,
                         before, after, meta)
    values (v_tenant, 'user', p_actor::text, 'contact.merged', 'contact', p_merge_id,
            v_merged, v_keep, jsonb_build_object('keep_id', p_keep_id));
end $fn$;

revoke all on function app.reassign_contact(uuid, uuid, uuid) from public;
revoke all on function app.merge_contacts(uuid, uuid, uuid) from public;
grant execute on function app.reassign_contact(uuid, uuid, uuid) to dealerai_app;
grant execute on function app.merge_contacts(uuid, uuid, uuid) to dealerai_app;
