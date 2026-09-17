"""Who can see whose customers. The second-highest-value test in the repository.

Tenant isolation (test_tenant_isolation.py) stops one dealership reading
another. This file stops one salesperson reading another salesperson's
customers inside the same dealership — enforced by the same mechanism, one
level down: the session states who is asking, and RLS filters.
"""

from __future__ import annotations

import pytest

from conftest import TENANT_A, USER_A
from dealerai.db.session import system_session, tenant_session


async def test_scope_and_user_reach_the_database(db: None, seeded: None) -> None:
    async with tenant_session(TENANT_A, user_id=USER_A, scope="own") as conn:
        assert await conn.fetchval("select app.current_user_id()") == USER_A
        assert await conn.fetchval("select current_setting('app.scope', true)") == "own"
        assert await conn.fetchval("select app.visible_owner_ids()") == [USER_A]


async def test_scope_all_means_no_owner_filter(db: None, seeded: None) -> None:
    async with tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select app.visible_owner_ids()") is None


async def test_an_unknown_scope_is_refused_before_it_reaches_sql(db: None) -> None:
    with pytest.raises(ValueError, match="scope"):
        async with tenant_session(TENANT_A, scope="everything"):
            pass


async def test_the_session_does_not_leak_a_user_into_the_next_transaction(
    db: None, seeded: None
) -> None:
    async with tenant_session(TENANT_A, user_id=USER_A, scope="own"):
        pass
    async with system_session() as conn:
        assert await conn.fetchval("select current_setting('app.user_id', true)") in (None, "")
