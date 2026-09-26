"""A person's own notifications. RLS makes "own" true; nothing here filters by user."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field, model_validator

from ..db.session import tenant_session
from ..deps import Ctx

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str | None
    href: str | None
    entity: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    data: list[NotificationOut]
    unread: int


class ReadIn(BaseModel):
    ids: list[UUID] = Field(default_factory=list)
    all: bool = False

    @model_validator(mode="after")
    def one_or_the_other(self) -> ReadIn:
        if bool(self.ids) == self.all:
            raise ValueError("provide either ids or all")
        return self


@router.get("", response_model=NotificationPage)
async def list_notifications(
    ctx: Ctx, unread_only: bool = False, limit: int = 50
) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            """select id, kind, title, body, href, entity, read_at, created_at
               from notifications
               where ($1::boolean is not true or read_at is null)
               order by created_at desc limit $2""",
            unread_only,
            min(limit, 100),
        )
        unread = await conn.fetchval("select count(*) from notifications where read_at is null")
    return {"data": [dict(row) for row in rows], "unread": unread}


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(ctx: Ctx, body: ReadIn) -> Response:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await conn.execute(
            """update notifications set read_at = now()
               where read_at is null and ($2::boolean or id = any($1::uuid[]))""",
            body.ids,
            body.all,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
