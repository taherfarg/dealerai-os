"""The Content Strategist: decides what to make, and hands the work out.

The first agent in W3 and the only one that sees the whole picture — what is in
stock, what was posted recently, what the dealer's brand allows. Everything
after it works on one brief and knows nothing about the others.

It spawns the rest of the run. The number of briefs a vehicle deserves is not
knowable when the run is planned, so the DAG grows once the strategist has
looked at the car. See `AgentResult.spawns`.
"""

from __future__ import annotations

from typing import ClassVar, Literal

import structlog
from pydantic import BaseModel, Field

from ...ai.gateway import SystemLayers
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...core.security import AuthedUser
from ...deps import TenantContext
from ...orchestrator.gate import Action
from ...orchestrator.toolloop import converse
from .. import base

log = structlog.get_logger()

Concept = Literal[
    "hero", "offer", "specs", "comparison", "feature", "educational", "story", "carousel"
]

#: What the compositor can render for each concept. The strategist chooses a
#: concept, not a template — picking the template is the Creative Director's
#: job, and a strategist that named one would be making a design decision from
#: a spreadsheet.
TEMPLATES: dict[str, tuple[str, ...]] = {
    "hero": ("hero",),
    "offer": ("offer",),
    "specs": ("specs_card",),
    "comparison": ("comparison",),
    "feature": ("feature",),
    "educational": ("educational",),
    "story": ("story_teaser",),
    "carousel": ("carousel_spec",),
}

#: One vehicle yields eight to twelve pieces (docs/05 § 4). More than this is
#: the model padding rather than the car deserving it.
MAX_BRIEFS = 12

TOOLS = [
    "search_inventory",
    "get_vehicle",
    "get_vehicle_media",
    "days_in_stock",
    "stock_report",
    "list_recent_content",
    "get_brand_profile",
]


class Brief(BaseModel):
    concept: Concept
    vehicle_id: str = Field(description="The vehicle this piece is about.")
    angle: str = Field(max_length=200, description="What this piece says, in one line.")
    kind: Literal["post", "story", "reel", "carousel"] = "post"


class Plan(BaseModel):
    reasoning: str = Field(max_length=600, description="Why this set, in a sentence or two.")
    briefs: list[Brief]


class Input(BaseModel):
    vehicle_ids: list[str] = Field(default_factory=list)
    objective: str = Field(default="sell this stock", max_length=400)
    count: int = Field(default=8, ge=1, le=MAX_BRIEFS)
    locales: list[str] = Field(default_factory=lambda: ["en", "ar"])


class Output(BaseModel):
    reasoning: str
    briefs: list[Brief]


class ContentStrategist:
    """Reads the real inventory, then decides the mix."""

    name: ClassVar[str] = "content_strategist"
    input_schema: ClassVar[type[BaseModel]] = Input
    output_schema: ClassVar[type[BaseModel]] = Output
    task_kind: ClassVar[TaskKind | None] = TaskKind.STRATEGY
    #: Nothing leaves the building. Planning what to draft is not a decision a
    #: dealer would want to approve — publishing it is, and that gate is on the
    #: publisher.
    action: ClassVar[Action | None] = None

    async def run(self, inp: Input, ctx: base.AgentContext) -> base.AgentResult:
        tenant = TenantContext(
            tenant_id=ctx.tenant_id,
            user=AuthedUser(id=ctx.task_id, email=None, claims={}),
            role="marketer",
        )
        answer = await converse(
            TaskKind.STRATEGY,
            ctx=tenant,
            system=SystemLayers(role=load("_rules") + "\n\n" + load("strategist")),
            prompt=(
                f"## Objective\n<untrusted>\n{inp.objective}\n</untrusted>\n\n"
                f"## Vehicles in scope\n{', '.join(inp.vehicle_ids) or 'choose from stock'}\n\n"
                f"## How many pieces\n{inp.count}\n\n"
                f"## Languages\n{', '.join(inp.locales)}\n\n"
                "Look up the vehicles and what has been posted recently, then plan."
            ),
            tools=TOOLS,
            output_schema=Plan,
            run_id=ctx.run_id,
            task_id=ctx.task_id,
            trace_name="strategist",
        )
        if not isinstance(answer.parsed, Plan) or not answer.parsed.briefs:
            return base.AgentResult(
                status="escalated",
                reason="the strategist produced no usable briefs",
                cost_usd=answer.cost_usd,
            )

        briefs = answer.parsed.briefs[: inp.count]
        spawns = tuple(_fan_out(briefs, locales=inp.locales))
        log.info(
            "content_planned",
            run_id=str(ctx.run_id),
            briefs=len(briefs),
            tasks=len(spawns),
            tools=answer.tool_calls,
        )
        return base.AgentResult(
            status="ok",
            output={
                "reasoning": answer.parsed.reasoning,
                "briefs": [b.model_dump() for b in briefs],
            },
            spawns=spawns,
            cost_usd=answer.cost_usd,
        )


def _fan_out(briefs: list[Brief], *, locales: list[str]) -> list[base.Spawn]:
    """Three kinds of task per brief: direct, write, render.

    Copy depends on direction because a carousel card and a story teaser want
    different words, and the template is what says which one this is. The
    render depends on every locale's copy, so a piece is never half-written
    when it is composited.
    """
    out: list[base.Spawn] = []
    for i, brief in enumerate(briefs, start=1):
        direct = f"b{i}_direct"
        payload = brief.model_dump()
        out.append(base.Spawn(task_key=direct, agent="creative_director", input=payload))

        copy_keys = []
        for locale in locales:
            key = f"b{i}_copy_{locale}"
            copy_keys.append(key)
            out.append(
                base.Spawn(
                    task_key=key,
                    agent="copywriter",
                    depends_on=(direct,),
                    input={**payload, "locale": locale, "from_task": direct},
                )
            )
        out.append(
            base.Spawn(
                task_key=f"b{i}_render",
                agent="image_agent",
                depends_on=(direct, *copy_keys),
                input={**payload, "from_tasks": [direct, *copy_keys]},
            )
        )
    return out


base.register(ContentStrategist())
