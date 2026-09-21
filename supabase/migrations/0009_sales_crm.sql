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
