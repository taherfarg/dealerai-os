"""Turn a goal into a task DAG, and persist it as a run.

Two entry points, deliberately separate:

  * `create_run` takes a DAG somebody already knows. An event handler that
    always wants the same five tasks does not need a model to tell it so.
  * `plan` asks the Director for one. Grounding happens first, in SQL — the
    step everyone skips and the one that matters, because a plan written
    against a hallucinated inventory is a beautiful campaign for cars that
    sold last month.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..ai.prompts import load
from ..db.session import tenant_session
from ..events.bus import emit
from .executor import PlannedTask, validate_dag

log = structlog.get_logger()

#: A plan longer than this is the Director looping rather than planning.
MAX_TASKS = 25


class ProposedTask(BaseModel):
    id: str = Field(max_length=40, description="Short key, e.g. 't1'.")
    agent: str = Field(description="Exactly one of the agent names you were given.")
    depends_on: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    goal_understood: str = Field(max_length=400)
    tasks: list[ProposedTask]
    estimated_cost_usd: float = 0.0


_GROUND = """
select
  (select count(*) from vehicles where tenant_id = $1 and status = 'available') as available,
  (select count(*) from vehicles
    where tenant_id = $1 and status = 'available'
      and listed_at < now() - interval '60 days') as stale,
  (select count(*) from content_items
    where tenant_id = $1 and created_at > now() - interval '14 days') as recent_content,
  (select b.display_name is not null from brand_profiles b where b.tenant_id = $1)
    as brand_confirmed
"""


async def ground(tenant_id: UUID) -> dict[str, Any]:
    """Real facts, from SQL, before anything is asked of a model."""
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(_GROUND, tenant_id)
    return dict(row) if row else {}


async def plan(
    *, tenant_id: UUID, goal: str, agents: frozenset[str], run_id: UUID | None = None
) -> list[PlannedTask]:
    """Ask the Director for a DAG, and refuse it if it cannot run.

    The returned plan is validated before a row is written. A model will
    occasionally name an agent that does not exist or produce a cycle, and both
    are far cheaper to reject here than to debug as a run that hangs at 40%.
    """
    facts = await ground(tenant_id)
    result = await complete(
        TaskKind.ORCHESTRATE,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("director"), context=f"Available agents: {sorted(agents)}"),
        messages=(
            f"## Goal\n<untrusted>\n{goal}\n</untrusted>\n\n"
            f"## Grounding — the real state of this dealership right now\n"
            + "\n".join(f"{k}: {v}" for k, v in sorted(facts.items()))
        ),
        output_schema=Plan,
        run_id=run_id,
        trace_name="director_plan",
    )
    assert isinstance(result.parsed, Plan)  # noqa: S101 - schema-constrained
    proposed = result.parsed.tasks[:MAX_TASKS]
    tasks = [
        PlannedTask(task_key=t.id, agent=t.agent, depends_on=tuple(t.depends_on), input=t.input)
        for t in proposed
    ]
    validate_dag(tasks, known_agents=agents)
    return tasks


_INSERT_RUN = """
insert into agent_runs (tenant_id, trigger_type, triggered_by, goal, goal_input, plan,
                        status, autonomy)
values ($1,$2,$3,$4,$5,$6,'running',$7)
returning id
"""

_INSERT_TASK = """
insert into agent_tasks (tenant_id, run_id, task_key, agent, depends_on, input, status)
values ($1,$2,$3,$4,$5,$6,'pending')
"""


async def create_run(
    *,
    tenant_id: UUID,
    goal: str,
    tasks: list[PlannedTask],
    autonomy: str,
    trigger_type: str = "user",
    triggered_by: UUID | None = None,
    goal_input: dict[str, Any] | None = None,
) -> UUID:
    """Persist a run and its tasks, and hand it to the worker.

    The run, its tasks and the event that starts it are one transaction. A run
    whose start event escaped without its tasks would be picked up, find nothing
    to do, and report itself finished.
    """
    validate_dag(tasks)
    plan_json = [
        {"id": t.task_key, "agent": t.agent, "depends_on": list(t.depends_on), "input": t.input}
        for t in tasks
    ]
    async with tenant_session(tenant_id) as conn, conn.transaction():
        run_id: UUID = await conn.fetchval(
            _INSERT_RUN,
            tenant_id,
            trigger_type,
            triggered_by,
            goal,
            goal_input or {},
            {"tasks": plan_json},
            autonomy,
        )
        for task in tasks:
            await conn.execute(
                _INSERT_TASK,
                tenant_id,
                run_id,
                task.task_key,
                task.agent,
                list(task.depends_on),
                task.input,
            )
        await emit(
            conn,
            "agent_run.started",
            {"run_id": str(run_id)},
            tenant_id=tenant_id,
            dedupe_key=f"run.started:{run_id}",
            priority=3,
        )
    log.info("run_created", run_id=str(run_id), tasks=len(tasks), autonomy=autonomy)
    return run_id
