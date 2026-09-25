"""Response targets count business minutes, in the tenant's timezone. No database."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from dealerai.sales.hours import due_at, is_open, open_seconds
from dealerai.sales.settings import SalesSettings

DUBAI = ZoneInfo("Asia/Dubai")
#: Pollux: open every day but Sunday, 09:00–19:00, with a short Saturday.
SETTINGS = SalesSettings.model_validate(
    {
        "first_response_target_min": 5,
        "business_hours": {
            "mon": {"open": "09:00", "close": "19:00"},
            "tue": {"open": "09:00", "close": "19:00"},
            "wed": {"open": "09:00", "close": "19:00"},
            "thu": {"open": "09:00", "close": "19:00"},
            "fri": {"open": "09:00", "close": "19:00"},
            "sat": {"open": "10:00", "close": "14:00"},
        },
    }
)


def dubai(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=DUBAI)


def test_a_weight_for_a_signal_we_do_not_know_loads_anyway() -> None:
    """The scorer ignores unknown signals; settings must not refuse them, or a
    tenant tuned for a newer version would stop loading on an older one."""
    settings = SalesSettings.model_validate(
        {"scoring_weights": {"asked_price": 30, "read_their_mind": 5}}
    )
    assert settings.scoring_weights["asked_price"] == 30


def test_inside_business_hours_the_target_is_just_minutes() -> None:
    assert due_at(dubai("2026-09-16T10:00"), settings=SETTINGS, tz=DUBAI) == dubai(
        "2026-09-16T10:05"
    )


def test_a_message_at_night_is_due_after_opening() -> None:
    """The whole point: 23:30 is not late at 23:35."""
    assert due_at(dubai("2026-09-16T23:30"), settings=SETTINGS, tz=DUBAI) == dubai(
        "2026-09-17T09:05"
    )


def test_minutes_left_at_closing_continue_the_next_morning() -> None:
    assert due_at(dubai("2026-09-16T18:58"), settings=SETTINGS, tz=DUBAI) == dubai(
        "2026-09-17T09:03"
    )


def test_a_closed_day_is_skipped() -> None:
    saturday_evening = dubai("2026-09-19T15:00")  # after Saturday's 14:00 close
    assert due_at(saturday_evening, settings=SETTINGS, tz=DUBAI) == dubai("2026-09-21T09:05")


def test_a_tenant_that_never_closes_uses_the_clock() -> None:
    always = SalesSettings.model_validate({"first_response_target_min": 5, "business_hours": {}})
    assert due_at(dubai("2026-09-19T03:00"), settings=always, tz=DUBAI) == dubai("2026-09-19T03:05")


def test_the_caller_may_ask_for_a_different_target() -> None:
    assert due_at(dubai("2026-09-16T10:00"), settings=SETTINGS, tz=DUBAI, target_minutes=30) == (
        dubai("2026-09-16T10:30")
    )


@pytest.mark.parametrize(
    ("moment", "expected"),
    [("2026-09-16T10:00", True), ("2026-09-16T08:59", False), ("2026-09-20T11:00", False)],
)
def test_is_open_answers_for_the_tenants_week(moment: str, expected: bool) -> None:
    assert is_open(dubai(moment), settings=SETTINGS, tz=DUBAI) is expected


def test_a_tenant_with_no_hours_is_always_open() -> None:
    always = SalesSettings.model_validate({})
    assert is_open(dubai("2026-09-20T03:00"), settings=always, tz=DUBAI) is True


def test_settings_survive_a_key_they_have_never_seen() -> None:
    """sales_settings is read whole; a newer key must not break an older API."""
    settings = SalesSettings.model_validate({"invented_later": 3, "first_response_target_min": 7})
    assert settings.first_response_target_min == 7
    assert settings.unassigned_visible_to_sales is True


def test_an_impossible_target_is_rejected_at_the_edge() -> None:
    with pytest.raises(ValueError):
        SalesSettings.model_validate({"first_response_target_min": 0})


def test_a_day_that_closes_before_it_opens_is_rejected() -> None:
    with pytest.raises(ValueError):
        SalesSettings.model_validate(
            {"business_hours": {"mon": {"open": "19:00", "close": "09:00"}}}
        )


# ---------------------------------------------------------------------------
# how long a customer waited, in the team's hours
# ---------------------------------------------------------------------------


def test_a_wait_inside_one_open_stretch_is_just_the_minutes() -> None:
    asked, answered = dubai("2026-09-16T10:00"), dubai("2026-09-16T10:04")
    assert open_seconds(asked, answered, settings=SETTINGS, tz=DUBAI) == 240


def test_a_wait_counts_only_the_minutes_the_team_is_open() -> None:
    """Written at 23:30, answered at 09:02: two minutes of the team's time."""
    asked, answered = dubai("2026-09-16T23:30"), dubai("2026-09-17T09:02")
    assert open_seconds(asked, answered, settings=SETTINGS, tz=DUBAI) == 120


def test_a_closed_day_counts_nothing() -> None:
    """An hour of Saturday afternoon, no Sunday, half an hour of Monday."""
    asked, answered = dubai("2026-09-19T13:00"), dubai("2026-09-21T09:30")
    assert open_seconds(asked, answered, settings=SETTINGS, tz=DUBAI) == 90 * 60


def test_a_team_without_hours_waited_the_whole_time() -> None:
    asked, answered = dubai("2026-09-16T23:30"), dubai("2026-09-17T09:02")
    assert open_seconds(asked, answered, settings=SalesSettings(), tz=DUBAI) == 34_320


def test_an_answer_before_the_question_is_no_wait() -> None:
    moment = dubai("2026-09-16T10:00")
    assert open_seconds(moment, moment - timedelta(minutes=1), settings=SETTINGS, tz=DUBAI) == 0
