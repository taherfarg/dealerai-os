"""Content tools: what has been posted, and where the gaps are.

`create_draft` is the only mutating tool here, and it writes a draft — nothing
in this module publishes. Publishing is a separate group an agent has to be
given explicitly, which is how the Copywriter is prevented from posting.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from ..db.session import tenant_session
from ..deps import TenantContext
from .registry import tool

GROUP = "content"


@tool(name="list_recent_content", group=GROUP)
async def list_recent_content(
    ctx: TenantContext, *, days: int = 14, limit: int = 30
) -> list[dict[str, Any]]:
    """What this dealership has posted recently.

    Read it before proposing anything: repeating last week's angle on the same
    car is the most common way generated content becomes visibly generated.
    """
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            """select id, kind, concept, status, vehicle_id, scheduled_at, published_at
                 from content_items
                where created_at > now() - make_interval(days => $1)
                order by created_at desc limit $2""",
            days,
            min(limit, 100),
        )
    return [dict(r) | {"id": str(r["id"])} for r in rows]


@tool(name="create_draft", group=GROUP, mutates=True)
async def create_draft(
    ctx: TenantContext,
    *,
    kind: Literal["post", "story", "reel", "carousel"],
    concept: str,
    vehicle_id: str | None = None,
    locale: str = "en",
    caption: str = "",
) -> dict[str, Any]:
    """Create a draft content item. It is not published and not scheduled.

    A draft is how work leaves your hands: a human or a later task picks it up.
    Anything you write here still passes the price, inventory and brand guards
    before it can go anywhere.
    """
    vehicle = None
    if vehicle_id:
        try:
            vehicle = UUID(vehicle_id)
        except ValueError:
            vehicle = None

    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        row = await conn.fetchrow(
            """insert into content_items (tenant_id, kind, concept, vehicle_id, status)
               values ($1,$2,$3,$4,'draft') returning id, status""",
            ctx.tenant_id,
            kind,
            concept,
            vehicle,
        )
        if caption:
            await conn.execute(
                """insert into content_copy (tenant_id, content_item_id, locale, caption)
                   values ($1,$2,$3,$4)""",
                ctx.tenant_id,
                row["id"],
                locale,
                caption,
            )
        await conn.execute(
            """insert into audit_log (tenant_id, actor_type, actor_id, action,
                                      entity_type, entity_id, after)
               values ($1,'agent',$2,'content.draft_created','content_item',$3,$4)""",
            ctx.tenant_id,
            "tool:create_draft",
            row["id"],
            {"kind": kind, "concept": concept, "locale": locale},
        )
    return {"id": str(row["id"]), "status": row["status"]}
