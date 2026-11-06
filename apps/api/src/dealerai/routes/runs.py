"""Agent runs: start one, watch it, read what it did.

Starting a run returns immediately with the run id. Planning is a Pro call and
execution is many more; holding an HTTP request open for either means a browser
timeout decides whether a dealer's campaign happens.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
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


#: How often an open stream looks at the run again.
POLL_SECONDS = 1.0
#: A comment this often keeps a proxy from closing a quiet stream.
HEARTBEAT_SECONDS = 15.0
#: A run in one of these has nothing more to say.
FINISHED = frozenset({"completed", "partial", "failed", "cancelled"})


def _frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/{run_id}/stream")
async def stream_run(run_id: UUID, ctx: Ctx) -> StreamingResponse:
    """The run as it happens (docs/07-api-design.md § 4): `task.updated` when a
    task moves, `content.updated` when a piece appears or moves, `run.updated`
    when the run does, and `run.completed` last, after which the stream ends.

    A view, never the source of truth: it reads what the executor writes and
    says what changed. A client that drops reads `GET /v1/runs/{id}` and the
    content list, then opens a new stream.
    ponytail: polls once a second per open stream; LISTEN/NOTIFY from the
    executor if many people watch runs at the same time."""
    await _run(ctx.tenant_id, run_id)  # a 404 before the stream opens, not inside it

    async def events() -> AsyncIterator[str]:
        tasks: dict[str, str] = {}
        pieces: dict[UUID, str] = {}
        state: str | None = None
        quiet = 0.0
        yield ": connected\n\n"
        while True:
            async with tenant_session(ctx.tenant_id) as conn:
                run = await conn.fetchrow(
                    """select status, cost_usd::float8 as cost_usd, summary
                         from agent_runs where id = $1""",
                    run_id,
                )
                task_rows = await conn.fetch(
                    """select task_key, agent, status from agent_tasks
                        where run_id = $1 order by task_key""",
                    run_id,
                )
                piece_rows = await conn.fetch(
                    "select id, status from content_items where run_id = $1 order by created_at",
                    run_id,
                )
            if run is None:
                return
            frames = []
            for task in task_rows:
                if tasks.get(task["task_key"]) != task["status"]:
                    tasks[task["task_key"]] = task["status"]
                    frames.append(_frame("task.updated", dict(task)))
            for piece in piece_rows:
                if pieces.get(piece["id"]) != piece["status"]:
                    pieces[piece["id"]] = piece["status"]
                    frames.append(_frame("content.updated", dict(piece)))
            if run["status"] != state:
                state = run["status"]
                frames.append(_frame("run.updated", dict(run)))
            for frame in frames:
                yield frame
            if state in FINISHED:
                yield _frame("run.completed", dict(run))
                return
            quiet = 0.0 if frames else quiet + POLL_SECONDS
            if quiet >= HEARTBEAT_SECONDS:
                quiet = 0.0
                yield ": heartbeat\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _run(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(
            f"select {_RUN_COLUMNS} from agent_runs where id = $1",  # noqa: S608
            run_id,
        )
    if row is None:
        raise NotFound("no such run")
    return dict(row)
