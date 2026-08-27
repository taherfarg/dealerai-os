-- =============================================================================
-- DealerAI OS — 0002_growth
-- Phase 2: ads management, competitor + market intelligence, experiments.
-- Apply only when Phase 2 starts. Nothing in 0001 depends on this file.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- ADS
--
-- One self-referencing table instead of campaigns/ad_sets/ads. All three levels
-- have the same shape (budget, status, targeting, external_id) and every query
-- we care about is "walk the tree for this account". Three near-identical tables
-- would triple the connector-mapping code for no gain.
-- -----------------------------------------------------------------------------

create table ad_entities (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null references tenants(id) on delete cascade,
  channel_id             uuid not null references channels(id) on delete cascade,
  level                  text not null check (level in ('campaign','adset','ad')),
  parent_id              uuid references ad_entities(id) on delete cascade,
  external_id            text,
  name                   text not null,
  objective              text,
  status                 text not null default 'draft'
                           check (status in ('draft','active','paused','archived','deleted')),
  daily_budget_minor     bigint check (daily_budget_minor >= 0),
  lifetime_budget_minor  bigint check (lifetime_budget_minor >= 0),
  currency               char(3) not null default 'AED',
  targeting              jsonb not null default '{}'::jsonb,
  config                 jsonb not null default '{}'::jsonb,
  -- level='ad' points at the creative it runs
  content_item_id        uuid references content_items(id) on delete set null,
  vehicle_id             uuid references vehicles(id) on delete set null,
  created_by_run_id      uuid references agent_runs(id) on delete set null,
  external_created_at    timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  constraint ad_entities_level_parent check (
    (level = 'campaign' and parent_id is null) or (level <> 'campaign' and parent_id is not null)
  )
);
create unique index ad_entities_external_uq on ad_entities (channel_id, external_id)
  where external_id is not null;
create index on ad_entities (tenant_id, level, status);
create index on ad_entities (parent_id);

create table ad_metrics_daily (
  id                   bigserial primary key,
  tenant_id            uuid not null references tenants(id) on delete cascade,
  ad_entity_id         uuid not null references ad_entities(id) on delete cascade,
  metric_date          date not null,
  spend_minor          bigint not null default 0,
  impressions          bigint not null default 0,
  reach                bigint not null default 0,
  clicks               int not null default 0,
  ctr                  numeric(6,4),
  cpc_minor            bigint,
  cpm_minor            bigint,
  -- our funnel, joined back from leads.source_* not from the platform's guess
  leads                int not null default 0,
  conversations        int not null default 0,
  qualified_leads      int not null default 0,
  deals                int not null default 0,
  revenue_minor        bigint not null default 0,
  cost_per_lead_minor  bigint,
  roas                 numeric(8,3),
  raw                  jsonb not null default '{}'::jsonb,
  created_at           timestamptz not null default now(),
  unique (ad_entity_id, metric_date)
);
create index on ad_metrics_daily (tenant_id, metric_date desc);

-- Every budget or status change an agent makes. This is the audit trail the
-- budget guard is checked against (max % change per 24h).
create table ad_changes (
  id             bigserial primary key,
  tenant_id      uuid not null references tenants(id) on delete cascade,
  ad_entity_id   uuid not null references ad_entities(id) on delete cascade,
  run_id         uuid references agent_runs(id) on delete set null,
  change_type    text not null check (change_type in
                   ('budget','status','targeting','creative','bid')),
  before_value   jsonb,
  after_value    jsonb,
  pct_change     numeric(6,2),
  reason         text not null,
  approved_by    uuid references auth.users(id),
  created_at     timestamptz not null default now()
);
create index on ad_changes (tenant_id, ad_entity_id, created_at desc);

-- -----------------------------------------------------------------------------
-- COMPETITOR + MARKET INTELLIGENCE
-- Sourced from official APIs and licensed data only. See docs/00-prd.md § 12.
-- -----------------------------------------------------------------------------

create table competitors (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  name        text not null,
  -- {"instagram":"@dealer","facebook_page_id":"123","website":"https://..."}
  handles     jsonb not null default '{}'::jsonb,
  markets     text[] not null default '{AE}',
  notes       text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, name)
);

create table competitor_observations (
  id             bigserial primary key,
  tenant_id      uuid not null references tenants(id) on delete cascade,
  competitor_id  uuid not null references competitors(id) on delete cascade,
  kind           text not null check (kind in ('post','ad','price','offer','inventory')),
  external_id    text,
  url            text,
  observed_at    timestamptz not null default now(),
  summary        text,
  make           text,
  model          text,
  price_minor    bigint,
  currency       char(3),
  engagement     jsonb not null default '{}'::jsonb,
  raw            jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now()
);
create unique index competitor_obs_uq on competitor_observations (competitor_id, kind, external_id)
  where external_id is not null;
