"""My day: what to do next, in the order to do it.

One request, because it is one screen refreshed together (docs/sales/08-screens.md
§ 10). Every number is the caller's own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..db.queries.crm import HOT_LEADS, TASKS_LIST
from ..db.queries.inbox import list_sql
from ..db.session import tenant_session
from ..deps import Ctx
from ..sales import dashboard as numbers
from ..sales.clock import zone
from ..sales.settings import SalesSettings
from .inbox import ConversationSummary, summary
from .leads import LeadOut, lead_out
from .tasks import SalesTask, day_start, task_out, window

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])

#: Enough to act on before breakfast; the full lists are one tap away.
SHOWN = 5

REPLIED_TODAY = """
select count(*) from messages
 where author_user_id = $1 and direction = 'out' and kind = 'message' and created_at >= $2
"""


class MyDay(BaseModel):
    replied_today: int
    #: Null before the first reply of the day — a zero would read as instant.
    median_first_response_seconds: int | None
    accepting_chats: bool
    waiting_on_you: list[ConversationSummary]
    due_today: list[SalesTask]
    hot_leads: list[LeadOut]


@router.get("/me", response_model=MyDay)
async def my_day(ctx: Ctx) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        tenant = await conn.fetchrow(
            "select timezone, sales_settings from tenants where id = $1", ctx.tenant_id
        )
        timezone = tenant["timezone"] or "UTC"
        midnight = day_start(timezone, now)
        today_from, today_until = window("today", timezone, now)

        # The queue, through the inbox's own query: two definitions of "mine,
        # waiting" would drift, and this screen is the one that says the queue
        # is wrong.
        conversations = await conn.fetch(
            list_sql("mine", with_cursor=False), ctx.user.id, "open", "", "", 50
        )
        waiting = [summary(row, now) for row in conversations if row["waiting_since"] is not None][
            :SHOWN
        ]

        tasks = await conn.fetch(TASKS_LIST, ctx.user.id, False, today_from, today_until, SHOWN)
        leads = await conn.fetch(HOT_LEADS, ctx.user.id, SHOWN)
        # The dashboard's definition, filtered to me: two medians that could
        # disagree would be one too many (sales/dashboard.py).
        waits = await numbers.answered(
            conn,
            midnight,
            now,
            tz=zone(timezone),
            settings=SalesSettings.model_validate(tenant["sales_settings"] or {}),
        )

        return {
            "replied_today": await conn.fetchval(REPLIED_TODAY, ctx.user.id, midnight) or 0,
            "median_first_response_seconds": numbers.median_of(
                [wait for wait in waits if wait.assigned_to == ctx.user.id]
            ),
            "accepting_chats": bool(
                await conn.fetchval(
                    """select accepting_chats from memberships
                        where tenant_id = $1 and user_id = $2""",
                    ctx.tenant_id,
                    ctx.user.id,
                )
            ),
            "waiting_on_you": waiting,
            "due_today": [task_out(task) for task in tasks],
            "hot_leads": [lead_out(lead) for lead in leads],
        }
