"""The autonomy gate. Every cell of the matrix, and every numeric limit.

The gate is what a dealer is actually trusting when they turn on Autopilot, so
the table in docs/02 § 5 and the table in gate.py are asserted against each
other rather than assumed to match.
"""

from __future__ import annotations

from datetime import time

import pytest

from dealerai.orchestrator.gate import (
    ALWAYS_HUMAN,
    MATRIX,
    Action,
    GateContext,
    Verdict,
    decide,
    in_quiet_hours,
)

MODES = ("copilot", "assisted", "autopilot")

#: Transcribed from docs/02-agent-architecture.md § 5, by hand and on purpose.
#: If someone edits MATRIX without editing the doc, this fails.
EXPECTED = {
    Action.GENERATE_CONTENT: ("allow", "allow", "allow"),
    Action.ANSWER_FAQ: ("needs_approval", "allow", "allow"),
    Action.PUBLISH_SCHEDULED: ("needs_approval", "allow", "allow"),
    Action.REPLY_COMMENT: ("needs_approval", "allow", "allow"),
    Action.QUOTE_PRICE: ("needs_approval", "allow", "allow"),
    Action.REPLY_MESSAGE: ("needs_approval", "needs_approval", "allow"),
    Action.PUBLISH_NEW_CONTENT: ("needs_approval", "needs_approval", "allow"),
    Action.OFFER_DISCOUNT: ("needs_approval", "needs_approval", "allow"),
    Action.ADJUST_AD_BUDGET: ("needs_approval", "needs_approval", "allow"),
    Action.LAUNCH_CAMPAIGN: ("needs_approval", "needs_approval", "needs_approval"),
    Action.CHANGE_VEHICLE_PRICE: ("needs_approval", "needs_approval", "needs_approval"),
    Action.HANDLE_COMPLAINT: ("needs_approval", "needs_approval", "needs_approval"),
}


def ctx(mode: str, **rules: object) -> GateContext:
    return GateContext(mode=mode, rules=dict(rules))


# --------------------------------------------------------------------------
# the matrix
# --------------------------------------------------------------------------


@pytest.mark.parametrize("action", list(EXPECTED))
@pytest.mark.parametrize("mode_index", range(3))
def test_every_matrix_cell(action: Action, mode_index: int) -> None:
    mode = MODES[mode_index]
    expected = EXPECTED[action][mode_index]
    # No limit facts supplied, so limit-checked actions are exercised separately.
    assert MATRIX[action][mode].value == expected


def test_matrix_covers_every_non_human_action() -> None:
    uncovered = [a for a in Action if a not in MATRIX and a not in ALWAYS_HUMAN]
    assert not uncovered, f"actions with no rule: {uncovered}"


@pytest.mark.parametrize("action", sorted(ALWAYS_HUMAN))
@pytest.mark.parametrize("mode", MODES)
def test_always_human_actions_are_forbidden_in_every_mode(action: Action, mode: str) -> None:
    """Not 'needs approval' — the AI does not do these at all, it escalates."""
    assert decide(action, ctx(mode)).verdict is Verdict.FORBIDDEN


def test_an_unknown_action_is_forbidden_not_allowed() -> None:
    """A new action nobody thought about must not be implicitly permitted."""
    assert decide("teleport_the_car", ctx("autopilot")).verdict is Verdict.FORBIDDEN  # type: ignore[arg-type]


def test_an_unknown_mode_is_forbidden() -> None:
    assert decide(Action.REPLY_COMMENT, ctx("yolo")).verdict is Verdict.FORBIDDEN


def test_copilot_still_lets_the_ai_produce_drafts() -> None:
    """Copilot is a complete product: the AI generates, the human sends."""
    assert decide(Action.GENERATE_CONTENT, ctx("copilot")).allowed


# --------------------------------------------------------------------------
# limits downgrade, never refuse
# --------------------------------------------------------------------------


