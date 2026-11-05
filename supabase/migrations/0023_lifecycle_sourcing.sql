-- =============================================================================
-- 0023_lifecycle_sourcing — Lifecycle L5: what customers asked for, read into
-- cars, so the dealer can buy what it does not have. See
-- docs/lifecycle/README.md § L5.
-- =============================================================================

-- One row per car a customer's interest names, as the reader named it
-- (lifecycle/sourcing.py). An interest that names no car — "a family SUV" —
-- is one row with no make, so it is not read again. Rewritten whole when the
-- interest changes. Not the buy side: it is what a customer said. Readers join
-- `contacts`, so sales visibility applies through it.
create table customer_wants (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  contact_id  uuid not null references contacts(id) on delete cascade,
  -- The interest this was read from, word for word: unchanged text, no new read.
  interest    text not null check (length(interest) <= 500),
  make        text check (length(make) <= 60),
  model       text check (length(model) <= 80),
  model_year  int check (model_year between 1950 and 2100),
  -- The customer's words that name this car.
  quoted      text check (length(quoted) <= 200),
  asked_at    timestamptz not null,
  created_at  timestamptz not null default now(),
  check ((make is null) = (model is null))
);
create index on customer_wants (tenant_id, asked_at desc);
create index on customer_wants (contact_id);

alter table customer_wants enable row level security;
alter table customer_wants force row level security;
create policy tenant_isolation on customer_wants
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));

revoke all on customer_wants from anon, authenticated;
grant select, insert, update, delete on customer_wants to dealerai_app;

-- Every way an interest is written — the profile agent, the profile panel, a
-- merge — passes here, so here is where its reading is booked. The dedupe key
-- keeps one pending read per customer; the reader takes whatever the interest
-- says when it runs.
create or replace function app.book_interest_read()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    if tg_op = 'INSERT' then
        if new.profile -> 'interest' is null then
            return null;
        end if;
    elsif (new.profile -> 'interest' ->> 'value') is not distinct from
          (old.profile -> 'interest' ->> 'value') then
        return null;
    end if;
    insert into events (tenant_id, event_type, payload, dedupe_key)
    values (new.tenant_id, 'sourcing.interest_changed',
            jsonb_build_object('contact_id', new.id),
            'interest:' || new.id)
    on conflict do nothing;
    return null;
end;
$$;

revoke all on function app.book_interest_read() from public;

create trigger contacts_book_interest_read after insert or update of profile on contacts
  for each row execute function app.book_interest_read();
