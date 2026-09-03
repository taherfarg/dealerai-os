-- =============================================================================
-- 0005 — findings from Supabase's database linter, run after the first deploy
--
-- Two real issues. Both are the same underlying mistake: assuming a default is
-- safe rather than checking what it actually is.
-- =============================================================================

-- 1. app.touch_updated_at() ran with a mutable search_path.
--
-- Every other function in the app schema pins it; this one was written first
-- and missed. It is SECURITY INVOKER and only assigns to NEW, so the practical
-- risk is low — but a trigger function that resolves `now()` through a
-- caller-controlled search_path is a resolution someone else can influence, and
-- there is no reason to leave it open.
alter function app.touch_updated_at() set search_path = public, pg_temp;

-- 2. The migration ledger was writable by anon.
--
-- schema_migrations is created by the migrate runner, not by a file in this
-- directory, so it never passed through the grants at the bottom of 0001. On
-- Supabase, new tables in `public` inherit default privileges for anon and
-- authenticated — which meant INSERT, UPDATE, DELETE *and TRUNCATE* on the
-- ledger for anyone holding the public anon key.
--
-- Truncating it would make the runner replay every migration and fail: a
-- deployment denial of service from a key that is published in the frontend
-- bundle by design.
--
-- The runner now revokes these at creation time (scripts/migrate.py). This
-- statement fixes projects created before that change.
do $$
begin
  if to_regclass('public.schema_migrations') is not null then
    execute 'revoke all on public.schema_migrations from anon, authenticated';
  end if;
end $$;

-- Deliberately NOT addressed: the `vector` extension living in the public
-- schema, which the linter flags as a warning. Moving it to `extensions` would
-- mean the local container needs that schema too, purely to mirror a Supabase
-- convention. The warning exists because an attacker who can create objects in
-- `public` could shadow extension functions — and no role here can:
-- has_schema_privilege('anon'|'authenticated'|'public', 'public', 'CREATE') is
-- false on this project. Revisit if that ever changes.
