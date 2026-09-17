"""The local seed must be safe to run again and again, and never anywhere else."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dealerai.db.session import tenant_session
from dealerai.scripts import seed_sales
from dealerai.scripts.seed_sales import CUSTOMERS, PEOPLE, TENANT, person_id, seed


async def test_the_seed_can_run_twice(db: None) -> None:
    assert await seed() == 0
    assert await seed() == 0, "a second run must replace the workspace, not collide with it"
    async with tenant_session(TENANT) as conn:
        assert await conn.fetchval("select count(*) from memberships") == len(PEOPLE)
        assert await conn.fetchval("select count(*) from contacts") == len(CUSTOMERS)


async def test_visibility_holds_on_the_seeded_workspace(db: None) -> None:
    assert await seed() == 0
    ahmed = person_id("Ahmed Nasser")
    async with tenant_session(TENANT, user_id=ahmed, scope="own") as conn:
        his = await conn.fetchval("select count(*) from contacts")
    assert 0 < his < len(CUSTOMERS), "a salesperson should see some customers, not all"


async def test_the_seed_refuses_to_run_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        seed_sales,
        "get_settings",
        lambda: SimpleNamespace(env="staging", migration_dsn="postgresql://never@nowhere/db"),
    )
    assert await seed() == 1
