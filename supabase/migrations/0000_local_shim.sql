-- =============================================================================
-- 0000_local_shim — LOCAL DEVELOPMENT AND TEST ONLY
--
-- Supabase provides the auth schema, auth.uid(), and the anon / authenticated /
-- service_role roles. A plain Postgres container does not, and 0001_init depends
-- on all of them.
--
-- The migrate script SKIPS this file unless ENV=local, so it never reaches a
-- Supabase project. See apps/api/src/dealerai/scripts/migrate.py.
--
-- auth.uid() below mirrors Supabase's real implementation — it reads the sub
-- claim out of the request.jwt.claims GUC — so RLS policies behave identically
-- against the container and against a real project.
-- =============================================================================

create schema if not exists auth;

create table if not exists auth.users (
  id           uuid primary key default gen_random_uuid(),
  email        text unique,
  created_at   timestamptz not null default now()
);

create or replace function auth.uid()
returns uuid
language sql
stable
as $$
  select nullif(
    current_setting('request.jwt.claims', true)::json ->> 'sub',
    ''
  )::uuid;
$$;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit;
  end if;
  -- service_role bypasses RLS on Supabase. Reproduced here so the isolation
  -- test can prove that connecting as it DOES leak — that is what makes the
  -- test meaningful rather than vacuous.
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
end $$;

grant usage on schema auth to anon, authenticated, service_role;
grant select on auth.users to authenticated, service_role;
