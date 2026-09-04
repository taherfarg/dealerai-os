"""The agent contract, and the registry that resolves a name to one.

Every agent implements the same four things and no base class. The executor
knows nothing about any particular agent — it reads `agent` out of a row, looks
it up here, and calls `run`.

Two rules carry the weight:

  * **Events are returned, not emitted.** The executor writes them in the same
    transaction as the task's result, so a task that fails after emitting
    cannot leave an event behind for work that was rolled back.
  * **A result is data.** An agent never writes its own task row, never decides
    the run's status, and never commits. It says what happened and the executor
    records it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from ..ai.models import TaskKind
from ..orchestrator.gate import Action, AutonomyMode

Status = Literal["ok", "needs_approval", "escalated", "failed"]

#: What triggered the run. Not a user id — a scheduled run has no user, and
#: docs/02 § 2 writing `TenantContext` here assumed one always exists.
Actor = Literal["user", "system", "schedule", "webhook"]


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Something the agent created that a human will look at."""

    kind: str
    id: UUID


@dataclass(frozen=True, slots=True)
class EventSpec:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None
    priority: int = 0


@dataclass(frozen=True, slots=True)
class AgentContext:
    tenant_id: UUID
    run_id: UUID
    task_id: UUID
    autonomy: AutonomyMode
    actor: Actor
    locale: str = "en-AE"


@dataclass(frozen=True, slots=True)
class AgentResult:
    """`needs_approval` and `escalated` are successes, not errors.

    An agent that correctly recognises it must not act alone has done its job.
    Treating that as a failure would train the next one to guess instead.
    """

    status: Status
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    events: tuple[EventSpec, ...] = ()
    reason: str | None = None
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.status != "ok" and not self.reason:
            raise ValueError(f"a {self.status!r} result must say why")


class Agent(Protocol):
    """Structural, not inherited. An agent is anything with these attributes."""

    name: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    task_kind: TaskKind
    #: What the autonomy gate checks before this agent runs. None means the
    #: agent does nothing a dealer would want to approve — drafting, reading,
    #: summarising. Anything that leaves the building has an Action.
    action: Action | None

    async def run(self, inp: BaseModel, ctx: AgentContext) -> AgentResult: ...


_REGISTRY: dict[str, Agent] = {}


def register(agent: Agent) -> Agent:
    if agent.name in _REGISTRY:
        raise ValueError(f"agent {agent.name!r} is already registered")
    _REGISTRY[agent.name] = agent
    return agent


def get(name: str) -> Agent | None:
    return _REGISTRY.get(name)


def names() -> frozenset[str]:
    return frozenset(_REGISTRY)
