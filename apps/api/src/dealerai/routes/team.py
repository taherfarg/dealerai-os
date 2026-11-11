"""Members and teams: who is here, what they may do, and who they work with."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from ..core.errors import Conflict, NotFound
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..sales.settings import SalesSettings
from .tenants import Role

router = APIRouter(prefix="/v1", tags=["team"])

TeamAdmin = Annotated[TenantContext, Depends(require_permission("settings.team"))]
Language = Literal["ar", "en", "fr"]

_MEMBERS = """
select m.user_id as id, m.role, m.languages, m.accepting_chats,
       p.full_name as name, p.email, p.avatar_url,
       coalesce(array_agg(tm.team_id) filter (where tm.team_id is not null), '{}') as team_ids,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open')                as open_conversations
from memberships m
left join profiles p on p.id = m.user_id
left join team_members tm on tm.user_id = m.user_id and tm.tenant_id = m.tenant_id
where m.tenant_id = $1
group by m.user_id, m.role, m.languages, m.accepting_chats, p.full_name, p.email, p.avatar_url
order by p.full_name nulls last
"""


class MemberOut(BaseModel):
    id: UUID
    name: str | None
    email: str | None
    avatar_url: str | None
    role: Role
    team_ids: list[UUID]
    languages: list[str]
    accepting_chats: bool
    open_conversations: int


class MemberPatch(BaseModel):
    role: Role | None = None
    team_ids: list[UUID] | None = None
    languages: list[Language] | None = None
    accepting_chats: bool | None = None


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    member_ids: list[UUID] = []


class TeamOut(BaseModel):
    id: UUID
    name: str
    member_ids: list[UUID]


async def _members(conn: asyncpg.Connection, tenant_id: UUID) -> list[dict[str, Any]]:
    return [dict(row) for row in await conn.fetch(_MEMBERS, tenant_id)]


@router.get("/members", response_model=list[MemberOut])
async def list_members(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        return await _members(conn, ctx.tenant_id)


@router.patch("/members/{user_id}", response_model=MemberOut)
async def patch_member(ctx: TeamAdmin, user_id: UUID, patch: MemberPatch) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        current = await conn.fetchval(
            "select role from memberships where tenant_id = $1 and user_id = $2",
            ctx.tenant_id,
            user_id,
        )
        if current is None:
            raise NotFound("no such member")

        # A workspace with no owner cannot be recovered: nobody can invite and
        # nobody can delete it. Refuse rather than explain it afterwards.
        if current == "owner" and patch.role not in (None, "owner"):
            owners = await conn.fetchval(
                "select count(*) from memberships where tenant_id = $1 and role = 'owner'",
                ctx.tenant_id,
            )
            if owners == 1:
                raise Conflict(
                    "this is the last owner; make someone else an owner first",
                    ar="هذا آخر مالك للمساحة؛ اجعل شخصًا آخر مالكًا أولًا.",
                )

        await conn.execute(
            """update memberships
               set role = coalesce($3, role),
                   languages = coalesce($4, languages),
                   accepting_chats = coalesce($5, accepting_chats)
               where tenant_id = $1 and user_id = $2""",
            ctx.tenant_id,
            user_id,
            patch.role,
            patch.languages,
            patch.accepting_chats,
        )
        if patch.team_ids is not None:
            await conn.execute(
                "delete from team_members where tenant_id = $1 and user_id = $2",
                ctx.tenant_id,
                user_id,
            )
            for team_id in patch.team_ids:
                await conn.execute(
                    """insert into team_members (tenant_id, team_id, user_id)
                       values ($1, $2, $3) on conflict do nothing""",
                    ctx.tenant_id,
                    team_id,
                    user_id,
                )
        members = await _members(conn, ctx.tenant_id)
    return next(member for member in members if member["id"] == user_id)


@router.get("/teams", response_model=list[TeamOut])
async def list_teams(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            """select t.id, t.name,
                      coalesce(array_agg(tm.user_id) filter (where tm.user_id is not null), '{}')
                        as member_ids
               from teams t
               left join team_members tm on tm.team_id = t.id
               where t.tenant_id = $1
               group by t.id, t.name
               order by t.name""",
            ctx.tenant_id,
        )
    return [dict(row) for row in rows]


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(ctx: TeamAdmin, body: TeamIn) -> TeamOut:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        try:
            team_id = await conn.fetchval(
                "insert into teams (tenant_id, name) values ($1, $2) returning id",
                ctx.tenant_id,
                body.name,
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(
                f"a team called {body.name!r} already exists",
                ar=f"يوجد فريق باسم «{body.name}» من قبل.",
            ) from exc
        for user_id in body.member_ids:
            await conn.execute(
                """insert into team_members (tenant_id, team_id, user_id)
                   values ($1, $2, $3) on conflict do nothing""",
                ctx.tenant_id,
                team_id,
                user_id,
            )
    return TeamOut(id=team_id, name=body.name, member_ids=body.member_ids)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def rename_team(ctx: TeamAdmin, team_id: UUID, body: TeamIn) -> dict[str, Any]:
    """A new name, and nothing else: membership is changed on the member
    (PATCH /v1/members/{id}), the one place it is written."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        try:
            renamed = await conn.fetchval(
                "update teams set name = $2 where id = $1 returning id", team_id, body.name
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(
                f"a team called {body.name!r} already exists",
                ar=f"يوجد فريق باسم «{body.name}» من قبل.",
            ) from exc
        if renamed is None:
            raise NotFound("no such team")
        members = await conn.fetchval(
            "select coalesce(array_agg(user_id), '{}') from team_members where team_id = $1",
            team_id,
        )
    return {"id": team_id, "name": body.name, "member_ids": members}


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(ctx: TeamAdmin, team_id: UUID) -> None:
    """Refused while routing sends customers to it: a rule pointing at a team
    that is gone routes a customer to nobody. Its people stay; its customers
    keep their owners and lose only the team."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        raw = await conn.fetchval("select sales_settings from tenants where id = $1", ctx.tenant_id)
        settings = SalesSettings.model_validate(raw or {})
        if settings.default_team_id == team_id or any(
            rule.team_id == team_id for rule in settings.routing_rules
        ):
            raise Conflict(
                "routing still sends customers to this team; change the routing first",
                ar="ما زال التوزيع يرسل عملاء إلى هذا الفريق؛ غيّر التوزيع أولًا.",
            )
        deleted = await conn.fetchval("delete from teams where id = $1 returning id", team_id)
        if deleted is None:
            raise NotFound("no such team")
