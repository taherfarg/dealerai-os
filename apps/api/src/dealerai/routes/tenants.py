from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import jwt
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..core.errors import Conflict, Forbidden, NotFound, Unusable
from ..core.permissions import ROLES
from ..core.security import AuthedUser, AuthUnavailable, Unauthenticated
from ..db.session import system_session, tenant_session
from ..deps import Ctx, CurrentUser, TenantContext, require_role

router = APIRouter(prefix="/v1", tags=["tenants"])

Role = Literal["viewer", "sales", "marketer", "manager", "admin", "owner"]
AutonomyMode = Literal["copilot", "assisted", "autopilot"]

INVITE_TTL_DAYS = 7


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------


class TenantOut(BaseModel):
    id: UUID
    slug: str
    name: str
    country: str
    timezone: str
    currency: str
    locales: list[str]
    plan: str
    autonomy_mode: AutonomyMode
    autonomy_rules: dict[str, Any]
    status: str


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9][a-z0-9-]*$")
    country: str = Field(default="AE", min_length=2, max_length=2)
    timezone: str = "Asia/Dubai"
    currency: str = Field(default="AED", min_length=3, max_length=3)
    locales: list[str] = Field(default_factory=lambda: ["en", "ar"])


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    timezone: str | None = None
    locales: list[str] | None = None
    autonomy_mode: AutonomyMode | None = None
    autonomy_rules: dict[str, Any] | None = None


class MemberOut(BaseModel):
    user_id: UUID
    role: Role
    email: str | None = None


#: Loose on purpose: Supabase decides what an address is. This only stops a
#: name typed into the email box from minting a link nobody can accept.
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class InviteCreate(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    role: Role = "sales"
    team_ids: list[UUID] = Field(default_factory=list, max_length=20)


class JoinedOut(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    role: Role


def _name(user: AuthedUser) -> str | None:
    """What they called themselves on sign-up, or what Google calls them."""
    metadata = user.claims.get("user_metadata") or {}
    name = metadata.get("full_name") or metadata.get("name")
    return str(name) if name else None


class InviteOut(BaseModel):
    token: str
    expires_at: datetime
    role: Role


class UsageOut(BaseModel):
    month: str
    spent_usd: float
    budget_usd: float
    remaining_usd: float


# --------------------------------------------------------------------------
# tenants
# --------------------------------------------------------------------------

_TENANT_COLUMNS = """
    id, slug, name, country, timezone, currency, locales, plan,
    autonomy_mode, autonomy_rules, status
"""


@router.get("/tenants", response_model=list[TenantOut])
async def list_my_tenants(user: CurrentUser) -> list[Any]:
    """Which workspaces does the caller belong to?

    Runs before any tenant context exists, so it goes through a SECURITY
    DEFINER function scoped to one user id — see 0003_bootstrap.sql. The
    browser has no direct table access since 0006_sales_core.sql, so this
    endpoint is how every client learns its workspaces.
    """
    async with system_session() as conn:
        rows = await conn.fetch("select * from app.tenants_for_user($1)", user.id)
    return [dict(r) for r in rows]


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, user: CurrentUser) -> Any:
    """Create a workspace and make the caller its owner.

    Both writes happen inside app.create_tenant_with_owner (0003_bootstrap.sql).
    They cannot be done from here: the caller is not yet a member of the tenant
    they are creating, so RLS correctly refuses every statement. A tenant with
    no owner would also be unreachable, so the two writes are never allowed to
    diverge into separate application statements.
    """
    async with system_session() as conn:
        try:
            tenant_id = await conn.fetchval(
                "select app.create_tenant_with_owner($1,$2,$3,$4,$5,$6,$7)",
                body.slug,
                body.name,
                body.country.upper(),
                body.timezone,
                body.currency.upper(),
                body.locales,
                user.id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(f"the slug {body.slug!r} is taken") from exc
        await conn.execute(
            "select app.remember_profile($1, $2, $3)", user.id, user.email, _name(user)
        )

    # Read back through a tenant context — the caller is a member now.
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(
            f"select {_TENANT_COLUMNS} from tenants where id = $1",  # noqa: S608
            tenant_id,
        )
    return dict(row)


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
async def get_tenant(tenant_id: UUID, ctx: Ctx) -> Any:
    if tenant_id != ctx.tenant_id:
        raise NotFound("no such tenant")
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(
            f"select {_TENANT_COLUMNS} from tenants where id = $1",  # noqa: S608
            tenant_id,
        )
    if row is None:
        raise NotFound("no such tenant")
    return dict(row)


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    ctx: Annotated[TenantContext, Depends(require_role("admin"))],
) -> Any:
    if tenant_id != ctx.tenant_id:
        raise NotFound("no such tenant")

    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        return await get_tenant(tenant_id, ctx)

    # Column names come from TenantUpdate's own fields, never from user input.
    assignments = ", ".join(f"{name} = ${i + 2}" for i, name in enumerate(fields))
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(
            f"update tenants set {assignments} where id = $1 returning {_TENANT_COLUMNS}",  # noqa: S608
            tenant_id,
            *fields.values(),
        )
    if row is None:
        raise NotFound("no such tenant")
    return dict(row)


@router.get("/tenants/{tenant_id}/usage", response_model=UsageOut)
async def tenant_usage(tenant_id: UUID, ctx: Ctx) -> UsageOut:
    if tenant_id != ctx.tenant_id:
        raise NotFound("no such tenant")
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(
            """select t.monthly_ai_budget_usd::float8 as budget,
                      coalesce((select sum(tr.cost_usd) from agent_traces tr
                                where tr.tenant_id = t.id
                                  and tr.created_at >= date_trunc('month', now())), 0)::float8
                        as spent
               from tenants t where t.id = $1""",
            tenant_id,
        )
    if row is None:
        raise NotFound("no such tenant")
    return UsageOut(
        month=datetime.now(UTC).strftime("%Y-%m"),
        spent_usd=round(row["spent"], 4),
        budget_usd=row["budget"],
        remaining_usd=round(max(row["budget"] - row["spent"], 0.0), 4),
    )


# --------------------------------------------------------------------------
# members and invitations
# --------------------------------------------------------------------------


@router.get("/tenants/{tenant_id}/members", response_model=list[MemberOut])
async def list_members(tenant_id: UUID, ctx: Ctx) -> list[Any]:
    if tenant_id != ctx.tenant_id:
        raise NotFound("no such tenant")
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            """select m.user_id, m.role, p.email
               from memberships m
               left join profiles p on p.id = m.user_id
               where m.tenant_id = $1
               order by m.created_at""",
            tenant_id,
        )
    return [dict(r) for r in rows]


