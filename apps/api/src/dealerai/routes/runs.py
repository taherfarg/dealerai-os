"""Agent runs: start one, watch it, read what it did.

Starting a run returns immediately with the run id. Planning is a Pro call and
execution is many more; holding an HTTP request open for either means a browser
timeout decides whether a dealer's campaign happens.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from ..agents import base
from ..core.errors import NotFound, Unusable
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_role
from ..orchestrator import planner
from ..orchestrator.executor import PlanInvalid, PlannedTask

router = APIRouter(prefix="/v1/runs", tags=["runs"])

RunStatus = Literal[
    "planning", "running", "waiting_approval", "completed", "partial", "failed", "cancelled"
]


class TaskSpec(BaseModel):
    """A task in a caller-supplied DAG. Skips planning entirely."""

    task_key: str = Field(min_length=1, max_length=40)
    agent: str
    depends_on: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)


class RunCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    autonomy: Literal["copilot", "assisted", "autopilot"] | None = None
    #: Supply a DAG to run it as given; omit it and the Director plans one.
    tasks: list[TaskSpec] | None = None
    goal_input: dict[str, Any] = Field(default_factory=dict)


class TaskOut(BaseModel):
    task_key: str
    agent: str
    depends_on: list[str]
    status: str
    attempts: int
    output: dict[str, Any] | None = None
    error: str | None = None
    cost_usd: float


class RunOut(BaseModel):
    id: UUID
    goal: str | None
    status: RunStatus
    autonomy: str
    trigger_type: str
    cost_usd: float
    summary: str | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class RunDetail(RunOut):
    tasks: list[TaskOut]


_RUN_COLUMNS = """
    id, goal, status, autonomy, trigger_type, cost_usd::float8 as cost_usd,
    summary, error, started_at, finished_at
"""


@router.post("", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    body: RunCreate,
    ctx: Annotated[TenantContext, Depends(require_role("marketer"))],
) -> dict[str, Any]:
    """Plan and queue a run. 202, not 201 — the work has not happened yet."""
    async with tenant_session(ctx.tenant_id) as conn:
        autonomy = body.autonomy or await conn.fetchval(
            "select autonomy_mode from tenants where id = $1", ctx.tenant_id
        )

    if body.tasks:
        tasks = [
            PlannedTask(
                task_key=t.task_key,
                agent=t.agent,
                depends_on=tuple(t.depends_on),
                input=t.input,
            )
            for t in body.tasks
        ]
    else:
        agents = base.names()
        if not agents:
            raise Unusable("no agents are registered, so there is nothing to plan with")
        tasks = await planner.plan(tenant_id=ctx.tenant_id, goal=body.goal, agents=agents)

    try:
        run_id = await planner.create_run(
            tenant_id=ctx.tenant_id,
            goal=body.goal,
            tasks=tasks,
            autonomy=autonomy,
            trigger_type="user",
            triggered_by=ctx.user.id,
            goal_input=body.goal_input,
        )
    except PlanInvalid as exc:
        raise Unusable(str(exc)) from exc

    return await _run(ctx.tenant_id, run_id)


@router.get("", response_model=list[RunOut])
async def list_runs(
    ctx: Ctx,
    status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=50, le=200),
) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            f"""select {_RUN_COLUMNS} from agent_runs
                 where tenant_id = $1 and ($2::text is null or status = $2)
                 order by created_at desc limit $3""",  # noqa: S608
            ctx.tenant_id,
            status_filter,
            limit,
        )
    return [dict(r) for r in rows]


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: UUID, ctx: Ctx) -> dict[str, Any]:
    run = await _run(ctx.tenant_id, run_id)
    async with tenant_session(ctx.tenant_id) as conn:
        tasks = await conn.fetch(
            """select task_key, agent, depends_on, status, attempts, output, error,
                      cost_usd::float8 as cost_usd
                 from agent_tasks where run_id = $1 order by task_key""",
            run_id,
        )
    run["tasks"] = [dict(t) for t in tasks]
    return run


async def _run(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(
            f"select {_RUN_COLUMNS} from agent_runs where id = $1",  # noqa: S608
            run_id,
        )
    if row is None:
        raise NotFound("no such run")
    return dict(row)
