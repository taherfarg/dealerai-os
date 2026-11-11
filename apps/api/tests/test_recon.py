"""Lifecycle L3: reconditioning inside a budget.

The exit criterion first and last: a repair over budget raises an approval
before the money is spent. Around it, the rest of the loop — work inside the
budget is approved at once and counted in the landed cost, done turns an
estimate into what it cost, a car with work in hand is not ready — and the
wall: an estimate is what the dealer will pay, so a salesperson sees none.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from PIL import Image
from pydantic import ValidationError

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, USER_A, reseed_with_people
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.db import session
from dealerai.events.bus import Event
from dealerai.events.handlers.lifecycle import on_approval_requested, on_recon_overran
from dealerai.events.handlers.runs import on_approval_decided
from dealerai.lifecycle import recon
from dealerai.lifecycle.recon import Budget, Finding, Inspection, ReconSettings
from dealerai.main import app

AED = 100  # minor units per dirham

# --------------------------------------------------------------------------
# the rule — pure
# --------------------------------------------------------------------------


def test_no_budget_means_every_repair_asks() -> None:
    """Nobody said how much may be spent, so nothing is spent without asking."""
    assert recon.needs_approval(Budget(None, 0, 0), 1)


def test_work_inside_the_budget_does_not_ask() -> None:
    budget = Budget(5_000 * AED, 3_000 * AED, 0)
    assert not recon.needs_approval(budget, 1_999 * AED)
    assert not recon.needs_approval(budget, 2_000 * AED), "up to the budget is inside it"
    assert recon.needs_approval(budget, 2_001 * AED)


def test_the_budget_says_what_is_left_and_whether_it_is_over() -> None:
    assert Budget(5_000 * AED, 3_000 * AED, 1_000 * AED).remaining_minor == 2_000 * AED
    assert Budget(5_000 * AED, 5_100 * AED, 0).over
    assert not Budget(None, 5_100 * AED, 0).over, "no budget is not a budget overrun"


def _finding(**over: Any) -> Finding:
    base: dict[str, Any] = {
        "photo": 1,
        "area": "exterior",
        "operation": "paint_panel",
        "quantity": 2,
        "severity": "moderate",
        "description": "Repaint rear left door and quarter",
        "seen": "deep scratch through the paint",
    }
    return Finding(**{**base, **over})


def test_a_finding_on_a_photo_that_was_not_sent_is_dropped() -> None:
    reading = recon.verify(Inspection(findings=[_finding(), _finding(photo=3)]), photos=2)
    assert len(reading.findings) == 1
    assert reading.warnings == ["skipped 'Repaint rear left door and quarter': there is no photo 3"]


def test_the_same_finding_twice_is_listed_once() -> None:
    reading = recon.verify(
        Inspection(
            findings=[_finding(), _finding(description="REPAINT rear left door and quarter")]
        ),
        photos=1,
    )
    assert len(reading.findings) == 1


def test_a_quantity_that_is_not_a_count_is_corrected() -> None:
    reading = recon.verify(
        Inspection(
            findings=[
                _finding(quantity=0),
                _finding(description="Dent", operation="dent_repair", quantity=400),
            ]
        ),
        photos=1,
    )
    assert [f.quantity for f in reading.findings] == [1, 20]


def test_a_negative_rate_is_refused() -> None:
    with pytest.raises(ValidationError):
        ReconSettings(rates={"tyre": -1})


# --------------------------------------------------------------------------
# the wall — Postgres, as the application role
# --------------------------------------------------------------------------


async def _car(su: asyncpg.Connection, *, status: str = "draft") -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, model_year, price_minor, status)
           values ($1, $2, 'Lexus', 'LX 600', 2023, 42000000, $3)""",
        vehicle_id,
        TENANT_A,
        status,
    )
    await su.execute(
        """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                      fx_rate, amount_tenant_minor, incurred_at)
           values ($1, $2, 'purchase', 35000000, 'AED', 1, 35000000, current_date)""",
        TENANT_A,
        vehicle_id,
    )
    return vehicle_id


