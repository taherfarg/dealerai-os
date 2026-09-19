"""Connected channel settings and WhatsApp template catalogue."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.errors import NotFound
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..events.bus import emit

router = APIRouter(prefix="/v1/channels", tags=["channels"])


class ChannelOut(BaseModel):
    id: UUID
    platform: str
    display_name: str | None
    handle: str | None
    mode: str | None
    status: str
    quality_rating: str | None
    sync_state: dict[str, Any]


class TemplateOut(BaseModel):
    id: UUID
    channel_id: UUID
    external_id: str
    name: str
    language: str
    category: str
    status: str
    body: str
    variables: list[str]
    rejected_reason: str | None
    synced_at: datetime


@router.get("", response_model=list[ChannelOut])
async def list_channels(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            """select id, platform, display_name, handle, mode, status,
                      quality_rating, sync_state
               from channels order by platform, display_name nulls last"""
        )
    return [dict(row) for row in rows]


@router.get("/{channel_id}/templates", response_model=list[TemplateOut])
async def list_templates(channel_id: UUID, ctx: Ctx) -> list[TemplateOut]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        # Another tenant's channel is a 404, exactly like one that does not
        # exist — an empty list would answer "it exists, and it is empty".
        if not await conn.fetchval("select exists(select 1 from channels where id=$1)", channel_id):
            raise NotFound("no such channel")
        rows = await conn.fetch(
            """select id, channel_id, external_id, name, language, category, status,
                      body, variables, rejected_reason, synced_at
               from message_templates where channel_id=$1
               order by name, language""",
            channel_id,
        )
    return [TemplateOut.model_validate(dict(row)) for row in rows]


@router.post("/{channel_id}/templates/sync", status_code=202)
async def sync_templates(
    channel_id: UUID,
    ctx: Annotated[TenantContext, Depends(require_permission("settings.channels"))],
) -> dict[str, str]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        exists = await conn.fetchval(
            "select exists(select 1 from channels where id=$1 and platform='whatsapp')", channel_id
        )
        if not exists:
            raise NotFound("no such WhatsApp channel")
        await emit(
            conn,
            "whatsapp.templates_sync_requested",
            {"channel_id": str(channel_id)},
            tenant_id=ctx.tenant_id,
            dedupe_key=f"template-sync:{channel_id}",
            priority=2,
        )
    return {"status": "queued"}
