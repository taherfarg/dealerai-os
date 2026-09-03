from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import TENANT_A, TENANT_B, USER_A, USER_B, reseed
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.orchestrator.approvals import approver_role, request_approval

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed())
    with TestClient(app) as c:
        yield c


def auth(user_id: uuid.UUID, tenant_id: uuid.UUID | None = TENANT_A) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}"}
    if tenant_id is not None:
        headers["X-Tenant-Id"] = str(tenant_id)
    return headers


def set_role(user: uuid.UUID, role: str, tenant: uuid.UUID = TENANT_A) -> None:
    _run(
        """insert into memberships (tenant_id, user_id, role) values ($1,$2,$3)
           on conflict (tenant_id, user_id) do update set role = excluded.role""",
        tenant,
        user,
        role,
    )


def _run(sql: str, *args: object) -> None:
    async def go() -> None:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            await conn.execute(sql, *args)
        finally:
            await conn.close()

    asyncio.run(go())


def make_approval(
    kind: str = "publish_content",
    *,
    tenant: uuid.UUID = TENANT_A,
    summary: str = "Publish 6 posts to Instagram",
    expires_in_hours: int = 72,
) -> uuid.UUID:
    async def go() -> uuid.UUID:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            await conn.set_type_codec(
                "jsonb",
                encoder=__import__("json").dumps,
                decoder=__import__("json").loads,
                schema="pg_catalog",
            )
            async with conn.transaction():
                return await request_approval(
                    conn,
                    tenant_id=tenant,
                    kind=kind,
                    summary=summary,
                    payload={"content_ids": ["a", "b"]},
                    ttl_hours=expires_in_hours,
                )
        finally:
            await conn.close()

    return asyncio.run(go())


# --------------------------------------------------------------------------
# creation and listing
# --------------------------------------------------------------------------


def test_requested_approval_appears_in_the_pending_queue(client: TestClient) -> None:
    approval_id = make_approval()
    r = client.get("/v1/approvals", headers=auth(USER_A))
    assert r.status_code == 200
    ids = [a["id"] for a in r.json()]
    assert str(approval_id) in ids


def test_requesting_an_approval_emits_an_event(client: TestClient) -> None:
    make_approval()

    async def count() -> int:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return await conn.fetchval(
                "select count(*) from events where event_type = 'approval.requested'"
            )
        finally:
            await conn.close()

    assert asyncio.run(count()) == 1


def test_another_tenants_approval_is_invisible(client: TestClient) -> None:
    other = make_approval(tenant=TENANT_B)
    r = client.get("/v1/approvals", headers=auth(USER_A))
    assert str(other) not in [a["id"] for a in r.json()]

    direct = client.get(f"/v1/approvals/{other}", headers=auth(USER_A))
    assert direct.status_code == 404


def test_the_payload_survives_the_round_trip(client: TestClient) -> None:
    approval_id = make_approval()
    r = client.get(f"/v1/approvals/{approval_id}", headers=auth(USER_A))
    assert r.json()["payload"] == {"content_ids": ["a", "b"]}


def test_required_role_is_reported_so_the_ui_can_hide_what_you_cannot_act_on(
    client: TestClient,
) -> None:
    budget = make_approval("adjust_budget", summary="Raise MG7 budget to AED 500/day")
    r = client.get(f"/v1/approvals/{budget}", headers=auth(USER_A))
    assert r.json()["required_role"] == "admin"


# --------------------------------------------------------------------------
# deciding
# --------------------------------------------------------------------------