async def _item(
    su: asyncpg.Connection,
    vehicle_id: uuid.UUID,
    *,
    estimate: int | None = 1_000 * AED,
    operation: str = "paint_panel",
    status: str = "proposed",
    actual: int | None = None,
    quantity: int = 1,
    done_days_ago: int | None = None,
) -> uuid.UUID:
    item_id = uuid.uuid4()
    await su.execute(
        """insert into recon_items (id, tenant_id, vehicle_id, area, operation, quantity,
                                    description, estimate_minor, actual_minor, status, done_at)
           values ($1, $2, $3, 'exterior', $4, $5, 'Repaint bonnet', $6, $7, $8,
                   case when $9::int is null then null
                        else now() - make_interval(days => $9::int) end)""",
        item_id,
        TENANT_A,
        vehicle_id,
        operation,
        quantity,
        estimate,
        actual,
        status,
        done_days_ago,
    )
    return item_id


async def _budget(su: asyncpg.Connection, vehicle_id: uuid.UUID, amount: int | None) -> None:
    await su.execute(
        """insert into vehicle_recon (vehicle_id, tenant_id, budget_minor) values ($1, $2, $3)
           on conflict (vehicle_id) do update set budget_minor = excluded.budget_minor""",
        vehicle_id,
        TENANT_A,
        amount,
    )


