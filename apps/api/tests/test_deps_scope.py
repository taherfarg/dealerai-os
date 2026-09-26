"""The request context derives what a caller may see and do from their role."""

from __future__ import annotations

import pytest

from conftest import SALES_1, TENANT_A
from dealerai.core.errors import Forbidden
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext, require_permission


def _ctx(role: str) -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A,
        user=AuthedUser(id=SALES_1, email="s1@example.test", claims={}),
        role=role,
    )


def test_context_derives_scope_and_permissions_from_the_role() -> None:
    assert _ctx("sales").scope == "own"
    assert _ctx("manager").scope == "team"
    assert _ctx("owner").scope == "all"
    assert _ctx("manager").may("inbox.assign")
    assert not _ctx("sales").may("inbox.assign")


def test_manager_outranks_sales_and_marketer_but_not_admin() -> None:
    assert _ctx("manager").at_least("sales")
    assert _ctx("manager").at_least("marketer")
    assert not _ctx("manager").at_least("admin")
    assert not _ctx("sales").at_least("manager")


def test_the_api_role_type_lists_every_role() -> None:
    """A role the database accepts but the API's Literal does not would 500 the
    members list the first time a workspace has a manager."""
    from typing import get_args

    from dealerai.core.permissions import ROLES
    from dealerai.routes import tenants

    assert set(get_args(tenants.Role)) == set(ROLES)


async def test_require_permission_refuses_and_allows() -> None:
    guard = require_permission("contacts.reassign")
    with pytest.raises(Forbidden):
        await guard(_ctx("sales"))
    assert await guard(_ctx("manager")) is not None
