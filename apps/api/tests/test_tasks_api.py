"""Tasks: whose they are, which bucket they fall in, and what completing means."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.routes.tasks import window

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


async def _seed() -> uuid.UUID:
    """Pollux time: the workspace is in Dubai, four hours ahead of the server."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("update tenants set timezone = 'Asia/Dubai' where id = $1", TENANT_A)
        contact = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id)
               values ($1, 'Omar Al Mazrouei', $2, $3) returning id""",
            TENANT_A,
            SALES_1,
            TEAM_LOCAL,
        )
        return uuid.UUID(str(contact))
    finally:
        await conn.close()


@pytest.fixture
def contact_id(_migrated: None) -> uuid.UUID:
    return asyncio.run(_seed())


@pytest.fixture
def client(contact_id: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _create(
    client: TestClient,
    *,
    title: str,
    due_at: datetime,
    user: uuid.UUID = SALES_1,
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        "/v1/tasks",
        json={"title": title, "due_at": due_at.isoformat(), **extra},
        headers=_auth(user),
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _bucket(client: TestClient, bucket: str, user: uuid.UUID = SALES_1, **query: str) -> list[str]:
    extra = "".join(f"&{key}={value}" for key, value in query.items())
    response = client.get(f"/v1/tasks?bucket={bucket}{extra}", headers=_auth(user))
    assert response.status_code == 200, response.text
    return [task["title"] for task in response.json()]


def _later_today() -> datetime:
    """A moment that is still today in Dubai, whenever the suite runs.

    `datetime.now()` is not it: "today" starts at now and ends at local
    midnight, so a task due at this instant is overdue by the time the list is
    asked — which is right for the product and useless for a fixture.
    """
    start, end = window("today", "Asia/Dubai", datetime.now(UTC))
    assert start is not None and end is not None
    return start + (end - start) / 2


def test_a_task_due_this_evening_in_dubai_is_due_today(client: TestClient) -> None:
    """The test that fails if anybody uses the server's clock."""
    _create(client, title="Call Omar back", due_at=_later_today())
    assert "Call Omar back" in _bucket(client, "today")
    assert "Call Omar back" not in _bucket(client, "upcoming")


def test_yesterday_s_unfinished_task_is_overdue(client: TestClient) -> None:
    _create(client, title="Send the quote", due_at=datetime.now(UTC) - timedelta(days=1))
    assert _bucket(client, "overdue") == ["Send the quote"]
    assert _bucket(client, "today") == []


def test_next_week_is_upcoming(client: TestClient) -> None:
    _create(client, title="Registration renewal", due_at=datetime.now(UTC) + timedelta(days=7))
    assert _bucket(client, "upcoming") == ["Registration renewal"]


def test_completing_a_task_stamps_when_and_moves_it(client: TestClient) -> None:
    task = _create(client, title="Call Omar back", due_at=_later_today())
    done = client.patch(f"/v1/tasks/{task['id']}", json={"status": "done"}, headers=_auth(SALES_1))
    assert done.status_code == 200, done.text
    assert done.json()["completed_at"] is not None
    assert _bucket(client, "today") == []
    assert _bucket(client, "done") == ["Call Omar back"]


def test_completing_it_again_changes_nothing(client: TestClient) -> None:
    task = _create(client, title="Call Omar back", due_at=_later_today())
    first = client.patch(
        f"/v1/tasks/{task['id']}", json={"status": "done"}, headers=_auth(SALES_1)
    ).json()
    again = client.patch(
        f"/v1/tasks/{task['id']}", json={"status": "done"}, headers=_auth(SALES_1)
    ).json()
    assert again["completed_at"] == first["completed_at"]


def test_undoing_a_completion_is_an_ordinary_edit(client: TestClient) -> None:
    """Which is what lets the Undo toast work without an endpoint of its own."""
    task = _create(client, title="Call Omar back", due_at=_later_today())
    client.patch(f"/v1/tasks/{task['id']}", json={"status": "done"}, headers=_auth(SALES_1))
    undone = client.patch(
        f"/v1/tasks/{task['id']}", json={"status": "open"}, headers=_auth(SALES_1)
    ).json()
    assert undone["completed_at"] is None
    assert _bucket(client, "today") == ["Call Omar back"]


