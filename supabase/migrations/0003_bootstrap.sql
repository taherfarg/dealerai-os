-- =============================================================================
-- 0003_bootstrap — the two writes that must happen before a tenant context exists
--
-- Creating a workspace and accepting an invitation are both chicken-and-egg
-- under RLS: you are not yet a member of the tenant you are about to join, so
-- app.has_tenant_access() is correctly false and every policy refuses the write.
--
-- The tempting fix is an INSERT policy with `with check (true)` on memberships.
-- That is a hole: it would let any authenticated user insert themselves into
-- any tenant, as owner. The whole isolation guarantee would rest on application
-- code remembering to check.
--
-- Instead these two operations — and only these two — are SECURITY DEFINER
-- functions with a narrow signature. The privilege is scoped to exactly the
-- statements below, visible in SQL, and grantable to one role.
-- =============================================================================

create or replace function app.create_tenant_with_owner(
    p_slug     text,
    p_name     text,
    p_country  char(2),
    p_timezone text,
    p_currency char(3),
    p_locales  text[],
    p_owner    uuid
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    new_id uuid;
begin
    insert into tenants (slug, name, country, timezone, currency, locales)
    values (p_slug, p_name, p_country, p_timezone, p_currency, p_locales)
    returning id into new_id;

    -- A tenant with no owner is unreachable: nobody can be invited into it and
    -- nobody can delete it. The two writes are never allowed to diverge, so
    -- they live in one function rather than two application statements.
    insert into memberships (tenant_id, user_id, role)
    values (new_id, p_owner, 'owner');

    insert into brand_profiles (tenant_id, display_name)
    values (new_id, p_name);

    return new_id;
end;
$$;

-- Idempotent by design: replaying an invitation link must not create a second
-- membership, and must never change an existing role. Returns the role the
-- user actually holds afterwards.
create or replace function app.accept_invite(
    p_tenant uuid,
    p_user   uuid,
    p_role   text
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    existing text;
begin
    select role into existing
    from memberships
    where tenant_id = p_tenant and user_id = p_user;

    if existing is not null then
        return existing;
    end if;

    insert into memberships (tenant_id, user_id, role)
    values (p_tenant, p_user, p_role);
    return p_role;
end;
$$;

-- The API resolves a caller's memberships before any tenant context exists, so
-- this one read needs the same treatment. Scoped to a single user id.
create or replace function app.tenants_for_user(p_user uuid)
returns setof tenants
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select t.* from tenants t
    join memberships m on m.tenant_id = t.id
    where m.user_id = p_user
    order by t.name;
$$;

revoke all on function app.create_tenant_with_owner(text, text, char, text, char, text[], uuid)
    from public;
revoke all on function app.accept_invite(uuid, uuid, text) from public;
revoke all on function app.tenants_for_user(uuid) from public;

grant execute on function app.create_tenant_with_owner(text, text, char, text, char, text[], uuid)
    to dealerai_app;
grant execute on function app.accept_invite(uuid, uuid, text) to dealerai_app;
grant execute on function app.tenants_for_user(uuid) to dealerai_app, authenticated;