async def test_a_salespersons_session_sees_no_reconditioning_even_with_sql(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    await _budget(su, vehicle_id, 500 * AED)
    await _item(su, vehicle_id)
    async with session.tenant_session(TENANT_A, user_id=USER_A, buy_side=True) as conn:
        await recon.commit(
            conn, TENANT_A, await conn.fetchval("select id from recon_items"), actor_id=USER_A
        )

    async with session.tenant_session(TENANT_A, user_id=USER_A) as conn:
        assert await conn.fetchval("select count(*) from recon_items") == 0
        assert await conn.fetchval("select count(*) from vehicle_recon") == 0
        assert await conn.fetchval("select count(*) from approvals") == 0, (
            "the approval names what the repair costs, so it is behind the wall too"
        )
    async with session.tenant_session(TENANT_A, user_id=USER_A, buy_side=True) as conn:
        assert await conn.fetchval("select count(*) from recon_items") == 1
        assert await conn.fetchval("select count(*) from approvals") == 1


async def test_the_dealers_own_history_prices_what_the_rate_card_does_not(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """The median per tyre of the last jobs: one expensive invoice does not
    move it, and too few jobs are no history at all."""
    vehicle_id = await _car(su)
    settings = ReconSettings(rates={"paint_panel": 800 * AED})
    async with session.tenant_session(TENANT_A) as conn:
        assert await recon.estimate(conn, TENANT_A, settings, "tyre", 2) == (None, None)
    for actual in (450, 480, 2_000):
        await _item(
            su, vehicle_id, operation="tyre", status="done", actual=actual * AED, done_days_ago=10
        )
    await _item(  # two years ago: not history any more
        su, vehicle_id, operation="tyre", status="done", actual=100 * AED, done_days_ago=700
    )
    async with session.tenant_session(TENANT_A) as conn:
        assert await recon.estimate(conn, TENANT_A, settings, "tyre", 2) == (960 * AED, "history")
        assert await recon.estimate(conn, TENANT_A, settings, "paint_panel", 3) == (
            2_400 * AED,
            "rate_card",
        ), "what the dealer said comes before what the history suggests"


# --------------------------------------------------------------------------
# the decision — the worker
# --------------------------------------------------------------------------


def _event(event_type: str, payload: dict[str, Any]) -> Event:
    return Event(
        id=0,
        tenant_id=TENANT_A,
        event_type=event_type,
        payload=payload,
        attempts=1,
        dedupe_key=None,
    )


async def _ask(su: asyncpg.Connection) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A car with AED 500 of budget and a AED 1,000 repair: it has to ask."""
    vehicle_id = await _car(su)
    await _budget(su, vehicle_id, 500 * AED)
    item_id = await _item(su, vehicle_id)
    async with session.tenant_session(TENANT_A) as conn:
        committed = await recon.commit(conn, TENANT_A, item_id, actor_id=USER_A)
    assert committed is not None and committed.approval_id is not None
    assert committed.over_minor == 500 * AED
    return vehicle_id, item_id, committed.approval_id


async def _decide(su: asyncpg.Connection, approval_id: uuid.UUID, outcome: str) -> None:
    await su.execute(
        "update approvals set status = $2, decided_by = $3, decided_at = now() where id = $1",
        approval_id,
        outcome,
        USER_A,
    )
    await on_approval_decided(
        _event(
            "approval.decided",
            {"approval_id": str(approval_id), "kind": recon.KIND, "decision": outcome},
        )
    )


async def test_approving_an_overrun_commits_the_work(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id, item_id, approval_id = await _ask(su)
    assert await su.fetchval("select count(*) from vehicle_costs where status = 'estimate'") == 0, (
        "nothing is promised while it waits"
    )
    await _decide(su, approval_id, "approved")

    item = await su.fetchrow("select status, cost_id from recon_items where id = $1", item_id)
    assert item["status"] == "approved"
    line = await su.fetchrow(
        "select category, status, amount_tenant_minor, created_by from vehicle_costs where id = $1",
        item["cost_id"],
    )
    assert dict(line) == {
        "category": "repair",
        "status": "estimate",
        "amount_tenant_minor": 1_000 * AED,
        "created_by": USER_A,
    }


async def test_rejecting_an_overrun_declines_the_work(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    _vehicle_id, item_id, approval_id = await _ask(su)
    await _decide(su, approval_id, "rejected")
    assert await su.fetchval("select status from recon_items where id = $1", item_id) == "declined"
    assert await su.fetchval("select count(*) from vehicle_costs where status = 'estimate'") == 0


async def test_an_item_changed_after_it_was_asked_about_is_not_applied(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """What was approved is not what is there: AED 1,000 was asked, 3,000 is on
    the item now."""
    _vehicle_id, item_id, approval_id = await _ask(su)
    await su.execute("update recon_items set estimate_minor = 300000 where id = $1", item_id)
    await _decide(su, approval_id, "approved")
    assert (
        await su.fetchval("select status from recon_items where id = $1", item_id)
        == "awaiting_approval"
    )


async def test_whoever_decides_is_told_at_once(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    _vehicle_id, _item_id, approval_id = await _ask(su)
    summary = await su.fetchval("select summary from approvals where id = $1", approval_id)
    assert summary == "2023 Lexus LX 600 · Repaint bonnet · AED 1,000 · AED 500 over budget"
    await on_approval_requested(
        _event(
            "approval.requested",
            {"approval_id": str(approval_id), "kind": recon.KIND, "summary": summary},
        )
    )
    rows = await su.fetch(
        "select user_id, body, href from notifications where kind = 'recon_approval'"
    )
    assert [(r["user_id"], r["body"], r["href"]) for r in rows] == [
        (USER_A, summary, "/approvals")
    ], "the owner — and nobody who cannot decide it"


async def test_other_approvals_ring_no_bell_here(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    await on_approval_requested(
        _event(
            "approval.requested",
            {"approval_id": str(uuid.uuid4()), "kind": "price_change", "summary": "x"},
        )
    )
    assert await su.fetchval("select count(*) from notifications") == 0


async def test_a_repair_that_came_in_over_tells_the_owner(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """Approved at AED 1,000 inside a AED 1,200 budget; the bill says 1,500.
    The money is spent, so there is nothing to approve — only to tell."""
    vehicle_id = await _car(su)
    await _budget(su, vehicle_id, 1_200 * AED)
    item_id = await _item(su, vehicle_id)
    async with session.tenant_session(TENANT_A) as conn:
        committed = await recon.commit(conn, TENANT_A, item_id, actor_id=USER_A)
        assert committed is not None and committed.approval_id is None
        done = await recon.finish(
            conn, TENANT_A, item_id, actual_minor=1_500 * AED, vendor=None, actor_id=USER_A
        )
    assert done is not None and done.overran
    event = await su.fetchrow("select payload from events where event_type = 'recon.overran'")
    payload = json.loads(event["payload"])
    assert payload["over_minor"] == 300 * AED

    await on_recon_overran(_event("recon.overran", payload))
    note = await su.fetchrow("select title, body from notifications where kind = 'recon_overrun'")
    assert note["title"] == "A repair is AED 300 over budget"
    assert note["body"] == "Repaint bonnet: AED 1,500, estimated at AED 1,000."


# --------------------------------------------------------------------------
# the door — the API, per role
# --------------------------------------------------------------------------

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


async def _people_and_a_car() -> uuid.UUID:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await _car(conn)
    finally:
        await conn.close()


@pytest.fixture
def car(_migrated: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return asyncio.run(_people_and_a_car())


@pytest.fixture
def client(car: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


ITEM = {
    "area": "exterior",
    "operation": "paint_panel",
    "description": "Repaint front bumper",
    "estimate_minor": 1_500 * AED,
}


def _set_budget(client: TestClient, car: uuid.UUID, amount: int | None) -> None:
    response = client.patch(
        f"/v1/vehicles/{car}/recon", json={"budget_minor": amount}, headers=auth(OWNER)
    )
    assert response.status_code == 200, response.text


def _add(client: TestClient, car: uuid.UUID, **over: Any) -> str:
    response = client.post(
        f"/v1/vehicles/{car}/recon/items",
        json={"items": [{**ITEM, **over}]},
        headers=auth(MANAGER),
    )
    assert response.status_code == 201, response.text
    return str(response.json()[0]["id"])


def _commit(client: TestClient, car: uuid.UUID, item_id: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/vehicles/{car}/recon/items/{item_id}/commit", headers=auth(MANAGER)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_reconditioning_is_buy_side(client: TestClient, car: uuid.UUID) -> None:
    assert client.get(f"/v1/vehicles/{car}/recon", headers=auth(SALES_1)).status_code == 403
    for who in (OWNER, MANAGER):
        assert client.get(f"/v1/vehicles/{car}/recon", headers=auth(who)).status_code == 200


def test_a_manager_runs_the_work_but_cannot_move_the_budget(
    client: TestClient, car: uuid.UUID
) -> None:
    """Whoever commits work cannot be whoever moves the line it is measured against."""
    url = f"/v1/vehicles/{car}/recon"
    refused = client.patch(url, json={"budget_minor": 99_999 * AED}, headers=auth(MANAGER))
    assert refused.status_code == 403
    assert (
        client.patch(url, json={"ready_by": "2026-11-20"}, headers=auth(MANAGER)).json()["ready_by"]
        == "2026-11-20"
    )
    _set_budget(client, car, 5_000 * AED)
    record = client.get(url, headers=auth(MANAGER)).json()
    assert record["budget"] == {"amount_minor": 5_000 * AED, "currency": "AED"}
    assert (
        client.post(
            f"/v1/vehicles/{car}/recon/items", json={"items": [ITEM]}, headers=auth(SALES_1)
        ).status_code
        == 403
    )


def test_work_inside_the_budget_is_approved_and_counted_in_the_landed_cost(
    client: TestClient, car: uuid.UUID
) -> None:
    _set_budget(client, car, 5_000 * AED)
    committed = _commit(client, car, _add(client, car))
    assert committed["approval_id"] is None
    assert committed["item"]["status"] == "approved"

    economics = client.get(f"/v1/vehicles/{car}/economics", headers=auth(OWNER)).json()
    assert economics["cost_estimate"]["amount_minor"] == 1_500 * AED, (
        "tomorrow's price already counts the work the dealer agreed to"
    )
    record = client.get(f"/v1/vehicles/{car}/recon", headers=auth(OWNER)).json()
    assert record["committed"]["amount_minor"] == 1_500 * AED
    assert record["remaining"]["amount_minor"] == 3_500 * AED


def test_a_repair_over_budget_raises_an_approval_before_the_money_is_spent(
    client: TestClient, car: uuid.UUID
) -> None:
    """The slice's exit criterion."""
    _set_budget(client, car, 2_000 * AED)
    _commit(client, car, _add(client, car))
    asked = _commit(
        client, car, _add(client, car, description="Replace tyres", estimate_minor=90_000)
    )

    assert asked["item"]["status"] == "awaiting_approval"
    assert asked["over"] == {"amount_minor": 400 * AED, "currency": "AED"}
    economics = client.get(f"/v1/vehicles/{car}/economics", headers=auth(OWNER)).json()
    assert economics["cost_estimate"]["amount_minor"] == 1_500 * AED, "nothing promised yet"

    queue = client.get("/v1/approvals", headers=auth(OWNER)).json()
    [approval] = [a for a in queue if a["kind"] == "recon_over_budget"]
    assert approval["id"] == asked["approval_id"]
    assert approval["summary"].endswith("AED 900 · AED 400 over budget")
    assert approval["required_role"] == "admin"

    # A manager may not decide it, and a salesperson does not know it exists.
    decide = f"/v1/approvals/{approval['id']}/approve"
    assert client.post(decide, json={}, headers=auth(MANAGER)).status_code == 403
    assert all(
        a["kind"] != "recon_over_budget"
        for a in client.get("/v1/approvals", headers=auth(SALES_1)).json()
    )
    assert client.get(f"/v1/approvals/{approval['id']}", headers=auth(SALES_1)).status_code == 404
    assert client.post(decide, json={}, headers=auth(OWNER)).status_code == 200


def test_no_budget_set_asks_for_everything(client: TestClient, car: uuid.UUID) -> None:
    asked = _commit(client, car, _add(client, car))
    assert asked["item"]["status"] == "awaiting_approval"
    queue = client.get("/v1/approvals", headers=auth(OWNER)).json()
    assert any(a["summary"].endswith("no budget set") for a in queue)


def test_work_needs_an_estimate_before_it_is_committed(client: TestClient, car: uuid.UUID) -> None:
    item_id = _add(client, car, estimate_minor=None)
    response = client.post(
        f"/v1/vehicles/{car}/recon/items/{item_id}/commit", headers=auth(MANAGER)
    )
    assert response.status_code == 409


def test_done_turns_the_estimate_into_what_it_cost(client: TestClient, car: uuid.UUID) -> None:
    _set_budget(client, car, 5_000 * AED)
    item_id = _add(client, car)
    _commit(client, car, item_id)
    done = client.post(
        f"/v1/vehicles/{car}/recon/items/{item_id}/done",
        json={"actual_minor": 1_650 * AED, "vendor": "Al Quoz Bodyshop"},
        headers=auth(MANAGER),
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"

    lines = client.get(f"/v1/vehicles/{car}/costs", headers=auth(OWNER)).json()
    repair = [line for line in lines if line["category"] == "repair"]
    assert [(r["status"], r["amount"]["amount_minor"], r["vendor"]) for r in repair] == [
        ("actual", 1_650 * AED, "Al Quoz Bodyshop")
    ], "one line, the estimate's, now the actual"
    record = client.get(f"/v1/vehicles/{car}/recon", headers=auth(OWNER)).json()
    assert record["spent"]["amount_minor"] == 1_650 * AED


def test_committed_work_is_not_edited(client: TestClient, car: uuid.UUID) -> None:
    _set_budget(client, car, 5_000 * AED)
    item_id = _add(client, car)
    _commit(client, car, item_id)
    response = client.patch(
        f"/v1/vehicles/{car}/recon/items/{item_id}",
        json={"estimate_minor": 100},
        headers=auth(MANAGER),
    )
    assert response.status_code == 422


def test_declining_approved_work_takes_its_estimate_out_of_the_ledger(
    client: TestClient, car: uuid.UUID
) -> None:
    _set_budget(client, car, 5_000 * AED)
    item_id = _add(client, car)
    _commit(client, car, item_id)
    declined = client.post(
        f"/v1/vehicles/{car}/recon/items/{item_id}/decline", headers=auth(MANAGER)
    )
    assert declined.json()["status"] == "declined"
    economics = client.get(f"/v1/vehicles/{car}/economics", headers=auth(OWNER)).json()
    assert economics["cost_estimate"]["amount_minor"] == 0


def test_withdrawing_a_waiting_item_takes_it_out_of_the_queue(
    client: TestClient, car: uuid.UUID
) -> None:
    item_id = _add(client, car)
    _commit(client, car, item_id)
    client.post(f"/v1/vehicles/{car}/recon/items/{item_id}/decline", headers=auth(MANAGER))
    queue = client.get("/v1/approvals", headers=auth(OWNER)).json()
    assert all(a["kind"] != "recon_over_budget" for a in queue)


def test_a_car_with_work_in_hand_is_not_ready(client: TestClient, car: uuid.UUID) -> None:
    _set_budget(client, car, 5_000 * AED)
    item_id = _add(client, car)
    _commit(client, car, item_id)
    ready = f"/v1/vehicles/{car}/recon/ready"
    assert client.post(ready, headers=auth(MANAGER)).status_code == 409

    client.post(
        f"/v1/vehicles/{car}/recon/items/{item_id}/done",
        json={"actual_minor": 1_500 * AED},
        headers=auth(MANAGER),
    )
    response = client.post(ready, headers=auth(MANAGER))
    assert response.status_code == 200, response.text
    assert response.json()["ready_at"] is not None
    vehicle = client.get(f"/v1/vehicles/{car}", headers=auth(OWNER)).json()
    assert vehicle["status"] == "available", "a car in draft goes on sale when it is ready"


def test_an_item_of_another_car_is_not_there(client: TestClient, car: uuid.UUID) -> None:
    item_id = _add(client, car)
    other = uuid.uuid4()
    response = client.post(
        f"/v1/vehicles/{other}/recon/items/{item_id}/commit", headers=auth(MANAGER)
    )
    assert response.status_code == 404


def test_a_photo_from_somewhere_else_is_refused(client: TestClient, car: uuid.UUID) -> None:
    response = client.post(
        f"/v1/vehicles/{car}/recon/items",
        json={"items": [{**ITEM, "photo_path": f"{uuid.uuid4()}/inspections/x.jpg"}]},
        headers=auth(MANAGER),
    )
    assert response.status_code == 422


def test_reconditioning_settings_are_the_owners(client: TestClient, car: uuid.UUID) -> None:
    assert client.get("/v1/settings/recon", headers=auth(MANAGER)).status_code == 403
    saved = client.put(
        "/v1/settings/recon",
        json={"default_budget_minor": 3_000 * AED, "rates": {"paint_panel": 800 * AED}},
        headers=auth(OWNER),
    )
    assert saved.status_code == 200, saved.text
    # A car whose record does not exist yet starts with the default.
    record = client.get(f"/v1/vehicles/{car}/recon", headers=auth(OWNER)).json()
    assert record["budget"]["amount_minor"] == 3_000 * AED


# --------------------------------------------------------------------------
# reading inspection photos
# --------------------------------------------------------------------------

INSPECTION = {
    "findings": [
        {
            "photo": 1,
            "area": "exterior",
            "operation": "paint_panel",
            "quantity": 2,
            "severity": "moderate",
            "description": "Repaint rear left door and quarter",
            "seen": "deep scratch through the paint, primer visible",
        },
        {
            "photo": 2,
            "area": "tyres_wheels",
            "operation": "tyre",
            "quantity": 2,
            "severity": "major",
            "description": "Replace both front tyres",
            "seen": "tread worn to the wear bars",
        },
    ]
}


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    class Models:
        async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
            calls.append(kwargs)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model", parts=[types.Part(text=json.dumps(INSPECTION))]
                        ),
                        finish_reason=types.FinishReason.STOP,
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=1800, candidates_token_count=200, total_token_count=2000
                ),
            )

    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": Models()})()})()
    )
    return calls


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (120, 120, 120)).save(buf, format="JPEG")
    return buf.getvalue()