def _invite_secret() -> str:
    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")
    return secret


@router.post(
    "/tenants/{tenant_id}/invites",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    tenant_id: UUID,
    body: InviteCreate,
    ctx: Annotated[TenantContext, Depends(require_role("admin"))],
) -> InviteOut:
    """Mint a signed, expiring invitation.

    Signed rather than stored: there is no invitations table to keep clean, and
    a leaked link expires on its own. Single use is enforced at redemption by
    the unique (tenant_id, user_id) on memberships — replaying a link cannot
    create a second membership or silently change someone's role.
    """
    if tenant_id != ctx.tenant_id:
        raise NotFound("no such tenant")
    if ROLES.index(body.role) > ROLES.index(ctx.role):
        raise Forbidden(
            f"cannot grant {body.role!r}: you are {ctx.role!r} and may not "
            "invite someone above your own role"
        )

    teams = list(dict.fromkeys(body.team_ids))
    async with tenant_session(ctx.tenant_id) as conn:
        tenant = await conn.fetchrow("select name from tenants where id = $1", tenant_id)
        known = await conn.fetchval("select count(*) from teams where id = any($1::uuid[])", teams)
    if tenant is None:
        raise NotFound("no such tenant")
    if known != len(teams):
        raise Unusable("an invitation can only name this workspace's teams")

    expires_at = datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS)
    token = jwt.encode(
        {
            "kind": "invite",
            "tenant_id": str(tenant_id),
            # For the page that opens the link, before its reader belongs anywhere.
            "tenant_name": tenant["name"],
            "role": body.role,
            "email": body.email.strip().lower(),
            "teams": [str(team) for team in teams],
            "exp": int(expires_at.timestamp()),
        },
        _invite_secret(),
        algorithm="HS256",
    )
    return InviteOut(token=token, expires_at=expires_at, role=body.role)


class InviteAccept(BaseModel):
    token: str


@router.post("/invites/accept", response_model=JoinedOut)
async def accept_invite(body: InviteAccept, user: CurrentUser) -> JoinedOut:
    try:
        claims = jwt.decode(body.token, _invite_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthenticated("this invitation has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthenticated("invalid invitation") from exc

    if claims.get("kind") != "invite":
        raise Unauthenticated("invalid invitation")
    # A link forwarded on WhatsApp is not an invitation for whoever opens it.
    if str(claims.get("email") or "").lower() != (user.email or "").strip().lower():
        raise Forbidden("this invitation is for another email address")

    tenant_id = UUID(claims["tenant_id"])
    # Idempotent in SQL, not here: replaying a link must not create a second
    # membership, change a role or move anybody between teams, and two clicks
    # at once must be one join (0013_sales_joining.sql).
    async with system_session() as conn:
        role = await conn.fetchval(
            "select app.accept_invite($1, $2, $3, $4::uuid[], $5, $6)",
            tenant_id,
            user.id,
            claims["role"],
            [UUID(team) for team in claims.get("teams") or []],
            user.email,
            _name(user),
        )
        # A member now, so the one-user read finds it.
        slug = await conn.fetchval(
            "select slug from app.tenants_for_user($1) where id = $2", user.id, tenant_id
        )
    return JoinedOut(tenant_id=tenant_id, tenant_slug=slug, role=role)


@router.delete("/tenants/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    tenant_id: UUID,
    user_id: UUID,
    ctx: Annotated[TenantContext, Depends(require_role("admin"))],
) -> None:
    if tenant_id != ctx.tenant_id:
        raise NotFound("no such tenant")
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        target = await conn.fetchval(
            "select role from memberships where tenant_id = $1 and user_id = $2",
            tenant_id,
            user_id,
        )
        if target is None:
            raise NotFound("not a member of this tenant")
        if target == "owner":
            remaining = await conn.fetchval(
                "select count(*) from memberships where tenant_id = $1 and role = 'owner'",
                tenant_id,
            )
            if remaining <= 1:
                raise Conflict("cannot remove the last owner of a workspace")
        await conn.execute(
            "delete from memberships where tenant_id = $1 and user_id = $2", tenant_id, user_id
        )
