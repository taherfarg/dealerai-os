"""Runs a planned DAG of agent tasks to completion, or to the first thing that
needs a human.

There is no second worker and no second queue. A run is driven by an
`agent_run.started` event on the existing events table, so it inherits the lock,
the retry backoff, the dead-letter and the stuck-job reaper that already work.

**Resumability is the database, not memory.** Nothing about a run lives in this
process. Kill the worker mid-run and the event lock expires; the reaper releases
it; another worker picks it up, reloads the tasks, and finds the completed ones
already marked completed. That is the whole recovery story, and it is why every
task's result is committed the moment it is produced rather than at the end.

The DAG functions at the top are pure — the parts most likely to be wrong are
the parts that need no database to test.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog

from ..agents import base
from ..db.session import tenant_session
from ..events.bus import emit
from . import approvals
from .gate import GateContext, Verdict, decide

log = structlog.get_logger()

#: Task statuses that will never change again without a human.
TERMINAL = frozenset({"completed", "failed", "skipped"})

#: One re-run per task. An agent that fails twice on the same input fails the
#: third time too, and each attempt costs a model call.
MAX_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    task_key: str
    agent: str
    depends_on: tuple[str, ...]
    input: dict[str, Any]
    output: dict[str, Any] | None
    status: str
    attempts: int


@dataclass(frozen=True, slots=True)
class PlannedTask:
    """A task as the planner proposes it, before it exists in the database."""

    task_key: str
    agent: str
    depends_on: tuple[str, ...] = ()
    input: dict[str, Any] = field(default_factory=dict)


class PlanInvalid(ValueError):
    """The proposed DAG cannot be executed. Raised before anything is written."""


# --------------------------------------------------------------------------
# the DAG — pure
# --------------------------------------------------------------------------


def validate_dag(tasks: list[PlannedTask], *, known_agents: frozenset[str] | None = None) -> None:
    """Reject a plan that cannot run, before a single row is inserted.

    A model wrote this DAG. It will occasionally name an agent that does not
    exist, depend on a task it forgot to include, or produce a cycle. Each of
    those is a run that hangs or crashes halfway, which is far more expensive
    to understand than a rejected plan.
    """
    if not tasks:
        raise PlanInvalid("the plan has no tasks")

    keys = [t.task_key for t in tasks]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise PlanInvalid(f"duplicate task keys: {', '.join(sorted(duplicates))}")

    known = base.names() if known_agents is None else known_agents
    unknown_agents = {t.agent for t in tasks} - known
    if unknown_agents:
        raise PlanInvalid(f"no such agent: {', '.join(sorted(unknown_agents))}")

    as_set = set(keys)
    for task in tasks:
        missing = set(task.depends_on) - as_set
        if missing:
            raise PlanInvalid(f"{task.task_key} depends on missing {', '.join(sorted(missing))}")
        if task.task_key in task.depends_on:
            raise PlanInvalid(f"{task.task_key} depends on itself")

    # Kahn's algorithm: whatever is left when nothing more can be removed is a
    # cycle.
    pending = {t.task_key: set(t.depends_on) for t in tasks}
    while True:
        free = [k for k, deps in pending.items() if not deps]
        if not free:
            break
        for key in free:
            del pending[key]
        for deps in pending.values():
            deps.difference_update(free)
    if pending:
        raise PlanInvalid(f"the plan has a cycle among: {', '.join(sorted(pending))}")


def ready(tasks: list[Task]) -> list[Task]:
    """Tasks whose dependencies have all completed.

    Only `completed` counts. A dependency that failed, was skipped, or is
    waiting for a human does not release the tasks below it — that branch is
    over until something changes.
    """
    completed = {t.task_key for t in tasks if t.status == "completed"}
    return [t for t in tasks if t.status == "pending" and all(d in completed for d in t.depends_on)]


def blocked(tasks: list[Task]) -> list[Task]:
    """Pending tasks that can never become ready.

    Without this a run with one failed task hangs forever holding its event,
    because `ready()` correctly returns nothing and the loop correctly waits.
    """
    dead = {t.task_key for t in tasks if t.status in ("failed", "skipped")}
    if not dead:
        return []
    # A dependency of a dead task is dead too; walk until it stops growing.
    while True:
        newly = {
            t.task_key
            for t in tasks
            if t.status == "pending"
            and t.task_key not in dead
            and any(d in dead for d in t.depends_on)
        }
        if not newly:
            break
        dead |= newly
    return [t for t in tasks if t.status == "pending" and t.task_key in dead]


def resolve_input(raw: dict[str, Any], outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Replace `from_task` / `from_tasks` with the real outputs.

    Resolved here from what the earlier task actually produced, never by asking
    the model again — docs/02 § 3. Re-prompting would let the second call
    disagree with the first about what the first said.
    """
    resolved = {k: v for k, v in raw.items() if k not in ("from_task", "from_tasks")}
    single = raw.get("from_task")
    if isinstance(single, str):
        resolved.update(outputs.get(single, {}))
    many = raw.get("from_tasks")
    if isinstance(many, list):
        resolved["from_tasks"] = {k: outputs.get(k, {}) for k in many if isinstance(k, str)}
    return resolved


