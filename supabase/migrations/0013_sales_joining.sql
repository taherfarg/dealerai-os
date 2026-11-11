-- =============================================================================
-- 0013_sales_joining — S7 Part A: somebody who joins a workspace, as they are.
-- Only the seed wrote `profiles`, so anybody who really signed up was nameless
-- on every screen; an invitation carried a role and nothing else, so a
-- salesperson arrived in no team, saw no unassigned customer and was routed no
-- chat. See docs/sales/08-screens.md § 14.
-- =============================================================================

-- Who they are, from their own sign-in: the address is Supabase's, the name is
-- what they typed on sign-up (or Google's). A name they already have is kept.
create or replace function app.remember_profile(p_user uuid, p_email text, p_name text)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
  insert into profiles (id, email, full_name)
  values (p_user, p_email, nullif(btrim(p_name), ''))
  on conflict (id) do update
     set email = coalesce(excluded.email, profiles.email),
         full_name = coalesce(profiles.full_name, excluded.full_name),
         updated_at = now();
$$;

drop function if exists app.accept_invite(uuid, uuid, text);

-- Joining, all of it or none of it. Somebody already a member keeps their role
-- and teams — replaying a link can neither promote nor move anyone — and two
-- clicks at once are one join, not a unique violation.
create or replace function app.accept_invite(
    p_tenant uuid,
    p_user   uuid,
    p_role   text,
    p_teams  uuid[],
    p_email  text,
    p_name   text
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    existing text;
begin
    perform app.remember_profile(p_user, p_email, p_name);

    insert into memberships (tenant_id, user_id, role)
    values (p_tenant, p_user, p_role)
    on conflict (tenant_id, user_id) do nothing;
    if not found then
        select role into existing
          from memberships where tenant_id = p_tenant and user_id = p_user;
        return existing;
    end if;

    -- This workspace's teams only, whatever the token says.
    insert into team_members (tenant_id, team_id, user_id)
    select p_tenant, t.id, p_user
      from teams t
     where t.tenant_id = p_tenant and t.id = any (coalesce(p_teams, '{}'))
    on conflict do nothing;
    return p_role;
end;
$$;

revoke all on function app.remember_profile(uuid, text, text) from public;
revoke all on function app.accept_invite(uuid, uuid, text, uuid[], text, text) from public;
grant execute on function app.remember_profile(uuid, text, text) to dealerai_app;
grant execute on function app.accept_invite(uuid, uuid, text, uuid[], text, text) to dealerai_app;
