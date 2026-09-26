"""Who am I, here. The first call every screen makes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from ..db.session import tenant_session
from ..deps import Ctx

router = APIRouter(prefix="/v1", tags=["me"])


class MeTenant(BaseModel):
    id: UUID
    slug: str
    name: str
    timezone: str
    currency: str
    logo_url: str | None = None
    accent_color: str | None = None


class MeUser(BaseModel):
    id: UUID
    name: str | None
    email: str | None
    avatar_url: str | None = None


class MeOut(BaseModel):
    user: MeUser
    tenant: MeTenant
    role: str
    scope: str
    team_ids: list[UUID]
    permissions: list[str]
    accepting_chats: bool


class MePatch(BaseModel):
    accepting_chats: bool


async def _load(ctx: Ctx) -> MeOut:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        tenant = await conn.fetchrow(
            """select t.id, t.slug, t.name, t.timezone, t.currency,
                      -- the logo lives in brand_assets behind a signed URL; it joins
                      -- this response with the brand settings screen
                      b.colors->>'primary' as accent_color
               from tenants t
               left join brand_profiles b on b.tenant_id = t.id
               where t.id = $1""",
            ctx.tenant_id,
        )
        member = await conn.fetchrow(
            """select m.accepting_chats, p.full_name, p.email, p.avatar_url
               from memberships m
               left join profiles p on p.id = m.user_id
               where m.tenant_id = $1 and m.user_id = $2""",
            ctx.tenant_id,
            ctx.user.id,
        )
        teams = await conn.fetch("select team_id from team_members where user_id = $1", ctx.user.id)
    data: dict[str, Any] = dict(member) if member else {}
    return MeOut(
        user=MeUser(
            id=ctx.user.id,
            name=data.get("full_name"),
            email=data.get("email") or ctx.user.email,
            avatar_url=data.get("avatar_url"),
        ),
        tenant=MeTenant(**dict(tenant)),
        role=ctx.role,
        scope=ctx.scope,
        team_ids=[t["team_id"] for t in teams],
        permissions=sorted(ctx.permissions),
        accepting_chats=bool(data.get("accepting_chats", True)),
    )


@router.get("/me", response_model=MeOut)
async def get_me(ctx: Ctx) -> MeOut:
    return await _load(ctx)


@router.patch("/me", response_model=MeOut)
async def patch_me(ctx: Ctx, patch: MePatch) -> MeOut:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await conn.execute(
            """update memberships set accepting_chats = $3
               where tenant_id = $1 and user_id = $2""",
            ctx.tenant_id,
            ctx.user.id,
            patch.accepting_chats,
        )
    return await _load(ctx)