def run_status(tasks: list[Task]) -> str:
    """What the run row should say now."""
    if any(t.status == "waiting_approval" for t in tasks):
        return "waiting_approval"
    if any(t.status not in TERMINAL for t in tasks):
        return "running"
    if all(t.status == "completed" for t in tasks):
        return "completed"
    if any(t.status == "completed" for t in tasks):
        return "partial"
    return "failed"


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------

_LOAD = """
select id, task_key, agent, depends_on, input, output, status, attempts
  from agent_tasks where run_id = $1 order by task_key
"""

#: Claiming is what makes two workers on the same run safe. A reaped event can
#: be picked up while the original worker is still alive and slow, and both
#: would otherwise run the same task and charge for it twice.
_CLAIM = """
update agent_tasks set status = 'running', attempts = attempts + 1, started_at = now()
 where id = $1 and status = 'pending'
 returning id
"""

_FINISH = """
update agent_tasks
   set status = $2, output = $3, error = $4, cost_usd = cost_usd + $5, finished_at = now()
 where id = $1
"""

_SKIP = """
update agent_tasks set status = 'skipped', error = $2, finished_at = now() where id = $1
"""

_RETRY = "update agent_tasks set status = 'pending' where id = $1"


async def _load(tenant_id: UUID, run_id: UUID) -> list[Task]:
    async with tenant_session(tenant_id) as conn:
        rows = await conn.fetch(_LOAD, run_id)
    return [
        Task(
            id=r["id"],
            task_key=r["task_key"],
            agent=r["agent"],
            depends_on=tuple(r["depends_on"] or ()),
            input=r["input"] or {},
            output=r["output"],
            status=r["status"],
            attempts=r["attempts"],
        )
        for r in rows
    ]


async def _run_task(
    task: Task,
    inp: dict[str, Any],
    *,
    tenant_id: UUID,
    run_id: UUID,
    autonomy: str,
    actor: str,
) -> None:
    """Claim, gate, dispatch, and commit one task.

    Every exit path writes a terminal status or puts the task back to pending.
    A task left `running` is a run that never finishes, and the events reaper
    cannot help — it releases events, not tasks.
    """
    bound = log.bind(run_id=str(run_id), task=task.task_key, agent=task.agent)

    async with tenant_session(tenant_id) as conn:
        claimed = await conn.fetchval(_CLAIM, task.id)
    if claimed is None:
        bound.debug("task_claimed_elsewhere")
        return

    agent = base.get(task.agent)
    if agent is None:
        # validate_dag rejects this at plan time; reaching it means an agent was
        # removed while a run was in flight.
        await _fail(tenant_id, task, f"no such agent {task.agent!r}", retry=False)
        return

    ctx = base.AgentContext(
        tenant_id=tenant_id,
        run_id=run_id,
        task_id=task.id,
        autonomy=autonomy,
        actor=actor,  # type: ignore[arg-type]
    )

    # `_approved` is written onto the input by the approval handler when a human
    # says yes to *this* task. Without checking it the gate would stop the task
    # again on the very next pass, and approving something would achieve nothing.
    if agent.action is not None and not inp.get("_approved"):
        decision = decide(agent.action, GateContext(mode=autonomy), **inp.get("facts", {}))
        if decision.verdict is Verdict.FORBIDDEN:
            await _fail(tenant_id, task, decision.reason, retry=False)
            bound.warning("task_forbidden", reason=decision.reason)
            return
        if decision.verdict is Verdict.NEEDS_APPROVAL:
            await _pause(tenant_id, task, run_id, str(agent.action), decision.reason, inp)
            bound.info("task_needs_approval", reason=decision.reason)
            return

    try:
        result = await agent.run(agent.input_schema.model_validate(inp), ctx)
    except Exception as exc:  # noqa: BLE001 - one agent must not kill the run
        await _fail(tenant_id, task, f"{type(exc).__name__}: {exc}"[:2000], retry=True)
        bound.warning("task_failed", error=str(exc), attempts=task.attempts + 1)
        return

    await _commit(tenant_id, task, run_id, result)
    bound.info("task_done", status=result.status, cost_usd=round(result.cost_usd, 6))


