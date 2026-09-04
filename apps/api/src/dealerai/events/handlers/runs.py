"""Run lifecycle. See docs/02-agent-architecture.md § 3."""

from __future__ import annotations

from uuid import UUID

import structlog

from ...db.session import tenant_session
from ...orchestrator.executor import execute_run
from ..bus import Event, emit, handler

log = structlog.get_logger()


@handler("agent_run.started")
async def on_run_started(event: Event) -> None:
    """Drive the run.

    Idempotent by construction: `execute_run` decides everything from the task
    rows, so a redelivery after a crash resumes rather than repeats. That is
    what lets this ride the ordinary events queue instead of needing a worker
    and a lock of its own.
    """
    tenant_id = event.tenant_id
    if tenant_id is None:
        raise ValueError("agent_run.started requires a tenant")
    await execute_run(tenant_id, UUID(event.payload["run_id"]))


_RESUME = """
update agent_tasks
   set status = case
                  when output is not null then 'completed'
                  else 'pending'
                end,
       input = case when output is null then input || '{"_approved": true}'::jsonb else input end,
       error = null
 where id = $1 and status = 'waiting_approval'
 returning run_id, status
"""

_REJECT = """
update agent_tasks set status = 'failed', error = $2, finished_at = now()
 where id = $1 and status = 'waiting_approval'
 returning run_id
"""


@handler("approval.decided")
async def on_approval_decided(event: Event) -> None:
    """Un-pause the branch a human was holding.

    Two shapes of pause resume differently. A task the gate stopped before it
    ran goes back to `pending` carrying `_approved`, which is what stops the
    gate pausing it a second time — the human said yes to this task, not to the
    category. A task that ran and asked for sign-off on what it produced already
    has its output, so approval simply completes it.
    """
    tenant_id = event.tenant_id
    task_id = event.payload.get("task_id")
    if tenant_id is None or not task_id:
        return  # an approval not tied to a task — nothing to resume

    approved = event.payload.get("decision") == "approved"
    async with tenant_session(tenant_id) as conn, conn.transaction():
        if approved:
            row = await conn.fetchrow(_RESUME, UUID(task_id))
        else:
            row = await conn.fetchrow(
                _REJECT, UUID(task_id), event.payload.get("note") or "rejected by a human"
            )
        if row is None:
            return  # already decided, or not waiting
        await emit(
            conn,
            "agent_run.started",
            {"run_id": str(row["run_id"])},
            tenant_id=tenant_id,
            dedupe_key=f"run.started:{row['run_id']}",
            priority=3,
        )
    log.info("run_resumed", task_id=task_id, approved=approved)
