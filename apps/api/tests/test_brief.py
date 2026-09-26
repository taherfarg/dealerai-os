"""The morning brief: one per reader, written from what that reader may see.

The model is faked here — the suite never spends money. tests/evals/test_brief_live.py
is where the real one writes a headline.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import pytest

from conftest import MANAGER, OWNER, SALES_1, SALES_2, SALES_X, TENANT_A, USER_A
from dealerai.agents.sales import brief as brief_agent
from dealerai.agents.sales.brief import Written
from dealerai.core.errors import BudgetExceeded
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext
from dealerai.events.bus import Event
from dealerai.events.handlers.manager import on_brief_due
from dealerai.routes.dashboard import manager_dashboard
from dealerai.sales.dashboard import Headline

DUBAI = ZoneInfo("Asia/Dubai")
TODAY = datetime.now(DUBAI).date()
CUSTOMERS = (
    "alpha customer",
    "s1 customer",
    "s2 customer",
    "covered customer",
    "x customer",
    "local pool",
    "export pool",
)


class FakeBrief:
    """Records what it was shown; answers with a fixed pair of lines."""

    def __init__(
        self, en: str = "2 new conversations yesterday.", raises: Exception | None = None
    ) -> None:
        self.en, self.raises = en, raises
        self.shown: list[str] = []

    async def write(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, facts: str) -> Written:
        self.shown.append(facts)
        if self.raises:
            raise self.raises
        return Written(Headline(en=self.en, ar="2 محادثة جديدة أمس."), 0.001)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBrief:
    model = FakeBrief()
    monkeypatch.setattr(brief_agent, "write", model.write)
    return model


async def _yesterday(su: asyncpg.Connection) -> None:
    """Yesterday in Dubai: s1 customer (Local) and x customer (Export) wrote at
    noon and were answered four minutes later."""
    noon = datetime.combine(TODAY - timedelta(days=1), time(12), tzinfo=DUBAI)
    for name in ("s1 customer", "x customer"):
        conversation = await su.fetchval(
            """select cv.id from conversations cv join contacts ct on ct.id = cv.contact_id
                where ct.full_name = $1""",
            name,
        )
        await su.execute(
            "update conversations set created_at = $2, first_response_at = $3 where id = $1",
            conversation,
            noon,
            noon + timedelta(minutes=4),
        )
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, body,
                                     created_at)
               values ($1, $2, 'in', 'customer', 'customer', 'Hello', $3)""",
            TENANT_A,
            conversation,
            noon,
        )


async def _brief_due() -> None:
    await on_brief_due(Event(1, TENANT_A, "sales.brief_due", {"date": TODAY.isoformat()}, 1, None))


async def _briefs(su: asyncpg.Connection) -> dict[uuid.UUID, asyncpg.Record]:
    rows = await su.fetch("select user_id, headline, facts from sales_briefs")
    return {row["user_id"]: row for row in rows}


async def test_every_reader_gets_a_brief_of_their_own(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    await _yesterday(su)
    await _brief_due()
    readers = set(await _briefs(su))
    assert readers == {USER_A, OWNER, MANAGER}
    assert not readers & {SALES_1, SALES_2, SALES_X}


async def test_a_managers_brief_counts_only_her_teams(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    await _yesterday(su)
    await _brief_due()
    briefs = await _briefs(su)
    assert json.loads(briefs[MANAGER]["facts"])["new_conversations"] == 1
    assert json.loads(briefs[OWNER]["facts"])["new_conversations"] == 2


async def test_the_model_is_never_shown_a_customers_name(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    await _yesterday(su)
    await _brief_due()
    assert fake.shown, "the model was asked"
    for shown in fake.shown:
        assert not [name for name in CUSTOMERS if name in shown]
    assert any("sales1" in shown for shown in fake.shown), "salespeople are named"


async def test_a_retried_brief_writes_nobody_twice(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    await _yesterday(su)
    await _brief_due()
    await _brief_due()
    per_reader = await su.fetch(
        "select user_id, count(*) as n from sales_briefs group by user_id having count(*) > 1"
    )
    assert per_reader == []
    told = await su.fetch(
        """select user_id, count(*) as n from notifications where kind = 'brief_ready'
            group by user_id"""
    )
    assert sorted(row["n"] for row in told) == [1, 1, 1]


async def test_a_headline_with_a_number_it_was_not_given_is_not_shown(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    fake.en = "37 new conversations yesterday."
    await _yesterday(su)
    await _brief_due()
    briefs = await _briefs(su)
    assert briefs[OWNER]["headline"] is None
    body = await su.fetchval(
        "select body from notifications where kind = 'brief_ready' and user_id = $1", OWNER
    )
    assert body is None


async def test_a_quiet_day_costs_nothing(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    await _brief_due()
    assert fake.shown == []
    briefs = await _briefs(su)
    assert set(briefs) == {USER_A, OWNER, MANAGER}
    assert all(brief["headline"] is None for brief in briefs.values())


async def test_no_budget_means_no_headline_rather_than_no_brief(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    fake.raises = BudgetExceeded("monthly AI budget reached")
    await _yesterday(su)
    await _brief_due()  # does not raise: the event must not fail
    briefs = await _briefs(su)
    assert set(briefs) == {USER_A, OWNER, MANAGER}
    assert all(brief["headline"] is None for brief in briefs.values())


async def test_the_dashboard_shows_the_readers_brief(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    await _yesterday(su)
    await _brief_due()
    ctx = TenantContext(
        tenant_id=TENANT_A, user=AuthedUser(id=MANAGER, email=None, claims={}), role="manager"
    )
    board = await manager_dashboard(ctx, None)
    assert board["brief"]["headline"] == {
        "en": "2 new conversations yesterday.",
        "ar": "2 محادثة جديدة أمس.",
    }


async def test_a_brief_notification_opens_the_dashboard(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    await _yesterday(su)
    await _brief_due()
    hrefs = {
        row["href"]
        for row in await su.fetch("select href from notifications where kind = 'brief_ready'")
    }
    assert hrefs == {"/dashboard"}
