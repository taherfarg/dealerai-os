"""The agent runtime.

The DAG functions are pure and tested directly — they decide what runs, in what
order, and what a failure does to everything downstream, and none of that needs
a database to be wrong.

The second half runs real DAGs against Postgres with stub agents. No model is
involved anywhere in this file: the executor's job is scheduling and
bookkeeping, and a model call would only make the tests slow and flaky without
testing anything the executor does.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from pydantic import BaseModel

from conftest import TENANT_A, TENANT_B, reseed
from dealerai.agents import base
from dealerai.ai.models import TaskKind
from dealerai.config import get_settings
from dealerai.orchestrator import planner
from dealerai.orchestrator.executor import (
    PlanInvalid,
    PlannedTask,
    Task,
    blocked,
    execute_run,
    ready,
    resolve_input,
    run_status,
    validate_dag,
)
from dealerai.orchestrator.gate import Action

# --------------------------------------------------------------------------
# validating a plan a model wrote
# --------------------------------------------------------------------------

AGENTS = frozenset({"a", "b", "c"})


def planned(key: str, *deps: str, agent: str = "a") -> PlannedTask:
    return PlannedTask(task_key=key, agent=agent, depends_on=deps)


def test_a_straight_line_plan_is_valid() -> None:
    validate_dag([planned("t1"), planned("t2", "t1")], known_agents=AGENTS)


def test_an_empty_plan_is_refused() -> None:
    with pytest.raises(PlanInvalid, match="no tasks"):
        validate_dag([], known_agents=AGENTS)


def test_a_plan_naming_an_agent_that_does_not_exist_is_refused() -> None:
    """Cheaper to reject here than to debug as a run that hangs at 40%."""
    with pytest.raises(PlanInvalid, match="no such agent: ghost"):
        validate_dag([planned("t1", agent="ghost")], known_agents=AGENTS)


def test_a_plan_depending_on_a_task_it_forgot_to_include_is_refused() -> None:
    with pytest.raises(PlanInvalid, match="depends on missing t9"):
        validate_dag([planned("t1", "t9")], known_agents=AGENTS)


def test_duplicate_task_keys_are_refused() -> None:
    """`from_task: t1` has to mean one task."""
    with pytest.raises(PlanInvalid, match="duplicate task keys: t1"):
        validate_dag([planned("t1"), planned("t1")], known_agents=AGENTS)


def test_a_cycle_is_refused() -> None:
    with pytest.raises(PlanInvalid, match="cycle"):
        validate_dag([planned("t1", "t2"), planned("t2", "t1")], known_agents=AGENTS)


def test_a_self_dependency_is_refused() -> None:
    with pytest.raises(PlanInvalid, match="depends on itself"):
        validate_dag([planned("t1", "t1")], known_agents=AGENTS)


def test_a_diamond_is_valid() -> None:
    validate_dag(
        [planned("t1"), planned("t2", "t1"), planned("t3", "t1"), planned("t4", "t2", "t3")],
        known_agents=AGENTS,
    )


# --------------------------------------------------------------------------
# what is ready, and what can never be
# --------------------------------------------------------------------------


def task(key: str, status: str = "pending", *deps: str, output: Any = None) -> Task:
    return Task(
        id=uuid.uuid4(),
        task_key=key,
        agent="a",
        depends_on=deps,
        input={},
        output=output,
        status=status,
        attempts=0,
    )


def test_a_task_with_no_dependencies_is_ready() -> None:
    assert [t.task_key for t in ready([task("t1")])] == ["t1"]


def test_both_sides_of_a_diamond_are_ready_at_once() -> None:
    """The whole reason a plan is a DAG and not a list."""
    tasks = [
        task("t1", "completed"),
        task("t2", "pending", "t1"),
        task("t3", "pending", "t1"),
        task("t4", "pending", "t2", "t3"),
    ]
    assert sorted(t.task_key for t in ready(tasks)) == ["t2", "t3"]


def test_a_task_waits_for_every_dependency_not_just_one() -> None:
    tasks = [task("t1", "completed"), task("t2", "running"), task("t3", "pending", "t1", "t2")]
    assert ready(tasks) == []


@pytest.mark.parametrize("dep_status", ["failed", "skipped", "waiting_approval", "running"])
def test_only_a_completed_dependency_releases_a_task(dep_status: str) -> None:
    tasks = [task("t1", dep_status), task("t2", "pending", "t1")]
    assert ready(tasks) == []


def test_a_task_below_a_failure_can_never_run() -> None:
    """Without this the run hangs forever holding its event: `ready` correctly
    returns nothing and the loop correctly waits."""
    tasks = [task("t1", "failed"), task("t2", "pending", "t1")]
    assert [t.task_key for t in blocked(tasks)] == ["t2"]


def test_being_blocked_travels_all_the_way_down() -> None:
    tasks = [
        task("t1", "failed"),
        task("t2", "pending", "t1"),
        task("t3", "pending", "t2"),
        task("t4", "pending"),
    ]
    assert sorted(t.task_key for t in blocked(tasks)) == ["t2", "t3"]


def test_nothing_is_blocked_when_nothing_failed() -> None:
    assert blocked([task("t1", "completed"), task("t2", "pending", "t1")]) == []


def test_a_task_waiting_for_approval_does_not_block_what_is_below_it() -> None:
    """A human may still say yes. Skipping the branch now would throw away work
    the dealer is about to approve."""
    tasks = [task("t1", "waiting_approval"), task("t2", "pending", "t1")]
    assert blocked(tasks) == []


# --------------------------------------------------------------------------
# passing one task's output to the next
# --------------------------------------------------------------------------


def test_from_task_is_replaced_by_that_tasks_output() -> None:
    resolved = resolve_input({"from_task": "t1", "locale": "ar"}, {"t1": {"brief": "hero shot"}})
    assert resolved == {"locale": "ar", "brief": "hero shot"}


def test_from_tasks_keeps_each_output_under_its_own_key() -> None:
    resolved = resolve_input({"from_tasks": ["t2", "t3"]}, {"t2": {"a": 1}, "t3": {"b": 2}})
    assert resolved == {"from_tasks": {"t2": {"a": 1}, "t3": {"b": 2}}}


def test_a_reference_to_a_task_with_no_output_resolves_to_nothing() -> None:
    """Not a KeyError. The agent's own schema decides whether the missing field
    matters, and it reports that better than a crash in the executor does."""
    assert resolve_input({"from_task": "t9", "x": 1}, {}) == {"x": 1}


def test_ordinary_input_passes_through_untouched() -> None:
    assert resolve_input({"vehicle_ids": ["a"]}, {}) == {"vehicle_ids": ["a"]}


# --------------------------------------------------------------------------
# what the run row should say
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["completed", "completed"], "completed"),
        (["completed", "failed"], "partial"),
        (["failed", "skipped"], "failed"),
        (["completed", "pending"], "running"),
        (["completed", "waiting_approval"], "waiting_approval"),
        (["failed", "waiting_approval"], "waiting_approval"),
    ],
)
def test_run_status_reflects_its_tasks(statuses: list[str], expected: str) -> None:
    assert run_status([task(f"t{i}", s) for i, s in enumerate(statuses)]) == expected


# --------------------------------------------------------------------------
# stub agents
# --------------------------------------------------------------------------


class Anything(BaseModel):
    model_config = {"extra": "allow"}


class Stub:
    """Records what it was given, returns what it was told to."""

    input_schema = Anything
    output_schema = Anything
    task_kind = TaskKind.ANALYSIS

    def __init__(
        self,
        name: str,
        *,
        result: str = "ok",
        action: Action | None = None,
        raises: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.name = name
        self.action = action
        self.result = result
        self.raises = raises
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.started: list[float] = []

    async def run(self, inp: Anything, ctx: base.AgentContext) -> base.AgentResult:
        self.started.append(asyncio.get_running_loop().time())
        self.calls.append(inp.model_dump())
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise RuntimeError("the agent blew up")
        return base.AgentResult(
            status=self.result,  # type: ignore[arg-type]
            output={"from": self.name, "n": len(self.calls)},
            reason=None if self.result == "ok" else f"{self.name} says no",
        )


@pytest.fixture
def registry() -> Iterator[dict[str, Stub]]:
    """A clean registry per test. The real one is a module-level dict, so a
    leaked agent would make the next test pass for the wrong reason."""
    saved = dict(base._REGISTRY)
    base._REGISTRY.clear()
    stubs: dict[str, Stub] = {}
    yield stubs
    base._REGISTRY.clear()
    base._REGISTRY.update(saved)


def add(registry: dict[str, Stub], name: str, **kwargs: Any) -> Stub:
    stub = Stub(name, **kwargs)
    registry[name] = stub
    base.register(stub)  # type: ignore[arg-type]
    return stub


@pytest.fixture
def clean(_migrated: None) -> None:
    asyncio.run(reseed())
    asyncio.run(_wipe_runs())


async def _wipe_runs() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("delete from agent_runs")
        await conn.execute("delete from events")
    finally:
        await conn.close()


async def _tasks(run_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        rows = await conn.fetch(
            "select task_key, status, output, attempts, error from agent_tasks where run_id = $1",
            run_id,
        )
        return {r["task_key"]: dict(r) for r in rows}
    finally:
        await conn.close()


DIAMOND = [
    PlannedTask(task_key="t1", agent="t1"),
    PlannedTask(task_key="t2", agent="t2", depends_on=("t1",), input={"from_task": "t1"}),
    PlannedTask(task_key="t3", agent="t3", depends_on=("t1",), input={"from_task": "t1"}),
    PlannedTask(
        task_key="t4", agent="t4", depends_on=("t2", "t3"), input={"from_tasks": ["t2", "t3"]}
    ),
]


# --------------------------------------------------------------------------
# the acceptance test
# --------------------------------------------------------------------------


async def test_a_diamond_runs_its_middle_in_parallel_and_its_tip_once(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """T3.2's acceptance. t2 and t3 overlap in time; t4 runs exactly once."""
    for name in ("t1", "t4"):
        add(registry, name)
    for name in ("t2", "t3"):
        add(registry, name, delay=0.1)

    run_id = await planner.create_run(
        tenant_id=TENANT_A, goal="diamond", tasks=DIAMOND, autonomy="autopilot"
    )
    assert await execute_run(TENANT_A, run_id) == "completed"

    tasks = await _tasks(run_id)
    assert {k: v["status"] for k, v in tasks.items()} == dict.fromkeys(
        ("t1", "t2", "t3", "t4"), "completed"
    )
    assert len(registry["t4"].calls) == 1, "the tip of the diamond ran more than once"

    # Overlap, not just "both ran": each sleeps 0.1s, so sequential execution
    # would put their start times 0.1s apart.
    apart = abs(registry["t2"].started[0] - registry["t3"].started[0])
    assert apart < 0.05, f"t2 and t3 started {apart:.3f}s apart — they ran in series"


