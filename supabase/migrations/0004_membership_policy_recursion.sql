-- =============================================================================
-- 0004 — fix infinite recursion in the memberships policy
--
-- 0001 wrote the admin check inline:
--
--   create policy membership_managed on memberships for all using (
--     exists (select 1 from memberships m where m.tenant_id = memberships.tenant_id
--             and m.user_id = auth.uid() and m.role in ('owner','admin')))
--
-- That subquery reads memberships, which re-invokes the policy, which reads
-- memberships. Postgres detects it and raises:
--
--   infinite recursion detected in policy for relation "memberships"
--
-- app.has_tenant_access() never had this problem because it is SECURITY
-- DEFINER — the inner read runs as the function owner and skips RLS. The rule
-- is therefore: **a policy on table X may only read X through a SECURITY
-- DEFINER function.** Inline is a landmine.
--
-- Also adds app.member_role(). Resolving which role a user holds happens before
-- any tenant context exists (it is the query that establishes one), so it needs
-- the same treatment as the bootstrap functions in 0003.
-- =============================================================================

create or replace function app.is_tenant_admin(t uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.memberships m
    where m.tenant_id = t
      and m.user_id = auth.uid()
      and m.role in ('owner', 'admin')
  );
$$;

create or replace function app.member_role(p_tenant uuid, p_user uuid)
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select role from public.memberships
  where tenant_id = p_tenant and user_id = p_user;
$$;

revoke all on function app.is_tenant_admin(uuid) from public;
revoke all on function app.member_role(uuid, uuid) from public;
grant execute on function app.is_tenant_admin(uuid) to authenticated, anon, dealerai_app;
grant execute on function app.member_role(uuid, uuid) to dealerai_app;

drop policy if exists membership_managed on memberships;
create policy membership_managed on memberships
  for all
  using (
    app.is_tenant_admin(tenant_id)
    or coalesce(nullif(current_setting('app.tenant_id', true), '')::uuid = tenant_id, false)
  )
  with check (
    app.is_tenant_admin(tenant_id)
    or coalesce(nullif(current_setting('app.tenant_id', true), '')::uuid = tenant_id, false)
  );

-- tenants carried the same inline subquery. It does not recurse (it reads
-- memberships, not tenants) but it re-implements the same predicate, and two
-- copies of an authorisation rule drift. One definition.
drop policy if exists tenant_self_write on tenants;
create policy tenant_self_write on tenants
  for update
  using (
    app.is_tenant_admin(id)
    or coalesce(nullif(current_setting('app.tenant_id', true), '')::uuid = id, false)
  );
