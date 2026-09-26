"""The board's shape: who may change it, and what it refuses to lose."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, TENANT_B, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed_with_people())
    with TestClient(app) as test_client:
        yield test_client


def _board(client: TestClient, user: uuid.UUID = OWNER) -> dict[str, Any]:
    response = client.get("/v1/pipelines", headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()[0]  # type: ignore[no-any-return]


def _stages(pipeline: dict[str, Any]) -> list[str]:
    return [stage["name"] for stage in pipeline["stages"]]


async def _a_lead_on(stage_id: str, pipeline_id: str) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        contact = await conn.fetchval(
            "select id from contacts where tenant_id = $1 limit 1", TENANT_A
        )
        await conn.execute(
            """insert into leads (tenant_id, contact_id, pipeline_id, stage_id)
               values ($1, $2, $3, $4)""",
            TENANT_A,
            contact,
            uuid.UUID(pipeline_id),
            uuid.UUID(stage_id),
        )
    finally:
        await conn.close()


def test_a_workspace_starts_with_a_board_leads_can_sit_on(client: TestClient) -> None:
    """A workspace whose first lead fails is a workspace that looks broken."""
    board = _board(client)
    assert board["is_default"] is True
    assert _stages(board)[:2] == ["New", "Contacted"]
    assert [stage["category"] for stage in board["stages"]][-2:] == ["won", "lost"]


def test_stages_come_back_in_board_order(client: TestClient) -> None:
    positions = [stage["position"] for stage in _board(client)["stages"]]
    assert positions == sorted(positions)


def test_renaming_and_reordering_keeps_the_leads_where_they_are(client: TestClient) -> None:
    board = _board(client)
    qualified = next(stage for stage in board["stages"] if stage["name"] == "Qualified")
    asyncio.run(_a_lead_on(qualified["id"], board["id"]))

    reordered = [
        {"id": stage["id"], "name": stage["name"], "category": stage["category"]}
        for stage in board["stages"]
    ]
    next(stage for stage in reordered if stage["id"] == qualified["id"])["name"] = (
        "Qualified (docs in)"
    )
    appointment = next(stage for stage in reordered if stage["name"] == "Appointment")
    reordered.remove(appointment)
    reordered.insert(1, appointment)

    response = client.put(
        f"/v1/pipelines/{board['id']}/stages",
        json={"stages": reordered},
        headers=_auth(OWNER),
    )
    assert response.status_code == 200, response.text
    assert _stages(response.json())[:4] == [
        "New",
        "Appointment",
        "Contacted",
        "Qualified (docs in)",
    ]
    assert (
        next(stage for stage in response.json()["stages"] if stage["id"] == qualified["id"])["name"]
        == "Qualified (docs in)"
    ), "the lead's stage was renamed, not replaced"


def test_a_new_stage_can_be_added_in_the_middle(client: TestClient) -> None:
    board = _board(client)
    stages = [
        {"id": stage["id"], "name": stage["name"], "category": stage["category"]}
        for stage in board["stages"]
    ]
    stages.insert(2, {"name": "Test drive booked", "category": "open"})

    response = client.put(
        f"/v1/pipelines/{board['id']}/stages", json={"stages": stages}, headers=_auth(OWNER)
    )
    assert response.status_code == 200, response.text
    assert _stages(response.json())[2] == "Test drive booked"


def test_deleting_a_stage_that_still_holds_leads_says_how_many(client: TestClient) -> None:
    board = _board(client)
    doomed = next(stage for stage in board["stages"] if stage["name"] == "Contacted")
    for _ in range(2):
        asyncio.run(_a_lead_on(doomed["id"], board["id"]))

    kept = [
        {"id": stage["id"], "name": stage["name"], "category": stage["category"]}
        for stage in board["stages"]
        if stage["id"] != doomed["id"]
    ]
    response = client.put(
        f"/v1/pipelines/{board['id']}/stages", json={"stages": kept}, headers=_auth(OWNER)
    )
    assert response.status_code == 409, response.text
    problem = response.json()
    assert problem["type"].endswith("stage-in-use")
    assert "2 leads" in problem["detail"]
    assert _stages(_board(client)) == _stages(board), "a refused change changed nothing"


def test_an_empty_stage_can_be_removed(client: TestClient) -> None:
    board = _board(client)
    kept = [
        {"id": stage["id"], "name": stage["name"], "category": stage["category"]}
        for stage in board["stages"]
        if stage["name"] != "Appointment"
    ]
    response = client.put(
        f"/v1/pipelines/{board['id']}/stages", json={"stages": kept}, headers=_auth(OWNER)
    )
    assert response.status_code == 200, response.text
    assert "Appointment" not in _stages(response.json())


@pytest.mark.parametrize(
    "stages,because",
    [
        ([("New", "open"), ("Won", "won"), ("Also won", "won"), ("Lost", "lost")], "two won"),
        ([("New", "open"), ("Won", "won")], "nowhere to lose"),
        ([("Won", "won"), ("Lost", "lost")], "nowhere to live"),
    ],
)
def test_a_board_that_cannot_work_is_refused(
    client: TestClient, stages: list[tuple[str, str]], because: str
) -> None:
    board = _board(client)
    response = client.put(
        f"/v1/pipelines/{board['id']}/stages",
        json={"stages": [{"name": name, "category": category} for name, category in stages]},
        headers=_auth(OWNER),
    )
    assert response.status_code == 422, f"{because}: {response.text}"


def test_a_stage_from_another_board_is_refused(client: TestClient) -> None:
    board = _board(client)
    stages = [
        {"id": stage["id"], "name": stage["name"], "category": stage["category"]}
        for stage in board["stages"]
    ]
    stages[0]["id"] = str(uuid.uuid4())
    response = client.put(
        f"/v1/pipelines/{board['id']}/stages", json={"stages": stages}, headers=_auth(OWNER)
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("who", [SALES_1, MANAGER])
def test_reshaping_the_board_is_an_owner_s_decision(client: TestClient, who: uuid.UUID) -> None:
    """A manager runs the desk; the shape of the pipeline is the workspace's,
    and pipeline.edit_stages says so (core/permissions.py)."""
    board = _board(client, who)
    response = client.put(
        f"/v1/pipelines/{board['id']}/stages",
        json={
            "stages": [
                {"name": "Mine", "category": "open"},
                {"name": "Won", "category": "won"},
                {"name": "Lost", "category": "lost"},
            ]
        },
        headers=_auth(who),
    )
    assert response.status_code == 403, response.text


def test_another_tenant_s_board_is_404(client: TestClient) -> None:
    theirs = asyncio.run(_beta_pipeline())
    response = client.put(
        f"/v1/pipelines/{theirs}/stages",
        json={
            "stages": [
                {"name": "Mine", "category": "open"},
                {"name": "Won", "category": "won"},
                {"name": "Lost", "category": "lost"},
            ]
        },
        headers=_auth(OWNER),
    )
    assert response.status_code == 404, response.text


async def _beta_pipeline() -> uuid.UUID:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return uuid.UUID(  # type: ignore[no-any-return]
            str(await conn.fetchval("select id from pipelines where tenant_id = $1", TENANT_B))
        )
    finally:
        await conn.close()