async def test_the_tip_receives_both_branches_outputs(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """`from_tasks` is resolved from what the branches actually produced, never
    by asking a model again."""
    for name in ("t1", "t2", "t3", "t4"):
        add(registry, name)

    run_id = await planner.create_run(
        tenant_id=TENANT_A, goal="diamond", tasks=DIAMOND, autonomy="autopilot"
    )
    await execute_run(TENANT_A, run_id)

    received = registry["t4"].calls[0]["from_tasks"]
    assert received["t2"]["from"] == "t2"
    assert received["t3"]["from"] == "t3"
    assert registry["t2"].calls[0]["from"] == "t1", "from_task merges the output in"


# --------------------------------------------------------------------------
# resumability
# --------------------------------------------------------------------------


async def test_a_second_run_of_the_same_run_repeats_nothing(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """The other half of T3.2's acceptance, and the reason a run holds no state
    in the process: re-entering after a crash resumes rather than repeats."""
    for name in ("t1", "t2", "t3", "t4"):
        add(registry, name)

    run_id = await planner.create_run(
        tenant_id=TENANT_A, goal="diamond", tasks=DIAMOND, autonomy="autopilot"
    )
    await execute_run(TENANT_A, run_id)
    calls_before = {k: len(v.calls) for k, v in registry.items()}

    assert await execute_run(TENANT_A, run_id) == "completed"
    assert {k: len(v.calls) for k, v in registry.items()} == calls_before


async def test_a_run_interrupted_mid_flight_finishes_the_rest(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """Simulates the crash directly: t1 is already completed in the database and
    the executor is entered fresh, exactly as a second worker would find it."""
    for name in ("t1", "t2", "t3", "t4"):
        add(registry, name)

    run_id = await planner.create_run(
        tenant_id=TENANT_A, goal="diamond", tasks=DIAMOND, autonomy="autopilot"
    )
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """update agent_tasks set status = 'completed', output = '{"from": "t1"}'::jsonb
                where run_id = $1 and task_key = 't1'""",
            run_id,
        )
    finally:
        await conn.close()

    assert await execute_run(TENANT_A, run_id) == "completed"
    assert registry["t1"].calls == [], "a completed task was run again"
    assert len(registry["t4"].calls) == 1


# --------------------------------------------------------------------------
# failure
# --------------------------------------------------------------------------


async def test_a_failing_task_is_retried_once_then_gives_up(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    add(registry, "t1", raises=True)
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="fail",
        tasks=[PlannedTask(task_key="t1", agent="t1")],
        autonomy="autopilot",
    )
    assert await execute_run(TENANT_A, run_id) == "failed"

    tasks = await _tasks(run_id)
    assert tasks["t1"]["status"] == "failed"
    assert tasks["t1"]["attempts"] == 2, "one retry, not an infinite loop"
    assert "blew up" in tasks["t1"]["error"]


async def test_one_failure_does_not_take_the_independent_branch_with_it(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """A partial run is a real outcome. The dealer gets the half that worked."""
    add(registry, "t1", raises=True)
    add(registry, "t2")
    add(registry, "t3")

    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="partial",
        tasks=[
            PlannedTask(task_key="t1", agent="t1"),
            PlannedTask(task_key="t2", agent="t2", depends_on=("t1",)),
            PlannedTask(task_key="t3", agent="t3"),
        ],
        autonomy="autopilot",
    )
    assert await execute_run(TENANT_A, run_id) == "partial"

    tasks = await _tasks(run_id)
    assert tasks["t1"]["status"] == "failed"
    assert tasks["t2"]["status"] == "skipped", "the branch below a failure is closed, not hung"
    assert tasks["t3"]["status"] == "completed"


async def test_a_run_reports_itself_finished(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    add(registry, "t1")
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="one",
        tasks=[PlannedTask(task_key="t1", agent="t1")],
        autonomy="autopilot",
    )
    await execute_run(TENANT_A, run_id)

    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        run = await conn.fetchrow(
            "select status, summary, finished_at from agent_runs where id=$1", run_id
        )
        finished = await conn.fetchval(
            "select count(*) from events where event_type = 'agent_run.finished'"
        )
    finally:
        await conn.close()
    assert run is not None
    assert run["status"] == "completed"
    assert run["finished_at"] is not None
    assert run["summary"] == "1 completed"
    assert finished == 1


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


async def test_a_gated_action_pauses_the_run_instead_of_doing_it(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """Copilot mode approves nothing automatically. The task must stop before
    the agent runs, not after — an approval for something already published is
    a receipt, not a decision."""
    stub = add(registry, "t1", action=Action.PUBLISH_NEW_CONTENT)
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="publish",
        tasks=[PlannedTask(task_key="t1", agent="t1")],
        autonomy="copilot",
    )
    assert await execute_run(TENANT_A, run_id) == "waiting_approval"

    assert stub.calls == [], "the agent ran despite needing approval"
    tasks = await _tasks(run_id)
    assert tasks["t1"]["status"] == "waiting_approval"

    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        pending = await conn.fetchval(
            "select count(*) from approvals where run_id = $1 and status = 'pending'", run_id
        )
    finally:
        await conn.close()
    assert pending == 1, "the run paused without asking anyone"


async def test_an_action_no_mode_allows_fails_rather_than_waits(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """ALWAYS_HUMAN actions are forbidden in every mode. Queuing an approval for
    one would imply a dealer could click it through."""
    add(registry, "t1", action=Action.SIGN_CONTRACT)
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="sign",
        tasks=[PlannedTask(task_key="t1", agent="t1")],
        autonomy="autopilot",
    )
    assert await execute_run(TENANT_A, run_id) == "failed"
    assert (await _tasks(run_id))["t1"]["status"] == "failed"


async def test_an_agent_may_ask_for_approval_of_what_it_produced(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    add(registry, "t1", result="needs_approval")
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="draft",
        tasks=[PlannedTask(task_key="t1", agent="t1")],
        autonomy="autopilot",
    )
    assert await execute_run(TENANT_A, run_id) == "waiting_approval"

    tasks = await _tasks(run_id)
    assert tasks["t1"]["status"] == "waiting_approval"
    assert tasks["t1"]["output"] is not None, "its work is kept while a human looks at it"


# --------------------------------------------------------------------------
# isolation
# --------------------------------------------------------------------------


async def test_a_run_belonging_to_another_tenant_is_not_executable(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """RLS makes this true; the test makes it stay true."""
    add(registry, "t1")
    run_id = await planner.create_run(
        tenant_id=TENANT_B,
        goal="theirs",
        tasks=[PlannedTask(task_key="t1", agent="t1")],
        autonomy="autopilot",
    )
    with pytest.raises(ValueError, match="no such run"):
        await execute_run(TENANT_A, run_id)
    assert registry["t1"].calls == []


async def test_an_invalid_dag_is_refused_before_a_row_exists(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    add(registry, "t1")
    with pytest.raises(PlanInvalid):
        await planner.create_run(
            tenant_id=TENANT_A,
            goal="cycle",
            tasks=[
                PlannedTask(task_key="t1", agent="t1", depends_on=("t2",)),
                PlannedTask(task_key="t2", agent="t1", depends_on=("t1",)),
            ],
            autonomy="autopilot",
        )
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        runs = await conn.fetchval("select count(*) from agent_runs where tenant_id = $1", TENANT_A)
    finally:
        await conn.close()
    assert runs == 0


def test_the_registry_rejects_a_duplicate_name(registry: dict[str, Stub]) -> None:
    add(registry, "t1")
    with pytest.raises(ValueError, match="already registered"):
        add(registry, "t1")


def test_a_non_ok_result_must_say_why() -> None:
    with pytest.raises(ValueError, match="must say why"):
        base.AgentResult(status="failed")


# --------------------------------------------------------------------------
# resuming after a human decides
# --------------------------------------------------------------------------


async def _decide(run_id: uuid.UUID, outcome: str) -> None:
    """Approve or reject whatever the run is waiting on, as the route does."""
    from dealerai.events.bus import Event
    from dealerai.events.handlers.runs import on_approval_decided

    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        row = await conn.fetchrow(
            "select id, task_id from approvals where run_id = $1 and status = 'pending'", run_id
        )
        assert row is not None
        await conn.execute("update approvals set status = $2 where id = $1", row["id"], outcome)
    finally:
        await conn.close()

    await on_approval_decided(
        Event(
            id=0,
            tenant_id=TENANT_A,
            event_type="approval.decided",
            payload={"task_id": str(row["task_id"]), "decision": outcome, "note": "no thanks"},
            attempts=1,
            dedupe_key=None,
        )
    )


async def test_approving_a_gated_task_lets_it_run(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """The human said yes to this task, so the gate must not stop it a second
    time — otherwise approving something achieves nothing and the dealer clicks
    forever."""
    stub = add(registry, "t1", action=Action.PUBLISH_NEW_CONTENT)
    add(registry, "t2")
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="publish",
        tasks=[
            PlannedTask(task_key="t1", agent="t1"),
            PlannedTask(task_key="t2", agent="t2", depends_on=("t1",)),
        ],
        autonomy="copilot",
    )
    assert await execute_run(TENANT_A, run_id) == "waiting_approval"
    assert stub.calls == []

    await _decide(run_id, "approved")
    assert await execute_run(TENANT_A, run_id) == "completed"

    assert len(stub.calls) == 1, "approval did not release the task"
    assert (await _tasks(run_id))["t2"]["status"] == "completed", "the branch below resumed"


async def test_approving_a_finished_draft_completes_it_without_rerunning(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    """The agent already did the work and asked about the result. Running it
    again would pay for a second draft nobody asked for."""
    stub = add(registry, "t1", result="needs_approval")
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="draft",
        tasks=[PlannedTask(task_key="t1", agent="t1")],
        autonomy="autopilot",
    )
    await execute_run(TENANT_A, run_id)

    await _decide(run_id, "approved")
    assert await execute_run(TENANT_A, run_id) == "completed"
    assert len(stub.calls) == 1, "the agent ran again after its output was approved"


async def test_rejecting_closes_the_branch(
    db: None, clean: None, registry: dict[str, Stub]
) -> None:
    add(registry, "t1", action=Action.PUBLISH_NEW_CONTENT)
    add(registry, "t2")
    run_id = await planner.create_run(
        tenant_id=TENANT_A,
        goal="publish",
        tasks=[
            PlannedTask(task_key="t1", agent="t1"),
            PlannedTask(task_key="t2", agent="t2", depends_on=("t1",)),
        ],
        autonomy="copilot",
    )
    await execute_run(TENANT_A, run_id)

    await _decide(run_id, "rejected")
    assert await execute_run(TENANT_A, run_id) == "failed"

    tasks = await _tasks(run_id)
    assert tasks["t1"]["status"] == "failed"
    assert tasks["t2"]["status"] == "skipped", "a rejected task does not leave its branch hanging"
    assert registry["t2"].calls == []


def test_every_handler_module_is_actually_imported() -> None:
    """The bug this catches shipped once: handlers register with a decorator at
    import time, so a module nobody imports is a handler nobody has — and an
    unregistered type looks exactly like a mid-deploy race, so the worker
    dead-lettered every event in silence."""
    import dealerai.events.handlers  # noqa: F401
    from dealerai.events.bus import registered_types

    assert {"vehicle.created", "vehicle.media_uploaded", "agent_run.started"} <= registered_types()
