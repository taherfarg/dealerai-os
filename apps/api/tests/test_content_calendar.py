"""T3.8: the content calendar.

The acceptance is the spine of this file: dragging a piece updates its
`scheduled_at` and emits nothing until the slot is due, and scheduling above
`max_posts_per_day` is refused with a named reason.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, TENANT_A
from dealerai.config import get_settings
from dealerai.main import app
from dealerai.sales.clock import zone
from dealerai.schedule import Rules, gaps, refusal, rules_of
from test_content_review import SECRET, _made_a_piece, auth

DUBAI = zone("Asia/Dubai")
NOW = datetime(2026, 11, 7, 9, 0)

# --------------------------------------------------------------------------
# the rules — pure
# --------------------------------------------------------------------------


def test_the_rules_are_the_ones_the_gate_reads() -> None:
    rules = rules_of({"publishing": {"max_posts_per_day": 4, "quiet_hours": ["23:00", "07:00"]}})
    assert rules == Rules(max_per_day=4, quiet=(time(23), time(7)))
    assert rules_of({}) == Rules()
    assert rules_of({"publishing": {"quiet_hours": ["late"]}}) == Rules(), "unreadable is none"


def test_a_slot_is_refused_with_the_rule_it_breaks() -> None:
    rules = Rules(max_per_day=2, quiet=(time(23), time(7)))
    saturday = date(2026, 11, 7)
    sunday = date(2026, 11, 8)
    assert refusal(rules, day=saturday, at=time(8), already=0, now=NOW) == (
        "Saturday 07 November 08:00 has already passed"
    )
    assert refusal(rules, day=sunday, at=time(23, 30), already=0, now=NOW) == (
        "23:30 is inside quiet hours, 23:00–07:00"
    )
    assert refusal(rules, day=sunday, at=time(6, 59), already=0, now=NOW), "quiet wraps midnight"
    assert refusal(rules, day=sunday, at=time(10), already=2, now=NOW) == (
        "Sunday 08 November already has 2 of the 2 posts a day allowed"
    )
    assert refusal(rules, day=sunday, at=time(10), already=1, now=NOW) is None
    assert refusal(Rules(), day=sunday, at=time(3), already=40, now=NOW) is None, "no rules"


def test_a_gap_is_a_day_to_come_with_nothing_going_out() -> None:
    span = [date(2026, 11, d) for d in range(5, 10)]
    counts = {date(2026, 11, 8): 1}
    assert gaps(span, counts, today=date(2026, 11, 7)) == [date(2026, 11, 7), date(2026, 11, 9)]


# --------------------------------------------------------------------------
# through the API
# --------------------------------------------------------------------------


async def _another(piece: uuid.UUID, status: str, at: datetime | None) -> uuid.UUID:
    """A second piece for the same car, as the first one's run made it."""
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await conn.fetchval(
            """insert into content_items (tenant_id, vehicle_id, run_id, kind, concept, status,
                                          scheduled_at)
               select tenant_id, vehicle_id, run_id, 'story', 'specs', $2, $3
                 from content_items where id = $1
               returning id""",
            piece,
            status,
            at,
        )
    finally:
        await conn.close()


async def _rules(rules: dict[str, object]) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "update tenants set autonomy_rules = $2::jsonb, timezone = 'Asia/Dubai' where id = $1",
            TENANT_A,
            json.dumps(rules),
        )
    finally:
        await conn.close()


async def _events() -> int:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return int(
            await conn.fetchval("select count(*) from events where tenant_id = $1", TENANT_A)
        )
    finally:
        await conn.close()


@pytest.fixture
def approved(_migrated: None, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)
    made = asyncio.run(_made_a_piece("approved"))
    asyncio.run(_rules({"publishing": {"max_posts_per_day": 1, "quiet_hours": ["23:00", "07:00"]}}))
    return made["piece"]


