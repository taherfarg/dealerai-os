"""The autonomy gate: may this agent do this, right now, for this tenant?

Every agent asks before acting. It is checked *before* dispatch, so an agent
never discovers mid-run that it was not allowed to do the thing — see
docs/02-agent-architecture.md § 3, step 4.

Two properties matter more than the table itself:

  * **Exceeding a numeric limit downgrades to NEEDS_APPROVAL, never FORBIDDEN.**
    The dealer can still say yes. Turning "over budget" into a hard refusal
    would train people to widen the limits until they mean nothing.
  * **A missing fact is a violation.** If the caller does not say how many posts
    went out today, the gate does not assume zero. Fail closed: the cost of an
    unnecessary approval prompt is a click; the cost of the other mistake is a
    dealer's ad budget.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum
from typing import Any

AutonomyMode = str  # "copilot" | "assisted" | "autopilot"


class Action(StrEnum):
    # content
    GENERATE_CONTENT = "generate_content"
    PUBLISH_SCHEDULED = "publish_scheduled"
    PUBLISH_NEW_CONTENT = "publish_new_content"
    # conversations
    ANSWER_FAQ = "answer_faq"
    REPLY_COMMENT = "reply_comment"
    REPLY_MESSAGE = "reply_message"
    QUOTE_PRICE = "quote_price"
    OFFER_DISCOUNT = "offer_discount"
    HANDLE_COMPLAINT = "handle_complaint"
    # money
    ADJUST_AD_BUDGET = "adjust_ad_budget"
    LAUNCH_CAMPAIGN = "launch_campaign"
    CHANGE_VEHICLE_PRICE = "change_vehicle_price"
    # never automated, in any mode
    REFUND = "refund"
    SIGN_CONTRACT = "sign_contract"
    TAKE_PAYMENT_DETAILS = "take_payment_details"
    LEGAL_DISPUTE = "legal_dispute"
    DISCOUNT_BELOW_FLOOR = "discount_below_floor"


class Verdict(StrEnum):
    ALLOW = "allow"
    NEEDS_APPROVAL = "needs_approval"
    FORBIDDEN = "forbidden"


ALWAYS_HUMAN = frozenset(
    {
        Action.REFUND,
        Action.SIGN_CONTRACT,
        Action.TAKE_PAYMENT_DETAILS,
        Action.LEGAL_DISPUTE,
        Action.DISCOUNT_BELOW_FLOOR,
    }
)

A, N = Verdict.ALLOW, Verdict.NEEDS_APPROVAL

#: docs/02-agent-architecture.md § 5. Keep the two in step — the test walks
#: every cell, so a change here without a change there fails loudly.
MATRIX: dict[Action, dict[AutonomyMode, Verdict]] = {
    Action.GENERATE_CONTENT: {"copilot": A, "assisted": A, "autopilot": A},
    Action.ANSWER_FAQ: {"copilot": N, "assisted": A, "autopilot": A},
    Action.PUBLISH_SCHEDULED: {"copilot": N, "assisted": A, "autopilot": A},
    Action.REPLY_COMMENT: {"copilot": N, "assisted": A, "autopilot": A},
    Action.QUOTE_PRICE: {"copilot": N, "assisted": A, "autopilot": A},
    Action.REPLY_MESSAGE: {"copilot": N, "assisted": N, "autopilot": A},
    Action.PUBLISH_NEW_CONTENT: {"copilot": N, "assisted": N, "autopilot": A},
    Action.OFFER_DISCOUNT: {"copilot": N, "assisted": N, "autopilot": A},
    Action.ADJUST_AD_BUDGET: {"copilot": N, "assisted": N, "autopilot": A},
    Action.LAUNCH_CAMPAIGN: {"copilot": N, "assisted": N, "autopilot": N},
    Action.CHANGE_VEHICLE_PRICE: {"copilot": N, "assisted": N, "autopilot": N},
    Action.HANDLE_COMPLAINT: {"copilot": N, "assisted": N, "autopilot": N},
}


@dataclass(frozen=True, slots=True)
class GateContext:
    mode: AutonomyMode
    rules: dict[str, Any] = field(default_factory=dict)
    #: Tenant-local wall clock. Only quiet hours consult it.
    local_time: time | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str
    limit: str | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


MISSING = object()


def _rule(rules: dict[str, Any], group: str, key: str, default: Any = MISSING) -> Any:
    value = rules.get(group, {}).get(key, MISSING)
    return default if value is MISSING else value


def in_quiet_hours(now: time, start: time, end: time) -> bool:
    """Quiet hours wrap midnight: 23:00–07:00 means late night, not 20 hours."""
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def _parse_time(raw: str) -> time:
    hour, _, minute = raw.partition(":")
    return time(int(hour), int(minute or 0))


# --------------------------------------------------------------------------
# limit checks — return a violation message, or None when within limits
# --------------------------------------------------------------------------


def _check_publishing(rules: dict[str, Any], facts: dict[str, Any], ctx: GateContext) -> str | None:
    max_per_day = _rule(rules, "publishing", "max_posts_per_day", None)
    if max_per_day is not None:
        posted = facts.get("posts_today", MISSING)
        if posted is MISSING:
            return "posts_today was not supplied, so the daily posting limit cannot be checked"
        if posted >= max_per_day:
            return f"already published {posted} of {max_per_day} posts allowed today"

    quiet = _rule(rules, "publishing", "quiet_hours", None)
    if quiet and ctx.local_time is not None:
        start, end = _parse_time(quiet[0]), _parse_time(quiet[1])
        if in_quiet_hours(ctx.local_time, start, end):
            return f"{ctx.local_time:%H:%M} falls inside quiet hours {quiet[0]}–{quiet[1]}"
    return None


def _check_discount(rules: dict[str, Any], facts: dict[str, Any], ctx: GateContext) -> str | None:
    max_pct = _rule(rules, "pricing", "max_discount_pct", None)
    if max_pct is None:
        return None
    pct = facts.get("discount_pct", MISSING)
    if pct is MISSING:
        return "discount_pct was not supplied, so the discount limit cannot be checked"
    if pct > max_pct:
        return f"discount of {pct}% exceeds the {max_pct}% limit"
    return None


def _check_ad_budget(rules: dict[str, Any], facts: dict[str, Any], ctx: GateContext) -> str | None:
    before = facts.get("before_minor", MISSING)
    after = facts.get("after_minor", MISSING)
    if before is MISSING or after is MISSING:
        return "before_minor/after_minor were not supplied, so budget limits cannot be checked"

    max_daily = _rule(rules, "ads", "max_daily_minor", None)
    if max_daily is not None and after > max_daily:
        return f"daily budget {after} exceeds the cap of {max_daily}"

    max_pct = _rule(rules, "ads", "max_budget_increase_pct_24h", None)
    if max_pct is not None and after > before:
        # A rise from zero has no meaningful percentage; treat it as needing a human.
        if before <= 0:
            return "cannot raise a budget from zero automatically"
        increase = (after - before) / before * 100
        if increase > max_pct:
            return f"increase of {increase:.1f}% exceeds the {max_pct}% cap per 24h"
    return None


def _check_messaging(rules: dict[str, Any], facts: dict[str, Any], ctx: GateContext) -> str | None:
    max_msgs = _rule(rules, "messaging", "max_msgs_per_contact_per_day", None)
    if max_msgs is not None:
        sent = facts.get("msgs_to_contact_today", MISSING)
        if sent is MISSING:
            return (
                "msgs_to_contact_today was not supplied, so the messaging limit cannot be checked"
            )
        if sent >= max_msgs:
            return f"already sent {sent} of {max_msgs} messages to this contact today"

    max_turns = _rule(rules, "messaging", "escalate_after_turns", None)
    if max_turns is not None:
        turns = facts.get("conversation_turns", 0)
        if turns >= max_turns:
            return f"conversation has run {turns} turns; hand it to a human"
    return None


Check = Callable[[dict[str, Any], dict[str, Any], GateContext], str | None]

#: Only consulted when the matrix already said ALLOW.
LIMITS: dict[Action, Check] = {
    Action.PUBLISH_NEW_CONTENT: _check_publishing,
    Action.PUBLISH_SCHEDULED: _check_publishing,
    Action.OFFER_DISCOUNT: _check_discount,
    Action.ADJUST_AD_BUDGET: _check_ad_budget,
    Action.REPLY_MESSAGE: _check_messaging,
}


def decide(action: Action, ctx: GateContext, **facts: Any) -> Decision:
    """Can this action run unattended?

    `facts` are the numbers the limit checks need — posts_today,
    before_minor/after_minor, discount_pct, msgs_to_contact_today. Anything a
    check needs and does not get is treated as a violation, not as zero.
    """
    if action in ALWAYS_HUMAN:
        return Decision(
            Verdict.FORBIDDEN,
            f"{action} is never automated in any mode; escalate to a person",
        )

    per_mode = MATRIX.get(action)
    if per_mode is None:
        # An action nobody thought about is not implicitly allowed.
        return Decision(Verdict.FORBIDDEN, f"unknown action {action!r}; no rule covers it")

    verdict = per_mode.get(ctx.mode)
    if verdict is None:
        return Decision(Verdict.FORBIDDEN, f"unknown autonomy mode {ctx.mode!r}")

    if verdict is not Verdict.ALLOW:
        return Decision(verdict, f"{ctx.mode} mode requires approval for {action}")

    check = LIMITS.get(action)
    if check is not None:
        violation = check(ctx.rules, facts, ctx)
        if violation:
            # Downgrade, never refuse: the dealer can still approve it.
            return Decision(Verdict.NEEDS_APPROVAL, violation, limit=str(action))

    return Decision(Verdict.ALLOW, f"{action} is permitted in {ctx.mode} mode")