def test_approve_records_the_decision(client: TestClient) -> None:
    approval_id = make_approval()
    r = client.post(
        f"/v1/approvals/{approval_id}/approve", json={"note": "looks good"}, headers=auth(USER_A)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["decision_note"] == "looks good"
    assert body["decided_at"] is not None


def test_reject_records_the_decision(client: TestClient) -> None:
    approval_id = make_approval()
    r = client.post(
        f"/v1/approvals/{approval_id}/reject", json={"note": "wrong car"}, headers=auth(USER_A)
    )
    assert r.json()["status"] == "rejected"


def test_deciding_emits_approval_decided(client: TestClient) -> None:
    approval_id = make_approval()
    client.post(f"/v1/approvals/{approval_id}/approve", json={}, headers=auth(USER_A))

    async def payload() -> dict[str, object] | None:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return await conn.fetchval(
                "select payload from events where event_type = 'approval.decided'"
            )
        finally:
            await conn.close()

    import json

    raw = asyncio.run(payload())
    assert raw is not None
    assert json.loads(raw)["decision"] == "approved"


def test_deciding_twice_is_a_conflict(client: TestClient) -> None:
    approval_id = make_approval()
    first = client.post(f"/v1/approvals/{approval_id}/approve", json={}, headers=auth(USER_A))
    second = client.post(f"/v1/approvals/{approval_id}/reject", json={}, headers=auth(USER_A))
    assert first.status_code == 200
    assert second.status_code == 409
    assert "already approved" in second.text


def test_an_expired_approval_cannot_be_decided(client: TestClient) -> None:
    """A stale prompt about a car that may have sold is not a decision anyone
    should be able to rubber-stamp three days later."""
    approval_id = make_approval(expires_in_hours=-1)

    listed = client.get(f"/v1/approvals/{approval_id}", headers=auth(USER_A))
    assert listed.json()["status"] == "expired"

    decided = client.post(f"/v1/approvals/{approval_id}/approve", json={}, headers=auth(USER_A))
    assert decided.status_code == 409
    assert "expired" in decided.text


def test_expired_approvals_are_not_in_the_pending_queue(client: TestClient) -> None:
    make_approval(expires_in_hours=-1)
    fresh = make_approval(summary="still valid")
    pending = client.get("/v1/approvals", headers=auth(USER_A)).json()
    assert [a["id"] for a in pending] == [str(fresh)]


# --------------------------------------------------------------------------
# who may decide what
# --------------------------------------------------------------------------


def test_money_approvals_need_an_admin(client: TestClient) -> None:
    set_role(USER_B, "marketer")
    budget = make_approval("adjust_budget")
    r = client.post(f"/v1/approvals/{budget}/approve", json={}, headers=auth(USER_B))
    assert r.status_code == 403
    assert "admin" in r.text


def test_a_marketer_can_approve_content(client: TestClient) -> None:
    """Otherwise the approval queue becomes the owner's full-time job and
    Assisted mode stops being usable."""
    set_role(USER_B, "marketer")
    content = make_approval("publish_content")
    r = client.post(f"/v1/approvals/{content}/approve", json={}, headers=auth(USER_B))
    assert r.status_code == 200


def test_a_viewer_can_approve_nothing(client: TestClient) -> None:
    set_role(USER_B, "viewer")
    content = make_approval("publish_content")
    r = client.post(f"/v1/approvals/{content}/approve", json={}, headers=auth(USER_B))
    assert r.status_code == 403


def test_an_unclassified_kind_needs_the_highest_role() -> None:
    """Fail closed: a new approval kind nobody triaged is not a free-for-all."""
    assert approver_role("something_nobody_classified") == "admin"


# --------------------------------------------------------------------------
# bulk
# --------------------------------------------------------------------------


def test_bulk_approve_clears_the_queue(client: TestClient) -> None:
    ids = [make_approval(summary=f"item {i}") for i in range(3)]
    r = client.post(
        "/v1/approvals/bulk",
        json={"ids": [str(i) for i in ids], "decision": "approved"},
        headers=auth(USER_A),
    )
    assert r.status_code == 200
    assert sorted(r.json()["decided"]) == sorted(str(i) for i in ids)
    assert client.get("/v1/approvals", headers=auth(USER_A)).json() == []


def test_bulk_reports_partial_success_instead_of_failing(client: TestClient) -> None:
    """One already-decided item must not sink the other forty-nine."""
    good = make_approval(summary="good")
    already = make_approval(summary="already")
    client.post(f"/v1/approvals/{already}/approve", json={}, headers=auth(USER_A))
    missing = uuid.uuid4()

    r = client.post(
        "/v1/approvals/bulk",
        json={"ids": [str(good), str(already), str(missing)], "decision": "approved"},
        headers=auth(USER_A),
    )
    body = r.json()
    assert body["decided"] == [str(good)]
    assert set(body["skipped"]) == {str(already), str(missing)}
    assert "already" in body["skipped"][str(already)].lower()


def test_bulk_across_tenants_skips_rather_than_leaks(client: TestClient) -> None:
    mine = make_approval()
    theirs = make_approval(tenant=TENANT_B)
    r = client.post(
        "/v1/approvals/bulk",
        json={"ids": [str(mine), str(theirs)], "decision": "approved"},
        headers=auth(USER_A),
    )
    body = r.json()
    assert body["decided"] == [str(mine)]
    assert str(theirs) in body["skipped"]

    # And tenant B's approval is untouched.
    r2 = client.get(f"/v1/approvals/{theirs}", headers=auth(USER_B, TENANT_B))
    assert r2.json()["status"] == "pending"


def test_bulk_rejects_an_empty_list(client: TestClient) -> None:
    r = client.post(
        "/v1/approvals/bulk", json={"ids": [], "decision": "approved"}, headers=auth(USER_A)
    )
    assert r.status_code == 400


def test_ttl_defaults_to_three_days(client: TestClient) -> None:
    approval_id = make_approval()
    r = client.get(f"/v1/approvals/{approval_id}", headers=auth(USER_A))
    expires = datetime.fromisoformat(r.json()["expires_at"])
    assert timedelta(hours=71) < expires - datetime.now(UTC) < timedelta(hours=73)