def test_a_breached_limit_downgrades_to_approval_not_refusal() -> None:
    """The dealer can still say yes. Hard refusals train people to widen limits."""
    d = decide(
        Action.PUBLISH_NEW_CONTENT,
        ctx("autopilot", publishing={"max_posts_per_day": 4}),
        posts_today=4,
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "4 of 4" in d.reason


def test_within_the_limit_is_allowed() -> None:
    d = decide(
        Action.PUBLISH_NEW_CONTENT,
        ctx("autopilot", publishing={"max_posts_per_day": 4}),
        posts_today=3,
    )
    assert d.allowed


def test_a_missing_fact_is_a_violation_not_a_zero() -> None:
    """Fail closed. An unnecessary approval prompt costs a click; the other
    mistake costs a dealer's budget."""
    d = decide(
        Action.PUBLISH_NEW_CONTENT,
        ctx("autopilot", publishing={"max_posts_per_day": 4}),
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "posts_today" in d.reason


def test_no_configured_limit_means_no_check() -> None:
    """A tenant that set no rules gets the matrix verdict, not a blocked system."""
    assert decide(Action.PUBLISH_NEW_CONTENT, ctx("autopilot")).allowed


def test_limits_are_not_consulted_when_approval_is_already_required() -> None:
    d = decide(
        Action.PUBLISH_NEW_CONTENT,
        ctx("assisted", publishing={"max_posts_per_day": 4}),
        posts_today=0,
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "assisted mode" in d.reason


# --------------------------------------------------------------------------
# ad budget — the limit with money attached
# --------------------------------------------------------------------------


def test_budget_increase_within_cap_is_allowed() -> None:
    d = decide(
        Action.ADJUST_AD_BUDGET,
        ctx("autopilot", ads={"max_budget_increase_pct_24h": 15}),
        before_minor=10_000,
        after_minor=11_000,
    )
    assert d.allowed


def test_budget_increase_over_cap_needs_approval() -> None:
    d = decide(
        Action.ADJUST_AD_BUDGET,
        ctx("autopilot", ads={"max_budget_increase_pct_24h": 15}),
        before_minor=10_000,
        after_minor=15_000,
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "50.0%" in d.reason


def test_a_decrease_is_never_blocked_by_the_increase_cap() -> None:
    """Spending less is not the risk the cap exists for."""
    d = decide(
        Action.ADJUST_AD_BUDGET,
        ctx("autopilot", ads={"max_budget_increase_pct_24h": 15}),
        before_minor=10_000,
        after_minor=1_000,
    )
    assert d.allowed


def test_raising_a_budget_from_zero_needs_a_human() -> None:
    """Percent-of-zero is undefined, and 0 to anything is a new spend decision."""
    d = decide(
        Action.ADJUST_AD_BUDGET,
        ctx("autopilot", ads={"max_budget_increase_pct_24h": 15}),
        before_minor=0,
        after_minor=50_000,
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_absolute_daily_cap_applies_even_to_a_small_increase() -> None:
    """A 1% rise on an already-huge budget is still over the ceiling."""
    d = decide(
        Action.ADJUST_AD_BUDGET,
        ctx("autopilot", ads={"max_budget_increase_pct_24h": 15, "max_daily_minor": 50_000}),
        before_minor=50_000,
        after_minor=50_100,
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "cap" in d.reason


def test_budget_facts_are_mandatory() -> None:
    d = decide(Action.ADJUST_AD_BUDGET, ctx("autopilot", ads={"max_daily_minor": 100}))
    assert d.verdict is Verdict.NEEDS_APPROVAL


# --------------------------------------------------------------------------
# discount
# --------------------------------------------------------------------------


def test_discount_within_limit_is_allowed() -> None:
    d = decide(
        Action.OFFER_DISCOUNT, ctx("autopilot", pricing={"max_discount_pct": 3}), discount_pct=2
    )
    assert d.allowed


def test_discount_over_limit_needs_approval() -> None:
    d = decide(
        Action.OFFER_DISCOUNT, ctx("autopilot", pricing={"max_discount_pct": 3}), discount_pct=8
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_below_the_floor_is_forbidden_outright() -> None:
    """Distinct from an over-limit discount: this one is never automated at all."""
    assert decide(Action.DISCOUNT_BELOW_FLOOR, ctx("autopilot")).verdict is Verdict.FORBIDDEN


# --------------------------------------------------------------------------
# messaging
# --------------------------------------------------------------------------


def test_message_cap_per_contact_per_day() -> None:
    rules = {"messaging": {"max_msgs_per_contact_per_day": 3}}
    assert decide(
        Action.REPLY_MESSAGE, GateContext("autopilot", rules), msgs_to_contact_today=2
    ).allowed
    assert (
        decide(
            Action.REPLY_MESSAGE, GateContext("autopilot", rules), msgs_to_contact_today=3
        ).verdict
        is Verdict.NEEDS_APPROVAL
    )


def test_a_long_conversation_is_handed_over() -> None:
    d = decide(
        Action.REPLY_MESSAGE,
        GateContext("autopilot", {"messaging": {"escalate_after_turns": 12}}),
        msgs_to_contact_today=0,
        conversation_turns=12,
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "hand it to a human" in d.reason


# --------------------------------------------------------------------------
# quiet hours
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (time(23, 30), True),
        (time(2, 0), True),
        (time(6, 59), True),
        (time(7, 0), False),
        (time(12, 0), False),
        (time(22, 59), False),
    ],
)
def test_quiet_hours_wrap_midnight(now: time, expected: bool) -> None:
    """23:00-07:00 is eight hours of night, not sixteen hours of day."""
    assert in_quiet_hours(now, time(23, 0), time(7, 0)) is expected


def test_daytime_quiet_window_does_not_wrap() -> None:
    assert in_quiet_hours(time(13, 0), time(12, 0), time(14, 0)) is True
    assert in_quiet_hours(time(15, 0), time(12, 0), time(14, 0)) is False


def test_publishing_inside_quiet_hours_needs_approval() -> None:
    d = decide(
        Action.PUBLISH_NEW_CONTENT,
        GateContext(
            "autopilot",
            {"publishing": {"quiet_hours": ["23:00", "07:00"]}},
            local_time=time(2, 30),
        ),
    )
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "quiet hours" in d.reason


def test_publishing_outside_quiet_hours_is_allowed() -> None:
    d = decide(
        Action.PUBLISH_NEW_CONTENT,
        GateContext(
            "autopilot",
            {"publishing": {"quiet_hours": ["23:00", "07:00"]}},
            local_time=time(10, 0),
        ),
    )
    assert d.allowed
