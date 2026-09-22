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

#: Waiting_since is cleared the moment a reply is accepted, so how long the
#: customer actually waited is reconstructed from the messages: the last thing
#: they said before the answer went out.
MEDIAN_FIRST_RESPONSE = """
select percentile_cont(0.5) within group (order by seconds)::int
  from (
    select extract(epoch from (c.first_response_at - (
             select max(m.created_at) from messages m
              where m.conversation_id = c.id and m.direction = 'in' and m.kind = 'message'
                and m.created_at <= c.first_response_at))) as seconds
      from conversations c
     where c.first_response_at >= $2 and c.assigned_to = $1
  ) answered
 where seconds is not null
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
        timezone = await conn.fetchval("select timezone from tenants where id = $1", ctx.tenant_id)
        midnight = day_start(timezone or "UTC", now)
        today_from, today_until = window("today", timezone or "UTC", now)

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

        return {
            "replied_today": await conn.fetchval(REPLIED_TODAY, ctx.user.id, midnight) or 0,
            "median_first_response_seconds": await conn.fetchval(
                MEDIAN_FIRST_RESPONSE, ctx.user.id, midnight
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
