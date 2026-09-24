"""A model scoring drafts against what a salesperson actually sent.

A model's opinion is a fine way to measure tone and a poor way to measure
whether a number is right — so the price and availability gate does not come
from here. It comes from running the real guards against the fixed inventory
(test_copilot_live.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from dealerai.ai.gateway import SystemLayers, complete
from dealerai.ai.models import TaskKind
from dealerai.ai.prompts import load

AXES = ("accuracy", "language", "next_step", "brevity", "banned")


class Scores(BaseModel):
    accuracy: int = Field(ge=1, le=5)
    language: int = Field(ge=1, le=5)
    next_step: int = Field(ge=1, le=5)
    brevity: int = Field(ge=1, le=5)
    banned: int = Field(ge=1, le=5)
    why_accuracy: str = ""
    why_language: str = ""
    why_next_step: str = ""
    why_brevity: str = ""
    why_banned: str = ""

    @property
    def mean(self) -> float:
        return sum(getattr(self, axis) for axis in AXES) / len(AXES)


@dataclass(frozen=True, slots=True)
class Judged:
    scores: Scores | None
    cost_usd: float


async def judge(
    *,
    tenant_id: UUID,
    customer: str,
    facts: str,
    draft: str,
    reference: str,
) -> Judged:
    result = await complete(
        TaskKind.ANALYSIS,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("judge")),
        messages=(
            f"## What the customer wrote\n<untrusted>\n{customer}\n</untrusted>\n\n"
            f"## The facts the copilot was given\n{facts}\n\n"
            f"## The draft you are scoring\n<untrusted>\n{draft}\n</untrusted>\n\n"
            f"## What the salesperson actually sent\n<untrusted>\n{reference}\n</untrusted>"
        ),
        output_schema=Scores,
        trace_name="judge",
    )
    scores = result.parsed if isinstance(result.parsed, Scores) else None
    return Judged(scores=scores, cost_usd=result.cost_usd)


def worst(scores: Scores) -> tuple[str, int]:
    lowest = min(AXES, key=lambda axis: int(getattr(scores, axis)))
    return lowest, int(getattr(scores, lowest))


def why(scores: Scores, axis: str) -> Any:
    return getattr(scores, f"why_{axis}", "")
