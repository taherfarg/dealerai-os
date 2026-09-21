"""The score, and the reasons that have to add up to it. Pure — no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dealerai.sales.scoring import Signal, band, from_stored, observed_signals, score

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def test_a_customer_who_sent_a_passport_is_warm_on_the_way_to_hot() -> None:
    total, level, reasons = score(
        [
            Signal("asked_price", "m1"),
            Signal("requested_visit_or_test_drive", "m2"),
            Signal("shared_id_or_asked_payment_details", "m3"),
            Signal("responsive"),
        ]
    )
    assert (total, level) == (55, "warm")  # 10 + 15 + 25 + 5
    assert reasons[0]["evidence_message_id"] == "m1"
    assert reasons[-1]["signal"] == "responsive"


def test_the_reasons_add_up_to_the_score() -> None:
    """The whole point of returning them: a score you cannot check is a score
    you ignore."""
    signals = [Signal("asked_price"), Signal("negotiating_specific_car"), Signal("silent", times=2)]
    total, _, reasons = score(signals)
    assert sum(reason["points"] for reason in reasons) == total


@pytest.mark.parametrize(
    "total,expected",
    [(100, "hot"), (70, "hot"), (69, "warm"), (40, "warm"), (39, "cold"), (0, "cold")],
)
def test_the_bands_are_where_the_spec_puts_them(total: int, expected: str) -> None:
    assert band(total) == expected


def test_the_score_cannot_leave_nought_to_a_hundred() -> None:
    assert score([Signal("silent", times=9)])[0] == 0
    assert score([Signal("shared_id_or_asked_payment_details")] * 9)[0] == 100


def test_a_signal_this_version_does_not_know_is_worth_nothing() -> None:
    """An older API reading a row a newer one wrote must render, not raise."""
    total, _, reasons = score([Signal("asked_price"), Signal("read_their_mind")])
    assert total == 10
    assert [reason["signal"] for reason in reasons] == ["asked_price"]


def test_a_tenant_can_weigh_a_signal_differently() -> None:
    total, _, reasons = score([Signal("asked_price")], {"asked_price": 30})
    assert total == 30
    assert reasons[0]["points"] == 30, "the reason has to show the points that were counted"


def test_silence_costs_a_week_at_a_time() -> None:
    assert observed_signals([NOW - timedelta(days=22)], [], now=NOW) == [Signal("silent", times=3)]


def test_a_customer_who_wrote_yesterday_is_not_silent() -> None:
    assert observed_signals([NOW - timedelta(days=1)], [], now=NOW) == []


def test_a_customer_who_answers_within_the_hour_is_responsive() -> None:
    quick = [timedelta(minutes=5), timedelta(minutes=40), timedelta(hours=3)]
    assert Signal("responsive") in observed_signals([NOW], quick, now=NOW)


def test_two_quick_replies_are_not_a_pattern() -> None:
    assert observed_signals([NOW], [timedelta(minutes=1), timedelta(minutes=2)], now=NOW) == []


def test_a_stored_row_becomes_a_signal_and_rubbish_does_not() -> None:
    stored = [
        {"signal": "asked_price", "evidence_message_id": "m1", "points": 10},
        {"signal": "silent", "times": 2},
        {"label": "no signal name at all"},
        "not even a row",
    ]
    assert from_stored(stored) == [  # type: ignore[arg-type]
        Signal("asked_price", "m1"),
        Signal("silent", None, 2),
    ]
    assert from_stored(None) == []
