-- =============================================================================
-- 0015_sales_reader_language — S7 Part C.
-- What language a person reads the app in. The browser has always known; the
-- server needs it for what it writes when nobody is there to ask: a
-- notification, and the push that follows it. See docs/sales/07-frontend.md § 6.
-- =============================================================================

alter table profiles
  add column if not exists locale text not null default 'en' check (locale in ('en', 'ar'));

-- A person sets their own, and only their own: the route passes the caller's id.
-- Definer, because profiles are written through functions (0013) and somebody
-- who joined before then has a membership and no row yet.
create or replace function app.set_locale(p_user uuid, p_locale text)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
  insert into profiles (id, locale) values (p_user, p_locale)
  on conflict (id) do update set locale = excluded.locale, updated_at = now();
$$;

revoke all on function app.set_locale(uuid, text) from public;
grant execute on function app.set_locale(uuid, text) to dealerai_app;