create index on competitor_observations (tenant_id, observed_at desc);
create index on competitor_observations (tenant_id, make, model);

create table market_signals (
  id           bigserial primary key,
  tenant_id    uuid not null references tenants(id) on delete cascade,
  kind         text not null check (kind in
                 ('demand','price','trend','new_model','competitor_move','seasonality')),
  make         text,
  model        text,
  market       char(2),
  direction    text check (direction in ('up','down','flat')),
  magnitude    numeric(8,3),
  statement    text not null,
  evidence     jsonb not null default '{}'::jsonb,
  confidence   numeric(3,2) check (confidence between 0 and 1),
  source       text,
  observed_at  timestamptz not null default now(),
  created_at   timestamptz not null default now()
);
create index on market_signals (tenant_id, observed_at desc);
create index on market_signals (tenant_id, make, model, kind);

-- -----------------------------------------------------------------------------
-- EXPERIMENTS (the learning loop's controlled tests)
-- -----------------------------------------------------------------------------

create table experiments (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id) on delete cascade,
  hypothesis   text not null,
  kind         text not null check (kind in
                 ('creative','copy','posting_time','audience','offer','template')),
  -- [{"key":"a","description":"front 3/4 on black"},{"key":"b","description":"lifestyle"}]
  variants     jsonb not null default '[]'::jsonb,
  metric       text not null,
  min_sample   int not null default 30,
  status       text not null default 'running'
                 check (status in ('draft','running','concluded','abandoned')),
  result       jsonb,
  winner       text,
  run_id       uuid references agent_runs(id) on delete set null,
  started_at   timestamptz not null default now(),
  ended_at     timestamptz,
  created_at   timestamptz not null default now()
);
create index on experiments (tenant_id, status);

-- Which experiment variant a piece of content belongs to.
alter table content_items
  add column experiment_id uuid references experiments(id) on delete set null,
  add column variant_key   text,
  add column ad_entity_id  uuid references ad_entities(id) on delete set null;
create index on content_items (tenant_id, experiment_id) where experiment_id is not null;

-- -----------------------------------------------------------------------------
-- VIEWS
-- -----------------------------------------------------------------------------

create view v_campaign_performance with (security_invoker = true) as
with recursive tree as (
  select id as campaign_id, id as node_id
  from ad_entities where level = 'campaign'
  union all
  select t.campaign_id, e.id
  from ad_entities e join tree t on e.parent_id = t.node_id
)
select
  c.id                    as campaign_id,
  c.tenant_id,
  c.name,
  c.status,
  coalesce(sum(m.spend_minor), 0)     as spend_minor,
  coalesce(sum(m.impressions), 0)     as impressions,
  coalesce(sum(m.clicks), 0)          as clicks,
  coalesce(sum(m.leads), 0)           as leads,
  coalesce(sum(m.qualified_leads), 0) as qualified_leads,
  coalesce(sum(m.deals), 0)           as deals,
  coalesce(sum(m.revenue_minor), 0)   as revenue_minor,
  case when sum(m.leads) > 0
       then sum(m.spend_minor) / sum(m.leads) end            as cost_per_lead_minor,
  case when sum(m.spend_minor) > 0
       then sum(m.revenue_minor)::numeric / sum(m.spend_minor) end as roas
from ad_entities c
join tree t on t.campaign_id = c.id
left join ad_metrics_daily m on m.ad_entity_id = t.node_id
where c.level = 'campaign'
group by c.id, c.tenant_id, c.name, c.status;

-- =============================================================================
-- TRIGGERS + RLS (same uniform policy as 0001)
-- =============================================================================

do $$
declare t text;
begin
  foreach t in array array['ad_entities','competitors'] loop
    execute format(
      'create trigger %I_touch before update on %I
         for each row execute function app.touch_updated_at()', t, t);
  end loop;

  foreach t in array array[
    'ad_entities','ad_metrics_daily','ad_changes','competitors',
    'competitor_observations','market_signals','experiments'
  ]
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy tenant_isolation on %I
         using (app.has_tenant_access(tenant_id))
         with check (app.has_tenant_access(tenant_id))', t);
  end loop;
end $$;

grant select, insert, update, delete on all tables in schema public to authenticated;
grant usage, select on all sequences in schema public to authenticated;
