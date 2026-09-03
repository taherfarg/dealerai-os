"""Model routing and cost arithmetic.

Pure data and pure functions — no client, no I/O — so the cost maths is unit
testable without touching the network.

Provider: Google Gemini. See docs/01-system-architecture.md § 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

#: Gemini exposes thinking as a token budget rather than an effort label.
#: -1 means "decide for yourself", 0 means off (not accepted by Pro).
DYNAMIC_THINKING = -1


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
    max_tokens: int
    thinking_budget: int
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    cached_input_usd_per_mtok: float


# Only GA models. `gemini-3-pro-preview` was shut down while still being the
# newest Pro, and `gemini-3.1-pro-preview` is preview today — a model that
# disappears mid-quarter is an outage on the path where agents spend a dealer's
# ad budget. Move up when 3.x Pro reaches GA; it is a one-line change here and
# nothing else in the codebase names a model.
#
# Prices are USD per 1M tokens from ai.google.dev/gemini-api/docs/pricing.
# Pro's rates step up above a 200k-token prompt; we bill at the ≤200k rate,
# which is where every request in this product lands. If that changes, this is
# the table to fix.
PRO = ModelSpec("gemini-2.5-pro", 16_000, DYNAMIC_THINKING, 1.25, 10.00, 0.125)
FLASH = ModelSpec("gemini-2.5-flash", 8_000, DYNAMIC_THINKING, 0.30, 2.50, 0.03)
#: Thinking off: classification does not benefit and it is pure latency and cost
#: on the critical path of a customer reply.
FLASH_LITE = ModelSpec("gemini-2.5-flash-lite", 2_000, 0, 0.10, 0.40, 0.01)

ROUTING: dict[TaskKind, ModelSpec] = {
    TaskKind.ORCHESTRATE: PRO,
    TaskKind.STRATEGY: PRO,
    TaskKind.ADS_DECISION: PRO,
    TaskKind.LEARNING: PRO,
    TaskKind.COPYWRITE: FLASH,
    TaskKind.SALES_REPLY: FLASH,
    TaskKind.ANALYSIS: FLASH,
    TaskKind.CREATIVE_DIRECTION: FLASH,
    TaskKind.VISION: FLASH,
    TaskKind.ENRICHMENT: FLASH,
    TaskKind.CLASSIFY_INTENT: FLASH_LITE,
    TaskKind.SPAM_FILTER: FLASH_LITE,
    TaskKind.ROUTE: FLASH_LITE,
    TaskKind.TAG: FLASH_LITE,
}

_PER_TOKEN = 1_000_000

Provider = Literal["google"]
PROVIDER: Provider = "google"


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
    cached_tokens: int = 0,
    thought_tokens: int = 0,
) -> float:
    """Cost of one call.

    Two Gemini-specific details that are easy to get wrong:

    * `prompt_token_count` **includes** `cached_content_token_count`. The cached
      portion is not a separate bucket added on top — it is a discount on part
      of the same total. Adding them (as Anthropic's shape requires) would
      overstate every bill.
    * Thinking tokens are billed at the **output** rate and are reported
      separately from `candidates_token_count`, so they have to be added in or
      reasoning-heavy calls look far cheaper than they are.
    """
    billed_input = max(input_tokens - cached_tokens, 0)
    return (
        billed_input * spec.input_usd_per_mtok / _PER_TOKEN
        + cached_tokens * spec.cached_input_usd_per_mtok / _PER_TOKEN
        + (output_tokens + thought_tokens) * spec.output_usd_per_mtok / _PER_TOKEN
    )
