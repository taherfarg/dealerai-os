"""The runs API.

Starting a run is a 202: planning is a Pro call and execution is many more, so
a browser timeout must never be what decides whether a dealer's campaign
happens.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from conftest import TENANT_A, TENANT_B, USER_A, USER_B, reseed
from dealerai.agents import base
from dealerai.ai.models import TaskKind
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


class Anything(BaseModel):
    model_config = {"extra": "allow"}


class Noop:
    name = "noop"
    input_schema = Anything
    output_schema = Anything
    task_kind = TaskKind.ANALYSIS
    action = None

    async def run(self, inp: Anything, ctx: base.AgentContext) -> base.AgentResult:
        return base.AgentResult(status="ok", output={})


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed())
    saved = dict(base._REGISTRY)
    base._REGISTRY.clear()
    base.register(Noop())  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c
    base._REGISTRY.clear()
    base._REGISTRY.update(saved)


def auth(user: uuid.UUID = USER_A, tenant: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user, secret=SECRET)}",
        "X-Tenant-Id": str(tenant),
    }


DAG: dict[str, Any] = {
    "goal": "sell the MG6",
    "autonomy": "autopilot",
    "tasks": [
        {"task_key": "t1", "agent": "noop", "depends_on": [], "input": {}},
        {"task_key": "t2", "agent": "noop", "depends_on": ["t1"], "input": {"from_task": "t1"}},
    ],
}


def test_starting_a_run_returns_before_it_has_happened(client: TestClient) -> None:
    response = client.post("/v1/runs", json=DAG, headers=auth())
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["goal"] == "sell the MG6"
    assert body["finished_at"] is None


def test_a_started_run_is_queued_not_executed_in_the_request(client: TestClient) -> None:
    """The HTTP handler must not run agents. It emits one event and returns."""
    run_id = client.post("/v1/runs", json=DAG, headers=auth()).json()["id"]
    detail = client.get(f"/v1/runs/{run_id}", headers=auth()).json()
    assert [t["status"] for t in detail["tasks"]] == ["pending", "pending"]


def test_the_detail_view_shows_every_task(client: TestClient) -> None:
    run_id = client.post("/v1/runs", json=DAG, headers=auth()).json()["id"]
    detail = client.get(f"/v1/runs/{run_id}", headers=auth()).json()
    assert [t["task_key"] for t in detail["tasks"]] == ["t1", "t2"]
    assert detail["tasks"][1]["depends_on"] == ["t1"]


def test_an_unrunnable_dag_is_refused(client: TestClient) -> None:
    bad = {**DAG, "tasks": [{"task_key": "t1", "agent": "ghost", "depends_on": [], "input": {}}]}
    response = client.post("/v1/runs", json=bad, headers=auth())
    assert response.status_code == 422
    assert "no such agent" in response.text
    goals = [r["goal"] for r in client.get("/v1/runs", headers=auth()).json()]
    assert "sell the MG6" not in goals, "a rejected plan still created a run"


def test_a_cycle_is_refused(client: TestClient) -> None:
    bad = {
        **DAG,
        "tasks": [
            {"task_key": "t1", "agent": "noop", "depends_on": ["t2"], "input": {}},
            {"task_key": "t2", "agent": "noop", "depends_on": ["t1"], "input": {}},
        ],
    }
    assert client.post("/v1/runs", json=bad, headers=auth()).status_code == 422


def test_autonomy_defaults_to_the_tenants_own_mode(client: TestClient) -> None:
    """A run that silently ran in autopilot because the caller omitted a field
    is the worst possible default."""
    body = {k: v for k, v in DAG.items() if k != "autonomy"}
    run = client.post("/v1/runs", json=body, headers=auth()).json()
    assert run["autonomy"] == "copilot", "the seeded tenant's default"


def test_another_tenants_run_is_not_visible(client: TestClient) -> None:
    run_id = client.post("/v1/runs", json=DAG, headers=auth()).json()["id"]
    response = client.get(f"/v1/runs/{run_id}", headers=auth(USER_B, TENANT_B))
    assert response.status_code == 404, "cross-tenant reads are 404, never 403"


def test_starting_a_run_needs_more_than_a_viewer(client: TestClient) -> None:
    response = client.post("/v1/runs", json=DAG, headers=auth(USER_B, TENANT_A))
    assert response.status_code == 404


def test_runs_are_listed_newest_first(client: TestClient) -> None:
    first = client.post("/v1/runs", json={**DAG, "goal": "first"}, headers=auth()).json()["id"]
    second = client.post("/v1/runs", json={**DAG, "goal": "second"}, headers=auth()).json()["id"]
    listed = [r["id"] for r in client.get("/v1/runs", headers=auth()).json()]
    assert listed[:2] == [second, first]
