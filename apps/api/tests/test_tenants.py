"""Route tests for tenancy, roles, and invitations.

These are synchronous because TestClient is synchronous, so database setup goes
through asyncio.run helpers rather than the async `seeded` fixture.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import jwt
import pytest
from fastapi.testclient import TestClient

from conftest import TENANT_A, TENANT_B, USER_A, USER_B, reseed
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def _exec(sql: str, *args: object) -> None:
    async def run() -> None:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            await conn.execute(sql, *args)
        finally:
            await conn.close()

    asyncio.run(run())


def set_role(tenant: uuid.UUID, user: uuid.UUID, role: str) -> None:
    _exec(
        """insert into memberships (tenant_id, user_id, role) values ($1,$2,$3)
           on conflict (tenant_id, user_id) do update set role = excluded.role""",
        tenant,
        user,
        role,
    )


def seed_user(user_id: uuid.UUID) -> None:
    # Email is derived from the id: auth.users.email is unique, and a fixed
    # address would silently no-op on the second run, leaving the FK dangling.
    _exec(
        "insert into auth.users (id, email) values ($1,$2) on conflict do nothing",
        user_id,
        f"{user_id}@test.local",
    )


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed())
    with TestClient(app) as c:
        yield c


def auth(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
    *,
    email: str | None = None,
    name: str | None = None,
) -> dict[str, str]:
    token = mint_test_token(user_id, secret=SECRET, email=email, name=name)
    headers = {"Authorization": f"Bearer {token}"}
    if tenant_id is not None:
        headers["X-Tenant-Id"] = str(tenant_id)
    return headers


def _fetch(sql: str, *args: object) -> list[asyncpg.Record]:
    async def run() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return list(await conn.fetch(sql, *args))
        finally:
            await conn.close()

    return asyncio.run(run())


INVITED = "new@dealer.test"


def _invite(client: TestClient, **body: object) -> str:
    response = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": INVITED, "role": "sales", **body},
        headers=auth(USER_A, TENANT_A),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


def _join(client: TestClient, token: str, **claims: str) -> Any:
    return client.post(
        "/v1/invites/accept",
        json={"token": token},
        headers=auth(USER_B, **({"email": INVITED} | claims)),
    )


# --------------------------------------------------------------------------
# authentication
# --------------------------------------------------------------------------


def test_missing_token_is_401(client: TestClient) -> None:
    r = client.get(f"/v1/tenants/{TENANT_A}", headers={"X-Tenant-Id": str(TENANT_A)})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")


def test_garbage_token_is_401(client: TestClient) -> None:
    r = client.get(
        f"/v1/tenants/{TENANT_A}",
        headers={"Authorization": "Bearer not-a-jwt", "X-Tenant-Id": str(TENANT_A)},
    )
    assert r.status_code == 401


def test_expired_token_is_401(client: TestClient) -> None:
    token = mint_test_token(USER_A, secret=SECRET, expires_in_seconds=-60)
    r = client.get(
        f"/v1/tenants/{TENANT_A}",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(TENANT_A)},
    )
    assert r.status_code == 401


def test_token_signed_with_another_secret_is_401(client: TestClient) -> None:
    token = mint_test_token(USER_A, secret="a" * 48)
    r = client.get(
        f"/v1/tenants/{TENANT_A}",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(TENANT_A)},
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------
# tenant access
# --------------------------------------------------------------------------


def test_member_can_read_their_tenant(client: TestClient) -> None:
    r = client.get(f"/v1/tenants/{TENANT_A}", headers=auth(USER_A, TENANT_A))
    assert r.status_code == 200
    assert r.json()["slug"] == "alpha"


def test_another_tenant_is_404_not_403(client: TestClient) -> None:
    """403 confirms the workspace exists, which makes the endpoint an enumeration oracle."""
    r = client.get(f"/v1/tenants/{TENANT_B}", headers=auth(USER_A, TENANT_B))
    assert r.status_code == 404
    assert "forbidden" not in r.text.lower()


def test_list_only_returns_my_tenants(client: TestClient) -> None:
    r = client.get("/v1/tenants", headers=auth(USER_A))
    assert r.status_code == 200
    assert {t["slug"] for t in r.json()} == {"alpha"}


def test_members_of_another_tenant_are_not_visible(client: TestClient) -> None:
    r = client.get(f"/v1/tenants/{TENANT_B}/members", headers=auth(USER_A, TENANT_B))
    assert r.status_code == 404


def test_usage_reports_spend_against_budget(client: TestClient) -> None:
    r = client.get(f"/v1/tenants/{TENANT_A}/usage", headers=auth(USER_A, TENANT_A))
    assert r.status_code == 200
    body = r.json()
    assert body["budget_usd"] == 150.0
    assert body["remaining_usd"] == pytest.approx(body["budget_usd"] - body["spent_usd"])


# --------------------------------------------------------------------------
# creating a workspace
# --------------------------------------------------------------------------


def test_create_tenant_makes_the_caller_owner(client: TestClient) -> None:
    new_user = uuid.uuid4()
    seed_user(new_user)

    r = client.post(
        "/v1/tenants", json={"name": "Gamma Motors", "slug": "gamma"}, headers=auth(new_user)
    )
    assert r.status_code == 201, r.text
    tenant_id = uuid.UUID(r.json()["id"])

    members = client.get(f"/v1/tenants/{tenant_id}/members", headers=auth(new_user, tenant_id))
    assert members.status_code == 200
    assert [m["role"] for m in members.json()] == ["owner"]


def test_create_tenant_also_creates_a_brand_profile(client: TestClient) -> None:
    """Onboarding writes into brand_profiles immediately; a missing row is a 500 later."""
    r = client.post(
        "/v1/tenants", json={"name": "Delta Motors", "slug": "delta"}, headers=auth(USER_A)
    )
    assert r.status_code == 201
    tenant_id = uuid.UUID(r.json()["id"])

    async def has_brand() -> bool:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return bool(
                await conn.fetchval("select 1 from brand_profiles where tenant_id = $1", tenant_id)
            )
        finally:
            await conn.close()

    assert asyncio.run(has_brand())


def test_duplicate_slug_is_409(client: TestClient) -> None:
    r = client.post(
        "/v1/tenants", json={"name": "Alpha Again", "slug": "alpha"}, headers=auth(USER_A)
    )
    assert r.status_code == 409


@pytest.mark.parametrize("slug", ["login", "auth", "onboarding", "accept-invite", "icon"])
def test_a_workspace_cannot_take_an_address_the_app_answers_at(
    client: TestClient, slug: str
) -> None:
    """The app's own page would answer there, and the workspace could never be
    opened. The same answer as a slug somebody has: it is taken."""
    r = client.post("/v1/tenants", json={"name": "Icon Motors", "slug": slug}, headers=auth(USER_A))
    assert r.status_code == 409, r.text
    assert slug in r.json()["detail"]


def test_invalid_slug_is_rejected(client: TestClient) -> None:
    r = client.post(
        "/v1/tenants", json={"name": "Bad Slug", "slug": "Not A Slug!"}, headers=auth(USER_A)
    )
    assert r.status_code == 400
    assert r.json()["errors"][0]["field"] == "slug"


# --------------------------------------------------------------------------
# roles
# --------------------------------------------------------------------------


def test_viewer_cannot_change_settings(client: TestClient) -> None:
    set_role(TENANT_A, USER_B, "viewer")
    r = client.patch(
        f"/v1/tenants/{TENANT_A}", json={"name": "Renamed"}, headers=auth(USER_B, TENANT_A)
    )
    assert r.status_code == 403


def test_viewer_can_still_read(client: TestClient) -> None:
    set_role(TENANT_A, USER_B, "viewer")
    r = client.get(f"/v1/tenants/{TENANT_A}", headers=auth(USER_B, TENANT_A))
    assert r.status_code == 200


def test_admin_can_change_settings(client: TestClient) -> None:
    set_role(TENANT_A, USER_B, "admin")
    r = client.patch(
        f"/v1/tenants/{TENANT_A}",
        json={"autonomy_mode": "assisted"},
        headers=auth(USER_B, TENANT_A),
    )
    assert r.status_code == 200
    assert r.json()["autonomy_mode"] == "assisted"


def test_autonomy_rules_round_trip(client: TestClient) -> None:
    rules = {"ads": {"max_daily_aed": 500}, "publishing": {"max_posts_per_day": 4}}
    r = client.patch(
        f"/v1/tenants/{TENANT_A}", json={"autonomy_rules": rules}, headers=auth(USER_A, TENANT_A)
    )
    assert r.status_code == 200
    assert r.json()["autonomy_rules"] == rules


# --------------------------------------------------------------------------
# invitations
# --------------------------------------------------------------------------


def test_owner_can_invite_and_the_link_is_redeemable(client: TestClient) -> None:
    accepted = _join(client, _invite(client))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "sales"


def test_a_forwarded_invitation_is_refused(client: TestClient) -> None:
    """Anybody holding the link joined with any account."""
    refused = _join(client, _invite(client), email="someone.else@dealer.test")
    assert refused.status_code == 403
    assert not _fetch(
        "select 1 from memberships where tenant_id = $1 and user_id = $2", TENANT_A, USER_B
    )


def test_an_address_is_compared_as_an_address(client: TestClient) -> None:
    token = _invite(client, email="New@Dealer.test")
    assert _join(client, token, email="new@dealer.TEST").status_code == 200


def test_joining_puts_them_in_the_invited_teams(client: TestClient) -> None:
    team = uuid.uuid4()
    _exec("insert into teams (id, tenant_id, name) values ($1, $2, 'Local')", team, TENANT_A)
    assert _join(client, _invite(client, team_ids=[str(team)])).status_code == 200
    rows = _fetch("select team_id from team_members where user_id = $1", USER_B)
    assert [row["team_id"] for row in rows] == [team]


def test_an_invitation_names_only_this_workspaces_teams(client: TestClient) -> None:
    theirs = uuid.uuid4()
    _exec("insert into teams (id, tenant_id, name) values ($1, $2, 'Export')", theirs, TENANT_B)
    response = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": INVITED, "role": "sales", "team_ids": [str(theirs)]},
        headers=auth(USER_A, TENANT_A),
    )
    assert response.status_code == 422


def test_joining_remembers_who_they_are(client: TestClient) -> None:
    """Only the seed wrote profiles: a real salesperson was nameless everywhere."""
    _join(client, _invite(client), name="Layla Hassan")
    [profile] = _fetch("select email, full_name from profiles where id = $1", USER_B)
    assert (profile["email"], profile["full_name"]) == (INVITED, "Layla Hassan")


def test_creating_a_workspace_remembers_its_owner(client: TestClient) -> None:
    response = client.post(
        "/v1/tenants",
        json={"name": "Test Motors", "slug": f"test-{uuid.uuid4().hex[:8]}"},
        headers=auth(USER_B, email="owner@dealer.test", name="Khalid Al Suwaidi"),
    )
    assert response.status_code == 201, response.text
    [profile] = _fetch("select full_name from profiles where id = $1", USER_B)
    assert profile["full_name"] == "Khalid Al Suwaidi"


def test_the_link_names_the_workspace_and_joining_says_where_to_go(client: TestClient) -> None:
    token = _invite(client)
    claims = jwt.decode(token, options={"verify_signature": False})
    tenant = client.get(f"/v1/tenants/{TENANT_A}", headers=auth(USER_A, TENANT_A)).json()
    assert claims["tenant_name"] == tenant["name"]
    assert claims["email"] == INVITED
    assert _join(client, token).json()["tenant_slug"] == tenant["slug"]


def test_an_invitation_is_for_a_salesperson_unless_it_says_otherwise(client: TestClient) -> None:
    response = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": INVITED},
        headers=auth(USER_A, TENANT_A),
    )
    assert response.json()["role"] == "sales"


def test_replaying_an_invite_neither_duplicates_nor_reroles(client: TestClient) -> None:
    """A leaked link must not be able to promote or demote someone."""
    invite = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": "b@dealer.test", "role": "viewer"},
        headers=auth(USER_A, TENANT_A),
    )
    token = invite.json()["token"]

    invited = auth(USER_B, email="b@dealer.test")
    first = client.post("/v1/invites/accept", json={"token": token}, headers=invited)
    second = client.post("/v1/invites/accept", json={"token": token}, headers=invited)
    assert first.status_code == second.status_code == 200
    assert first.json()["role"] == second.json()["role"] == "viewer"

    members = client.get(f"/v1/tenants/{TENANT_A}/members", headers=auth(USER_A, TENANT_A))
    assert len(members.json()) == 2, "replaying the invite created a duplicate membership"


def test_cannot_invite_above_your_own_role(client: TestClient) -> None:
    """A marketer handing out owner links is a privilege-escalation path."""
    set_role(TENANT_A, USER_B, "marketer")
    r = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": "x@dealer.test", "role": "owner"},
        headers=auth(USER_B, TENANT_A),
    )
    assert r.status_code == 403


def test_viewer_cannot_invite_at_all(client: TestClient) -> None:
    set_role(TENANT_A, USER_B, "viewer")
    r = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": "x@dealer.test", "role": "viewer"},
        headers=auth(USER_B, TENANT_A),
    )
    assert r.status_code == 403


def test_garbage_invite_token_is_401(client: TestClient) -> None:
    r = client.post("/v1/invites/accept", json={"token": "nope"}, headers=auth(USER_B))
    assert r.status_code == 401


def test_a_user_token_is_not_a_valid_invite(client: TestClient) -> None:
    """Both are signed with the same secret; only the `kind` claim separates them."""
    not_an_invite = mint_test_token(USER_B, secret=SECRET)
    r = client.post("/v1/invites/accept", json={"token": not_an_invite}, headers=auth(USER_B))
    assert r.status_code == 401


def test_last_owner_cannot_be_removed(client: TestClient) -> None:
    """Removing the only owner orphans the workspace: nobody left who can invite."""
    r = client.delete(f"/v1/tenants/{TENANT_A}/members/{USER_A}", headers=auth(USER_A, TENANT_A))
    assert r.status_code == 409


def test_a_second_owner_can_be_removed(client: TestClient) -> None:
    set_role(TENANT_A, USER_B, "owner")
    r = client.delete(f"/v1/tenants/{TENANT_A}/members/{USER_B}", headers=auth(USER_A, TENANT_A))
    assert r.status_code == 204
