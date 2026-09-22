"""One agent_runs row per event-driven agent run.

The content agents get theirs from the planner. These four have no plan: the
customer wrote, so we draft. The row exists so `agent_traces` has a parent and
"why did it say that" is one join from a suggestion — which is the whole reason
`ai_suggestions.run_id` exists.

Deliberately not orchestrator/executor.py. That path checks the autonomy gate,
and REPLY_MESSAGE in copilot mode is NEEDS_APPROVAL, so every draft would
create an approvals row for a reviewer who does not exist: in the inbox the
person pressing Send is the approval (docs/sales/04-ai-copilot.md § 8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog

from ..db.session import tenant_session

log = structlog.get_logger()

_MAX_ERROR = 500


@dataclass(slots=True)
class Run:
    id: UUID
    #: Added to by the caller as each model call returns. What the cost
    #: envelope in docs/sales/04-ai-copilot.md § 10 is measured from.
    cost_usd: float = 0.0
    summary: str | None = None


@asynccontextmanager
async def agent_run(
    tenant_id: UUID, *, goal: str, goal_input: dict[str, Any]
) -> AsyncIterator[Run]:
    """Open a run, hand it over, close it however it ends.

    An exception closes the run as `failed` with its message and re-raises, so
    the event's own retry still happens. The row is a record, not a second
    error-handling mechanism.
    """
    async with tenant_session(tenant_id) as conn:
        run_id = await conn.fetchval(
            """insert into agent_runs (tenant_id, trigger_type, goal, goal_input, status, autonomy)
               values ($1, 'event', $2, $3::jsonb, 'running', 'copilot') returning id""",
            tenant_id,
            goal,
            goal_input,
        )
    run = Run(id=UUID(str(run_id)))
    try:
        yield run
    except Exception as exc:
        async with tenant_session(tenant_id) as conn:
            await conn.execute(
                """update agent_runs set status = 'failed', error = $2, cost_usd = $3,
                          finished_at = now() where id = $1""",
                run.id,
                str(exc)[:_MAX_ERROR],
                run.cost_usd,
            )
        raise
    else:
        async with tenant_session(tenant_id) as conn:
            await conn.execute(
                """update agent_runs set status = 'completed', summary = $2, cost_usd = $3,
                          finished_at = now() where id = $1""",
                run.id,
                run.summary,
                run.cost_usd,
            )
        log.info("agent_run_done", run_id=str(run.id), goal=goal, cost_usd=round(run.cost_usd, 6))
