"""My day, and the manager's dashboard: what to do next, and what needs doing.

Each is one request, because each is one screen refreshed together
(docs/sales/08-screens.md § 10–11). My day's numbers are the caller's own; the
dashboard's are whatever the caller may see.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..db.queries import dashboard as q
from ..db.queries.crm import HOT_LEADS, TASKS_LIST
from ..db.queries.inbox import list_sql
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..sales import dashboard as numbers
from ..sales.clock import zone
from ..sales.dashboard import Headline
from ..sales.settings import SalesSettings
from .inbox import ConversationSummary, UserRef, summary
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


# ---------------------------------------------------------------------------
# The manager's dashboard — docs/sales/08-screens.md § 11
# ---------------------------------------------------------------------------

Manager = Annotated[TenantContext, Depends(require_permission("dashboard.manager"))]

#: Waiting conversations returned: the list shows the first few, and the team
#: table's per-person view filters the same list rather than asking again.
WAITING_READ = 50


class Tiles(BaseModel):
    new_conversations: int
    waiting_now: int
    median_first_response_seconds: int | None
    first_response_target_seconds: int
    missed_targets: int
    new_leads: int
    hot_leads: int
    won: int
    lost: int


class RepRow(BaseModel):
    user: UserRef
    open: int
    waiting: int
    median_first_response_seconds: int | None
    missed_targets: int
    overdue_tasks: int
    hot: int
    warm: int
    cold: int
    won_this_month: int


class StageTotal(BaseModel):
    pipeline_id: UUID
    pipeline_name: str
    stage_id: UUID
    stage_name: str
    leads: int


class SourceCount(BaseModel):
    source: str
    leads: int


class Share(BaseModel):
    inbox: int
    phone: int


class PhoneShare(BaseModel):
    this_week: Share
    last_week: Share


class AttentionItem(BaseModel):
    kind: Literal["waiting", "hot_lead", "overdue_tasks"]
    #: The conversation, the lead, or the salesperson.
    id: UUID
    #: The customer — or, for overdue_tasks, the salesperson.
    name: str | None
    owner: UserRef | None
    since: datetime | None
    count: int | None


class Brief(BaseModel):
    date: date
    headline: Headline | None
    items: list[AttentionItem]


class ManagerDashboard(BaseModel):
    date: date
    tiles: Tiles
    waiting: list[ConversationSummary]
    team: list[RepRow]
    pipeline: list[StageTotal]
    sources: list[SourceCount]
    phone_share: PhoneShare
    brief: Brief


def _person(user_id: UUID | None, name: str | None) -> dict[str, Any] | None:
    return None if user_id is None else {"id": user_id, "name": name}


@router.get("/manager", response_model=ManagerDashboard)
async def manager_dashboard(
    ctx: Manager, day: Annotated[date | None, Query(alias="date")] = None
) -> dict[str, Any]:
    """A manager's morning in one request, because it is one screen refreshed
    together (docs/sales/06-api-contract.md § 7).

    Every number reads through the caller's own visibility — her teams'
    numbers because Postgres shows her nothing else. `date` moves the counted
    day; waiting, hot and overdue are always now; the brief is always today's.
    """
    now = datetime.now(UTC)
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        tenant = await conn.fetchrow(
            "select timezone, sales_settings from tenants where id = $1", ctx.tenant_id
        )
        tz = zone(tenant["timezone"])
        settings = SalesSettings.model_validate(tenant["sales_settings"] or {})
        today = now.astimezone(tz).date()
        shown = day or today
        since, until = numbers.day_window(shown, tz)
        waits = await numbers.answered(conn, since, until, tz=tz, settings=settings)
        facts = await numbers.facts(conn, since, until, now, waits, settings)
        team = await numbers.team(
            conn, ctx.tenant_id, since, until, now, waits, numbers.month_start(shown, tz)
        )
        rows = await conn.fetch(
            list_sql("all" if ctx.scope == "all" else "team", with_cursor=False),
            ctx.user.id,
            "open",
            "",
            "",
            WAITING_READ,
        )
        pipeline = await conn.fetch(q.PIPELINE)
        sources = await conn.fetch(q.SOURCES, now - timedelta(days=30))
        share = await conn.fetchrow(q.SHARE, now - timedelta(days=14), now - timedelta(days=7))
        items = await numbers.attention(conn, now)
        headline = await conn.fetchval(
            "select headline from sales_briefs where user_id = $1 and brief_date = $2",
            ctx.user.id,
            today,
        )
    return {
        "date": shown,
        "tiles": {key: facts[key] for key in Tiles.model_fields},
        "waiting": [summary(row, now) for row in rows if row["waiting_since"] is not None],
        "team": [
            {
                "user": _person(rep["id"], rep["name"]),
                **{key: rep[key] for key in RepRow.model_fields if key != "user"},
            }
            for rep in team
        ],
        "pipeline": [dict(row) for row in pipeline],
        "sources": [dict(row) for row in sources],
        "phone_share": {
            "this_week": {"inbox": share["inbox_this_week"], "phone": share["phone_this_week"]},
            "last_week": {"inbox": share["inbox_last_week"], "phone": share["phone_last_week"]},
        },
        "brief": {
            "date": today,
            "headline": headline,
            "items": [
                {
                    "kind": item["kind"],
                    "id": item["id"],
                    "name": item["name"],
                    "owner": _person(item["owner_id"], item["owner_name"]),
                    "since": item["since"],
                    "count": item["count"],
                }
                for item in items
            ],
        },
    }
