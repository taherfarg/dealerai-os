"""Quick replies: `/price` in the composer becomes the dealership's own words.

Tenant-wide and read by everyone; written by whoever holds
settings.quick_replies (docs/sales/06-api-contract.md § 8). A save replaces the
whole reply — the form always sends all of it, and a partial update is how a
French body nobody meant to keep survives an edit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from ..core.errors import Conflict, NotFound, Unusable
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission

router = APIRouter(prefix="/v1/quick-replies", tags=["quick-replies"])

Editor = Annotated[TenantContext, Depends(require_permission("settings.quick_replies"))]


class Bodies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: str | None = Field(default=None, max_length=1000)
    en: str | None = Field(default=None, max_length=1000)
    fr: str | None = Field(default=None, max_length=1000)


class QuickReplyIn(BaseModel):
    #: Matches the table's check (0011): a slash and a lowercase word.
    shortcut: str = Field(pattern=r"^/[a-z0-9-]{1,30}$")
    title: str = Field(min_length=1, max_length=80)
    body: Bodies


class QuickReply(QuickReplyIn):
    id: UUID
    updated_at: datetime


_COLUMNS = "id, shortcut, title, body, updated_at"


def _bodies(body: Bodies) -> dict[str, str]:
    kept = {lang: text.strip() for lang, text in body.model_dump().items() if text and text.strip()}
    if not kept:
        raise Unusable("a quick reply needs its text in at least one language")
    return kept


@router.get("", response_model=list[QuickReply])
async def list_quick_replies(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(f"select {_COLUMNS} from quick_replies order by shortcut")
    return [dict(row) for row in rows]


@router.post("", response_model=QuickReply, status_code=status.HTTP_201_CREATED)
async def add_quick_reply(ctx: Editor, body: QuickReplyIn) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        try:
            row = await conn.fetchrow(
                f"""insert into quick_replies (tenant_id, shortcut, title, body, created_by)
                    values ($1, $2, $3, $4, $5) returning {_COLUMNS}""",
                ctx.tenant_id,
                body.shortcut,
                body.title,
                _bodies(body.body),
                ctx.user.id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(f"{body.shortcut} is already a quick reply") from exc
    return dict(row)


@router.patch("/{reply_id}", response_model=QuickReply)
async def save_quick_reply(ctx: Editor, reply_id: UUID, body: QuickReplyIn) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        try:
            row = await conn.fetchrow(
                f"""update quick_replies set shortcut = $2, title = $3, body = $4
                     where id = $1 returning {_COLUMNS}""",
                reply_id,
                body.shortcut,
                body.title,
                _bodies(body.body),
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict(f"{body.shortcut} is already a quick reply") from exc
    if row is None:
        raise NotFound("no such quick reply")
    return dict(row)


@router.delete("/{reply_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quick_reply(ctx: Editor, reply_id: UUID) -> None:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        deleted = await conn.fetchval(
            "delete from quick_replies where id = $1 returning id", reply_id
        )
    if deleted is None:
        raise NotFound("no such quick reply")
