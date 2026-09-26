"""GET /v1/stream — the one SSE connection a browser tab opens."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..db.session import tenant_session
from ..deps import Ctx
from ..realtime import Subscriber, hub

router = APIRouter(prefix="/v1", tags=["stream"])

#: A comment this often keeps proxies from closing a stream nothing is using.
HEARTBEAT_SECONDS = 15


@router.get("/stream")
async def stream(ctx: Ctx) -> StreamingResponse:
    """Ids only. The browser refetches over REST, so a missed event costs a
    request rather than showing a stale screen."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        owners = await conn.fetchval("select app.visible_owner_ids()")
        teams = await conn.fetchval("select app.my_team_ids()")

    subscriber = hub.subscribe(
        Subscriber(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user.id,
            scope=ctx.scope,
            visible_owner_ids=set(owners or []),
            team_ids=set(teams or []),
        )
    )

    async def events() -> AsyncIterator[str]:
        yield ": connected\n\n"
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(subscriber.queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                event = json.loads(raw)
                yield f"event: {event['type']}\ndata: {raw}\n\n"
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # nginx buffers streaming responses by default, which delays every event.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