def test_snoozing_moves_it_between_buckets(client: TestClient) -> None:
    task = _create(client, title="Send the quote", due_at=datetime.now(UTC) - timedelta(days=1))
    assert _bucket(client, "overdue") == ["Send the quote"]
    client.patch(
        f"/v1/tasks/{task['id']}",
        json={"due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
        headers=_auth(SALES_1),
    )
    assert _bucket(client, "overdue") == []
    assert _bucket(client, "upcoming") == ["Send the quote"]


def test_a_task_is_mine_unless_it_says_otherwise(client: TestClient) -> None:
    task = _create(client, title="Call Omar back", due_at=_later_today())
    assert task["assignee"]["name"] == "sales1"


def test_a_salesperson_sees_only_their_own(client: TestClient) -> None:
    _create(client, title="Mine", due_at=_later_today())
    _create(client, title="Theirs", due_at=_later_today(), user=SALES_2)
    assert _bucket(client, "today") == ["Mine"]
    assert _bucket(client, "today", user=SALES_2) == ["Theirs"]


def test_asking_for_the_team_as_a_salesperson_still_answers_with_mine(
    client: TestClient,
) -> None:
    _create(client, title="Mine", due_at=_later_today())
    _create(client, title="Theirs", due_at=_later_today(), user=SALES_2)
    assert _bucket(client, "today", assignee="team") == ["Mine"]


def test_a_manager_can_ask_for_the_team_s(client: TestClient) -> None:
    _create(client, title="Mine", due_at=_later_today())
    _create(client, title="Theirs", due_at=_later_today(), user=SALES_2)
    assert set(_bucket(client, "today", user=MANAGER, assignee="team")) == {"Mine", "Theirs"}
    assert _bucket(client, "today", user=MANAGER) == [], "the manager's own day is their own"


def test_a_task_about_a_customer_i_cannot_see_is_404(client: TestClient) -> None:
    hidden = asyncio.run(_a_customer_of(SALES_2))
    response = client.post(
        "/v1/tasks",
        json={
            "title": "Snoop",
            "due_at": _later_today().isoformat(),
            "contact_id": str(hidden),
        },
        headers=_auth(SALES_1),
    )
    assert response.status_code == 404, response.text


async def _a_customer_of(owner: uuid.UUID) -> uuid.UUID:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return uuid.UUID(  # type: ignore[no-any-return]
            str(
                await conn.fetchval(
                    """insert into contacts (tenant_id, full_name, owner_id, team_id)
                       values ($1, 'Someone else', $2, $3) returning id""",
                    TENANT_A,
                    owner,
                    TEAM_LOCAL,
                )
            )
        )
    finally:
        await conn.close()


def test_a_task_for_a_colleague_outside_the_workspace_is_404(client: TestClient) -> None:
    response = client.post(
        "/v1/tasks",
        json={
            "title": "Not yours",
            "due_at": _later_today().isoformat(),
            "assignee_id": str(uuid.uuid4()),
        },
        headers=_auth(OWNER),
    )
    assert response.status_code == 404, response.text


def test_editing_a_colleague_s_task_is_404(client: TestClient) -> None:
    theirs = _create(client, title="Theirs", due_at=_later_today(), user=SALES_2)
    response = client.patch(
        f"/v1/tasks/{theirs['id']}", json={"status": "done"}, headers=_auth(SALES_1)
    )
    assert response.status_code == 404, response.text


def test_the_day_starts_at_midnight_where_the_dealership_is() -> None:
    """Directly, because the boundary is the whole point and a route test can
    only see one side of it."""
    # 21:00 in Dubai is 17:00 UTC, and still today for the person in Dubai.
    evening = datetime(2026, 9, 21, 17, 0, tzinfo=UTC)
    start, end = window("today", "Asia/Dubai", evening)
    assert start == evening
    assert end == datetime(2026, 9, 21, 20, 0, tzinfo=UTC), "midnight in Dubai, in UTC"

    # 23:00 UTC is already tomorrow morning in Dubai.
    late = datetime(2026, 9, 21, 23, 0, tzinfo=UTC)
    _, tomorrow_end = window("today", "Asia/Dubai", late)
    assert tomorrow_end == datetime(2026, 9, 22, 20, 0, tzinfo=UTC)


def test_an_unknown_timezone_falls_back_rather_than_breaking_the_list() -> None:
    start, end = window("today", "Mars/Olympus", datetime(2026, 9, 21, 17, 0, tzinfo=UTC))
    assert start is not None and end is not None
