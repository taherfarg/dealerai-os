"""The morning brief (docs/sales/05-workflows.md § 13).

One per reader, each gathered in that reader's own session: a manager's brief
is her teams' numbers because the session shows her nothing else, exactly as
her dashboard is. Idempotent per reader and day, so a retried event writes
nobody's twice.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog

from ...agents.sales import brief as brief_agent
from ...core.errors import BudgetExceeded
from ...core.permissions import permissions_for, scope_for
from ...core.words import Words
from ...db.session import tenant_session
from ...guards import facts as facts_guard
from ...sales import dashboard
from ...sales.clock import zone
from ...sales.runs import agent_run
from ...sales.settings import SalesSettings
from ..bus import Event, handler
from .notify import notify

log = structlog.get_logger()


@handler("sales.brief_due")
async def on_brief_due(event: Event) -> None:
    if event.tenant_id is None:
        raise ValueError("sales.brief_due requires a tenant")
    tenant_id = event.tenant_id
    day = date.fromisoformat(str(event.payload["date"]))
    async with tenant_session(tenant_id) as conn:
        tenant = await conn.fetchrow(
            "select timezone, sales_settings from tenants where id = $1", tenant_id
        )
        members = await conn.fetch(
            "select user_id, role from memberships where tenant_id = $1", tenant_id
        )
    if tenant is None:
        return
    tz = zone(tenant["timezone"])
    settings = SalesSettings.model_validate(tenant["sales_settings"] or {})
    for member in members:
        if "dashboard.manager" in permissions_for(member["role"]):
            await _brief(tenant_id, member["user_id"], scope_for(member["role"]), day, tz, settings)


async def _brief(
    tenant_id: UUID,
    user_id: UUID,
    scope: str,
    day: date,
    tz: ZoneInfo,
    settings: SalesSettings,
) -> None:
    now = datetime.now(UTC)
    yesterday = day - timedelta(days=1)
    since, until = dashboard.day_window(yesterday, tz)
    async with tenant_session(tenant_id, user_id=user_id, scope=scope) as conn:
        if await conn.fetchval(
            "select exists (select 1 from sales_briefs where user_id = $1 and brief_date = $2)",
            user_id,
            day,
        ):
            return
        waits = await dashboard.answered(conn, since, until, tz=tz, settings=settings)
        facts = await dashboard.facts(conn, since, until, now, waits, settings)
        team = await dashboard.team(
            conn, tenant_id, since, until, now, waits, dashboard.month_start(yesterday, tz)
        )
        cars = await dashboard.most_asked(conn, since, until)

    block = dashboard.render_facts(yesterday, facts, team, cars)
    headline = await _headline(tenant_id, user_id, day, facts, block)

    async with tenant_session(tenant_id, user_id=user_id, scope=scope) as conn:
        brief_id = await conn.fetchval(
            """insert into sales_briefs (tenant_id, user_id, brief_date, headline, facts)
               values ($1, $2, $3, $4, $5)
               on conflict do nothing returning id""",
            tenant_id,
            user_id,
            day,
            headline,
            facts,
        )
        if brief_id is not None:
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind="brief_ready",
                title=Words("Your morning brief", "موجزك الصباحي"),
                # Written in both languages from the start, for the dashboard.
                body=Words(headline["en"], headline["ar"]) if headline else None,
                entity={"type": "brief", "id": str(brief_id)},
                dedupe_key=f"brief:{day}",
            )


async def _headline(
    tenant_id: UUID, user_id: UUID, day: date, facts: dict[str, Any], block: str
) -> dict[str, str] | None:
    """None when there is nothing to say, no budget left, or a line the guard refused."""
    if not (facts["new_conversations"] or facts["waiting_now"] or facts["overdue_tasks"]):
        return None  # a quiet day is not worth a model call
    try:
        async with agent_run(
            tenant_id, goal="brief", goal_input={"user_id": str(user_id), "date": day.isoformat()}
        ) as run:
            written = await brief_agent.write(tenant_id=tenant_id, run_id=run.id, facts=block)
            run.cost_usd += written.cost_usd
    except BudgetExceeded:
        log.warning("brief_without_headline_budget", tenant_id=str(tenant_id))
        return None
    if written.headline is None:
        return None
    refused = facts_guard.check(f"{written.headline.en}\n{written.headline.ar}", facts=block)
    if refused:
        log.warning("brief_headline_refused", numbers=[finding.detail for finding in refused])
        return None
    return written.headline.model_dump()