def test_an_inspection_proposes_priced_work_and_writes_nothing(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    client.put(
        "/v1/settings/recon",
        json={"rates": {"paint_panel": 800 * AED}},
        headers=auth(OWNER),
    )
    response = client.post(
        f"/v1/vehicles/{car}/recon/inspect",
        files=[
            ("files", ("side.jpg", _jpeg(), "image/jpeg")),
            ("files", ("tyre.jpg", _jpeg(), "image/jpeg")),
        ],
        headers=auth(MANAGER),
    )
    assert response.status_code == 200, response.text
    paint, tyres = response.json()["findings"]
    assert paint["estimate"] == {"amount_minor": 1_600 * AED, "currency": "AED"}
    assert paint["estimate_source"] == "rate_card"
    assert tyres["estimate"] is None, "no rate and no history: a person types it"
    assert paint["photo_path"].startswith(f"{TENANT_A}/inspections/")
    assert paint["photo_path"] != tyres["photo_path"]
    assert client.get(f"/v1/vehicles/{car}/recon", headers=auth(OWNER)).json()["items"] == []

    # Both photos went to the model, each labelled with its number.
    parts = model[0]["contents"].parts
    labels = [p.text for p in parts if p.text and p.text.startswith("Photo ")]
    assert labels == ["Photo 1:", "Photo 2:"]


def test_an_inspection_is_photos_only(client: TestClient, car: uuid.UUID, model: list[Any]) -> None:
    response = client.post(
        f"/v1/vehicles/{car}/recon/inspect",
        files=[("files", ("report.pdf", b"%PDF-1.4", "application/pdf"))],
        headers=auth(MANAGER),
    )
    assert response.status_code == 422
    assert model == [], "refused before a model call"
