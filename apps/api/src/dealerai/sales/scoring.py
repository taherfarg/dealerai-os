"""Signals in, score out — and the reasons, which are the point.

A number nobody can argue with is a number nobody trusts. Every signal that
moved the score comes back with its points and, where the AI found it, the
message it found it in (docs/sales/04-ai-copilot.md § 5).

Pure: the same signals always give the same score. S4 adds the signals a model
finds; the two below are the ones code can see for itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any

#: Signal → points. Per-tenant overrides live in `sales_settings.scoring_weights`;
#: there is no UI for them in Phase 1.
DEFAULT_WEIGHTS: dict[str, int] = {
    "asked_price": 10,
    "asked_availability": 10,
    "asked_export_or_documents": 10,
    "gave_budget_or_timeline_30d": 10,
    "requested_visit_or_test_drive": 15,
    "negotiating_specific_car": 15,
    "shared_id_or_asked_payment_details": 25,
    "responsive": 5,
    "silent": -10,
}

#: What the salesperson reads in "Why this score".
LABELS: dict[str, str] = {
    "asked_price": "Asked the price",
    "asked_availability": "Asked whether it is available",
    "asked_export_or_documents": "Asked about export or documents",
    "gave_budget_or_timeline_30d": "Gave a budget or a date within a month",
    "requested_visit_or_test_drive": "Asked to visit or test drive",
    "negotiating_specific_car": "Negotiating one car",
    "shared_id_or_asked_payment_details": "Sent an ID or asked how to pay",
    "responsive": "Replies quickly",
    "silent": "Has gone quiet",
}

HOT = 70
WARM = 40

#: Below this many exchanges, a quick reply is politeness, not a pattern.
_ENOUGH_REPLIES = 3


@dataclass(frozen=True, slots=True)
class Signal:
    name: str
    #: The message that proves it, when the AI found it in one.
    evidence_message_id: str | None = None
    #: How many times it counts. `silent` counts once per full week.
    times: int = 1


def band(score_value: int) -> str:
    if score_value >= HOT:
        return "hot"
    return "warm" if score_value >= WARM else "cold"


def score(
    signals: list[Signal], weights: dict[str, int] | None = None
) -> tuple[int, str, list[dict[str, Any]]]:
    """`(score, band, reasons)` — and the reasons add up to the score."""
    table = {**DEFAULT_WEIGHTS, **(weights or {})}
    reasons: list[dict[str, Any]] = []
    total = 0
    for signal in signals:
        points = table.get(signal.name)
        if points is None:
            # A signal this version does not know is worth nothing rather than an
            # error: a lead row written by a newer API must still render in an
            # older one.
            continue
        points *= signal.times
        total += points
        reasons.append(
            {
                "signal": signal.name,
                "label": LABELS.get(signal.name, signal.name.replace("_", " ").capitalize()),
                "points": points,
                "evidence_message_id": signal.evidence_message_id,
            }
        )
    clamped = max(0, min(100, total))
    return clamped, band(clamped), reasons


def from_stored(rows: list[dict[str, Any]] | None) -> list[Signal]:
    """The signals as the lead row keeps them, ignoring anything unrecognisable."""
    return [
        Signal(
            name=str(row["signal"]),
            evidence_message_id=(
                str(row["evidence_message_id"]) if row.get("evidence_message_id") else None
            ),
            times=int(row.get("times", 1)),
        )
        for row in (rows or [])
        if isinstance(row, dict) and row.get("signal")
    ]


def observed_signals(
    inbound_at: list[datetime], reply_latencies: list[timedelta], now: datetime
) -> list[Signal]:
    """The two signals code can see without a model: pace, and silence."""
    found: list[Signal] = []
    if len(reply_latencies) >= _ENOUGH_REPLIES:
        # Seconds, not timedeltas: median over durations works at runtime and
        # not in the type checker, and the comparison reads the same either way.
        middle = median(latency.total_seconds() for latency in reply_latencies)
        if middle < timedelta(hours=1).total_seconds():
            found.append(Signal("responsive"))
    if inbound_at:
        weeks = (now - max(inbound_at)) // timedelta(weeks=1)
        if weeks >= 1:
            found.append(Signal("silent", times=int(weeks)))
    return found