async def _commit(tenant_id: UUID, task: Task, run_id: UUID, result: base.AgentResult) -> None:
    """Write the result and the agent's events in one transaction.

    This is the transaction the whole design is arranged around: an event that
    escapes without its task result would schedule work for something that did
    not happen.
    """
    status = {"ok": "completed", "needs_approval": "waiting_approval"}.get(result.status, "failed")
    async with tenant_session(tenant_id) as conn, conn.transaction():
        await conn.execute(
            _FINISH, task.id, status, result.output, result.reason, round(result.cost_usd, 4)
        )
        await conn.execute(
            "update agent_runs set cost_usd = cost_usd + $2 where id = $1",
            run_id,
            round(result.cost_usd, 4),
        )
        if result.status == "needs_approval":
            await approvals.request_approval(
                conn,
                tenant_id=tenant_id,
                kind=task.agent,
                summary=result.reason or f"{task.agent} needs approval",
                payload=result.output,
                run_id=run_id,
                task_id=task.id,
            )
        for spec in result.events:
            await emit(
                conn,
                spec.event_type,
                spec.payload,
                tenant_id=tenant_id,
                dedupe_key=spec.dedupe_key,
                priority=spec.priority,
            )


async def _fail(tenant_id: UUID, task: Task, reason: str, *, retry: bool) -> None:
    async with tenant_session(tenant_id) as conn:
        if retry and task.attempts + 1 < MAX_ATTEMPTS:
            await conn.execute(_RETRY, task.id)
        else:
            await conn.execute(_FINISH, task.id, "failed", None, reason[:2000], 0)


async def _pause(
    tenant_id: UUID, task: Task, run_id: UUID, kind: str, reason: str, payload: dict[str, Any]
) -> None:
    async with tenant_session(tenant_id) as conn, conn.transaction():
        await conn.execute(_FINISH, task.id, "waiting_approval", None, reason[:2000], 0)
        await approvals.request_approval(
            conn,
            tenant_id=tenant_id,
            kind=kind,
            summary=reason,
            payload=payload,
            run_id=run_id,
            task_id=task.id,
        )


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


async def execute_run(tenant_id: UUID, run_id: UUID) -> str:
    """Drive a run until nothing more can happen without a human.

    Returns the run's status. Safe to call again on the same run at any time:
    everything it decides comes from the task rows, so a second call after a
    crash resumes rather than repeats.
    """
    async with tenant_session(tenant_id) as conn:
        run = await conn.fetchrow(
            "select autonomy, trigger_type, status from agent_runs where id = $1", run_id
        )
    if run is None:
        raise ValueError(f"no such run {run_id}")

    while True:
        tasks = await _load(tenant_id, run_id)
        batch = ready(tasks)
        if not batch:
            break
        outputs = {t.task_key: t.output for t in tasks if t.status == "completed" and t.output}
        # Parallel by default: t2 and t3 both depending only on t1 is the whole
        # reason the plan is a DAG and not a list.
        await asyncio.gather(
            *(
                _run_task(
                    t,
                    resolve_input(t.input, outputs),
                    tenant_id=tenant_id,
                    run_id=run_id,
                    autonomy=run["autonomy"],
                    actor=run["trigger_type"],
                )
                for t in batch
            )
        )

    tasks = await _load(tenant_id, run_id)
    dead_ends = blocked(tasks)
    if dead_ends:
        async with tenant_session(tenant_id) as conn:
            for task in dead_ends:
                await conn.execute(_SKIP, task.id, "a task it depends on did not complete")
        tasks = await _load(tenant_id, run_id)

    status = run_status(tasks)
    await _report(tenant_id, run_id, status, tasks)
    return status


_SUMMARY = """
update agent_runs
   set status = $2,
       summary = $3,
       finished_at = case when $2 in ('completed','partial','failed') then now() else null end
 where id = $1
"""


async def _report(tenant_id: UUID, run_id: UUID, status: str, tasks: list[Task]) -> None:
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))

    async with tenant_session(tenant_id) as conn, conn.transaction():
        await conn.execute(_SUMMARY, run_id, status, summary)
        if status in ("completed", "partial", "failed"):
            await emit(
                conn,
                "agent_run.finished",
                {"run_id": str(run_id), "status": status, "tasks": counts},
                tenant_id=tenant_id,
                dedupe_key=f"run.finished:{run_id}",
            )
    log.info("run_finished", run_id=str(run_id), status=status, tasks=counts)
