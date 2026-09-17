"""Request-scoped dependencies. Every tenant route takes `ctx`.

There is no ambient tenant and no server-side "current workspace" session: the
caller states which tenant it means via X-Tenant-Id and we verify membership.
A user in two dealerships can keep both open in two tabs without one leaking
into the other.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from .core.errors import Forbidden, NotFound
from .core.permissions import ROLES, permissions_for, scope_for  # routes import ROLES from here
from .core.security import AuthedUser, Unauthenticated, decode_supabase_jwt
from .db.session import system_session


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID
    user: AuthedUser
    role: str

    @property
    def scope(self) -> str:
        """What this caller may see: own, team or all. Passed to tenant_session."""
        return scope_for(self.role)

    @property
    def permissions(self) -> frozenset[str]:
        return permissions_for(self.role)

    def may(self, permission: str) -> bool:
        return permission in self.permissions

    def at_least(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


async def current_user(request: Request) -> AuthedUser:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthenticated("expected an Authorization: Bearer header")
    return decode_supabase_jwt(token)


CurrentUser = Annotated[AuthedUser, Depends(current_user)]


async def tenant_ctx(
    user: CurrentUser,
    x_tenant_id: Annotated[UUID, Header(alias="X-Tenant-Id")],
) -> TenantContext:
    """Resolve and authorise the tenant for this request.

    A tenant the caller is not a member of raises 404, never 403. 403 confirms
    the workspace exists, which turns the endpoint into an enumeration oracle.
    """
    # This lookup runs before any tenant context exists — it is the query that
    # establishes one — so a plain SELECT would be filtered to nothing by RLS.
    # app.member_role is SECURITY DEFINER and scoped to a single (tenant, user)
    # pair; see 0004_membership_policy_recursion.sql.
    async with system_session() as conn:
        role = await conn.fetchval("select app.member_role($1, $2)", x_tenant_id, user.id)
    if role is None:
        raise NotFound("no such tenant")
    return TenantContext(tenant_id=x_tenant_id, user=user, role=role)


Ctx = Annotated[TenantContext, Depends(tenant_ctx)]


def require_role(minimum: str) -> Callable[[TenantContext], Awaitable[TenantContext]]:
    """Dependency factory guarding a route by role.

    Usage: `_: Annotated[TenantContext, Depends(require_role("admin"))]`
    """
    if minimum not in ROLES:
        raise ValueError(f"unknown role {minimum!r}; expected one of {ROLES}")

    async def guard(ctx: Ctx) -> TenantContext:
        if not ctx.at_least(minimum):
            raise Forbidden(f"this action requires the {minimum} role or higher")
        return ctx

    return guard


def require_permission(permission: str) -> Callable[[TenantContext], Awaitable[TenantContext]]:
    """Guard a route by permission rather than by rank.

    Rank is the wrong question for most sales actions: a manager may reassign a
    customer, and an admin cannot do it any better. Usage:
    `_: Annotated[TenantContext, Depends(require_permission("contacts.reassign"))]`
    """

    async def guard(ctx: Ctx) -> TenantContext:
        if not ctx.may(permission):
            raise Forbidden(f"this action requires the {permission} permission")
        return ctx

    return guard
