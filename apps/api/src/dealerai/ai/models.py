"""Model routing and cost arithmetic.

Pure data and pure functions — no client, no I/O — so the cost maths is unit
testable without touching the network.

Routing table mirrors docs/01-system-architecture.md § 5. The orchestrator picks
the cheapest model that can do the job; most calls land on Sonnet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class TaskKind(StrEnum):
    # reasoning tier — multi-step planning, or a decision with money attached
    ORCHESTRATE = "orchestrate"
    STRATEGY = "strategy"
    ADS_DECISION = "ads_decision"
    LEARNING = "learning"

    # workhorse tier
    COPYWRITE = "copywrite"
    SALES_REPLY = "sales_reply"
    ANALYSIS = "analysis"
    CREATIVE_DIRECTION = "creative_direction"
    VISION = "vision"
    ENRICHMENT = "enrichment"

    # cheap tier — high volume, trivial decisions
    CLASSIFY_INTENT = "classify_intent"
    SPAM_FILTER = "spam_filter"
    ROUTE = "route"
    TAG = "tag"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model: str
    effort: Effort
    max_tokens: int
    input_usd_per_mtok: float
    output_usd_per_mtok: float


# Model IDs are exact strings and are never date-suffixed.
OPUS = ModelSpec("claude-opus-5", "high", 16_000, 5.0, 25.0)
OPUS_XHIGH = ModelSpec("claude-opus-5", "xhigh", 32_000, 5.0, 25.0)
SONNET = ModelSpec("claude-sonnet-5", "high", 8_000, 2.0, 10.0)
HAIKU = ModelSpec("claude-haiku-4-5", "low", 2_000, 1.0, 5.0)

ROUTING: dict[TaskKind, ModelSpec] = {
    TaskKind.ORCHESTRATE: OPUS_XHIGH,
    TaskKind.STRATEGY: OPUS,
    TaskKind.ADS_DECISION: OPUS,
    TaskKind.LEARNING: OPUS,
    TaskKind.COPYWRITE: SONNET,
    TaskKind.SALES_REPLY: SONNET,
    TaskKind.ANALYSIS: SONNET,
    TaskKind.CREATIVE_DIRECTION: SONNET,
    TaskKind.VISION: SONNET,
    TaskKind.ENRICHMENT: SONNET,
    TaskKind.CLASSIFY_INTENT: HAIKU,
    TaskKind.SPAM_FILTER: HAIKU,
    TaskKind.ROUTE: HAIKU,
    TaskKind.TAG: HAIKU,
}

# Standard prompt-caching multipliers against the base input rate, 5-minute TTL.
# If Anthropic's pricing changes these are the two numbers to update; the cost
# column in agent_traces is only as honest as they are.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

_PER_TOKEN = 1_000_000


def spec_for(task: TaskKind) -> ModelSpec:
    try:
        return ROUTING[task]
    except KeyError:  # pragma: no cover - StrEnum makes this unreachable
        raise ValueError(f"no model routed for task {task!r}") from None


def cost_usd(
    spec: ModelSpec,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Cost of one call.

    `input_tokens` from the API already excludes cached tokens, so the three
    input terms are added, not substituted.
    """
    rate_in = spec.input_usd_per_mtok / _PER_TOKEN
    return (
        input_tokens * rate_in
        + cache_read_tokens * rate_in * CACHE_READ_MULTIPLIER
        + cache_write_tokens * rate_in * CACHE_WRITE_MULTIPLIER
        + output_tokens * spec.output_usd_per_mtok / _PER_TOKEN
    )
