"""Pure logic, no database — the same reason orchestrator/gate.py is pure:
an authorisation rule you cannot test in milliseconds is one nobody re-checks."""

from __future__ import annotations

import pytest

from dealerai.core.permissions import ROLES, permissions_for, scope_for


def test_every_role_has_a_scope_and_a_permission_set() -> None:
    for role in ROLES:
        assert scope_for(role) in ("own", "team", "all")
        assert isinstance(permissions_for(role), frozenset)


@pytest.mark.parametrize(
    ("role", "scope"),
    [
        ("owner", "all"),
        ("admin", "all"),
        ("viewer", "all"),
        ("manager", "team"),
        ("sales", "own"),
        ("marketer", "own"),
    ],
)
def test_scope_by_role(role: str, scope: str) -> None:
    assert scope_for(role) == scope


def test_a_salesperson_may_send_but_not_reassign() -> None:
    sales = permissions_for("sales")
    assert "inbox.send" in sales
    assert "contacts.reassign" not in sales
    assert "settings.team" not in sales


def test_a_manager_may_assign_and_route_but_not_change_channels() -> None:
    manager = permissions_for("manager")
    assert {"inbox.assign", "contacts.reassign", "dashboard.manager", "settings.routing"} <= manager
    assert "settings.channels" not in manager


def test_a_viewer_may_do_nothing() -> None:
    assert permissions_for("viewer") == frozenset()


def test_an_unknown_role_gets_nothing_rather_than_everything() -> None:
    """Fail closed: a role added to the database but not here must not inherit power."""
    assert permissions_for("nonsense") == frozenset()
    assert scope_for("nonsense") == "own"


def test_owners_and_admins_hold_every_permission_anyone_holds() -> None:
    """A permission granted to some role but not to the owner is almost always a typo."""
    everything = frozenset().union(*(permissions_for(role) for role in ROLES))
    assert permissions_for("owner") == everything
    assert permissions_for("admin") == everything
