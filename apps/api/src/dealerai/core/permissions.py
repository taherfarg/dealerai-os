"""Who may do what, as data.

Visibility (whose rows you see) is enforced in Postgres; permissions (what you
may do) are enforced here and in the routes. Keeping them apart is deliberate:
one is a leak if it is wrong, the other is a button that should not have worked.
"""

from __future__ import annotations

#: Ordered least to most privileged. deps.require_role compares by index.
ROLES = ("viewer", "sales", "marketer", "manager", "admin", "owner")

_ADMIN = frozenset(
    {
        "inbox.send",
        "inbox.assign",
        "contacts.reassign",
        "contacts.merge",
        "leads.mark_won_lost",
        "pipeline.edit_stages",
        "dashboard.manager",
        "settings.channels",
        "settings.team",
        "settings.routing",
        "settings.quick_replies",
        "settings.knowledge",
        "settings.ai",
    }
)

PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": _ADMIN,
    "admin": _ADMIN,
    "manager": frozenset(
        {
            "inbox.send",
            "inbox.assign",
            "contacts.reassign",
            "contacts.merge",
            "leads.mark_won_lost",
            "dashboard.manager",
            "settings.routing",
            "settings.quick_replies",
        }
    ),
    "sales": frozenset({"inbox.send", "leads.mark_won_lost"}),
    "marketer": frozenset(),
    "viewer": frozenset(),
}

#: What a role may see. 'all' means no owner filter at all.
SCOPES: dict[str, str] = {
    "owner": "all",
    "admin": "all",
    "viewer": "all",
    "manager": "team",
    "sales": "own",
    "marketer": "own",
}


def permissions_for(role: str) -> frozenset[str]:
    """Unknown roles get nothing. Fail closed."""
    return PERMISSIONS.get(role, frozenset())


def scope_for(role: str) -> str:
    """Unknown roles see only their own rows, which for them is nothing."""
    return SCOPES.get(role, "own")
