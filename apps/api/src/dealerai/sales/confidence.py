"""How much to trust this draft — decided in code, from facts the model does
not choose.

A model asked to rate its own confidence rates it high. Every input here is
either arithmetic (the classifier's own number) or an observation about what
happened during the run: whether a regeneration was needed, whether the guards
passed first time, whether any source was found. None of it is an opinion.

Calibration is checked monthly by the eval report: acceptance must come out
ordered high > medium > low. If it does not, these thresholds are wrong and the
report says so (docs/sales/04-ai-copilot.md § 3).
"""

from __future__ import annotations

#: Things a person decides. None of them is about how well the model wrote —
#: a perfect draft about a complaint still needs somebody to read it.
NEEDS_A_PERSON = frozenset({"complaint", "negotiation", "financing", "trade_in", "human_request"})

#: Intents a well-grounded draft can be trusted on.
CAN_BE_HIGH = frozenset(
    {
        "greeting",
        "price",
        "availability",
        "specs",
        "export_shipping",
        "visit_test_drive",
        "documents_payment",
    }
)

#: Intents whose answer is a fact. With no source, the draft is guessing, and
#: guessing about a price is the one thing this product may never do.
FACT_BEARING = frozenset({"price", "availability", "specs", "export_shipping", "documents_payment"})

MIN_INTENT_CONFIDENCE = 0.6
HIGH_INTENT_CONFIDENCE = 0.85


def band(
    intent: str,
    *,
    intent_confidence: float,
    needs_human: str | None,
    regenerated: bool,
    guards_passed_first_time: bool,
    has_sources: bool,
) -> str:
    """`"low"`, `"medium"` or `"high"` — evaluated in that order.

    The order is the specification, not an implementation detail: a
    perfectly-classified price answer that needed a second attempt is low, not
    high, because the first attempt broke a guard and that is exactly when a
    person should read it.
    """
    if (
        intent in NEEDS_A_PERSON
        or needs_human
        or regenerated
        or intent_confidence < MIN_INTENT_CONFIDENCE
    ):
        return "low"
    if (
        intent_confidence >= HIGH_INTENT_CONFIDENCE
        and intent in CAN_BE_HIGH
        and guards_passed_first_time
        and (intent not in FACT_BEARING or has_sources)
    ):
        return "high"
    return "medium"