@pytest.fixture
def client(approved: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _day(days_on: int) -> date:
    return datetime.now(DUBAI).date() + timedelta(days=days_on)


def test_dragging_a_piece_moves_its_slot_and_sends_nothing(
    client: TestClient, approved: uuid.UUID
) -> None:
    """The acceptance: scheduled on one day, dragged to another. Its time moves
    on the dealer's clock and not one event is booked — it goes out when due."""
    before = asyncio.run(_events())
    first = client.post(
        f"/v1/content/{approved}/schedule",
        json={"day": _day(2).isoformat(), "at": "10:00"},
        headers=auth(MANAGER),
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "scheduled"
    expected = datetime.combine(_day(2), time(10), tzinfo=DUBAI)
    assert datetime.fromisoformat(first.json()["scheduled_at"]) == expected

    dragged = client.post(
        f"/v1/content/{approved}/schedule",
        json={"day": _day(3).isoformat(), "at": "10:00"},
        headers=auth(MANAGER),
    )
    assert dragged.status_code == 200, dragged.text
    moved = datetime.fromisoformat(dragged.json()["scheduled_at"])
    assert moved == datetime.combine(_day(3), time(10), tzinfo=DUBAI)
    assert asyncio.run(_events()) == before, "scheduling emits nothing until the slot is due"

    week = client.get(
        "/v1/content/calendar",
        params={"from": _day(0).isoformat(), "to": _day(6).isoformat()},
        headers=auth(SALES_1),
    ).json()
    [item] = week["items"]
    assert (item["id"], item["local_date"], item["local_time"]) == (
        str(approved),
        _day(3).isoformat(),
        "10:00",
    )
    assert week["max_posts_per_day"] == 1 and week["quiet_hours"] == ["23:00", "07:00"]
    assert _day(3).isoformat() not in week["gaps"] and _day(2).isoformat() in week["gaps"]
    assert next(d for d in week["days"] if d["date"] == _day(3).isoformat())["full"] is True


def test_a_day_at_its_limit_refuses_another_and_says_why(
    client: TestClient, approved: uuid.UUID
) -> None:
    taken = datetime.combine(_day(2), time(18), tzinfo=DUBAI)
    asyncio.run(_another(approved, "scheduled", taken))
    refused = client.post(
        f"/v1/content/{approved}/schedule",
        json={"day": _day(2).isoformat(), "at": "10:00"},
        headers=auth(MANAGER),
    )
    assert refused.status_code == 409
    assert "already has 1 of the 1 posts a day allowed" in refused.text

    late = client.post(
        f"/v1/content/{approved}/schedule",
        json={"day": _day(4).isoformat(), "at": "23:30"},
        headers=auth(MANAGER),
    )
    assert late.status_code == 409 and "quiet hours" in late.text

    waiting = client.get(
        "/v1/content/calendar",
        params={"from": _day(0).isoformat(), "to": _day(6).isoformat()},
        headers=auth(MANAGER),
    ).json()
    assert [p["id"] for p in waiting["unscheduled"]] == [str(approved)], "still waiting a slot"


def test_only_an_approved_piece_is_scheduled_and_it_can_come_off(
    client: TestClient, approved: uuid.UUID
) -> None:
    pending = asyncio.run(_another(approved, "pending_approval", None))
    not_yet = client.post(
        f"/v1/content/{pending}/schedule",
        json={"day": _day(2).isoformat()},
        headers=auth(MANAGER),
    )
    assert not_yet.status_code == 409 and "approve it first" in not_yet.text
    assert (
        client.post(
            f"/v1/content/{approved}/schedule",
            json={"day": _day(2).isoformat()},
            headers=auth(SALES_1),
        ).status_code
        == 403
    )

    client.post(
        f"/v1/content/{approved}/schedule", json={"day": _day(2).isoformat()}, headers=auth(MANAGER)
    )
    off = client.post(f"/v1/content/{approved}/unschedule", headers=auth(MANAGER))
    assert off.status_code == 200, off.text
    assert (off.json()["status"], off.json()["scheduled_at"]) == ("approved", None)

    with_offset = client.post(
        f"/v1/content/{approved}/schedule",
        json={"day": _day(2).isoformat(), "at": "10:00:00+04:00"},
        headers=auth(MANAGER),
    )
    assert with_offset.status_code == 400, "the dealer's clock has no offset to give"

    backwards = client.get(
        "/v1/content/calendar",
        params={"from": _day(6).isoformat(), "to": _day(0).isoformat()},
        headers=auth(MANAGER),
    )
    assert backwards.status_code == 422
