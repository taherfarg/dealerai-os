"""What we know about a customer, and who said so.

Every field is `{value, source, evidence_message_id, updated_at}`. `source` is
`human` or `ai`, and that one word decides the rest: a person's answer is never
overwritten by a later inference, because being corrected and then ignored is
how people stop correcting anything.

The panel shows these fields in the order they are declared here
(docs/sales/08-screens.md § 5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ..core.errors import Unusable
from ..core.money import Money

Source = Literal["human", "ai"]

#: Field → how its value is checked.
FIELDS: dict[str, str] = {
    "interest": "text",
    "budget": "money",
    "purchase_type": "local_or_export",
    "destination": "country",
    "timeline": "text",
    "payment": "payment",
    "trade_in": "bool",
    "objections": "list",
}

_PURCHASE_TYPES = frozenset({"local", "export"})
_PAYMENTS = frozenset({"cash", "finance"})
_MAX_TEXT = 500
_MAX_ITEMS = 20


def check(key: str, value: Any) -> Any:
    """The value as it will be stored, or a 422 naming the field.

    Public because the profile agent validates a proposed field before
    applying it: one bad country code should cost that field, not the run.
    """
    kind = FIELDS.get(key)
    if kind is None:
        raise Unusable(f"{key} is not something we record about a customer")
    if value is None:
        return None
    if kind == "money":
        if not isinstance(value, dict) or "amount_minor" not in value:
            raise Unusable(f"{key} must be an amount in minor units, like 15000000 fils")
        try:
            money = Money(int(value["amount_minor"]), str(value.get("currency") or "AED"))
        except (TypeError, ValueError) as exc:
            raise Unusable(f"{key}: {exc}", ar="هذا المبلغ غير صالح.") from exc
        return {"amount_minor": money.amount_minor, "currency": money.currency}
    if kind == "local_or_export":
        if value not in _PURCHASE_TYPES:
            raise Unusable("purchase_type is local or export")
        return value
    if kind == "payment":
        if value not in _PAYMENTS:
            raise Unusable("payment is cash or finance")
        return value
    if kind == "country":
        code = str(value).upper()
        if len(code) != 2 or not code.isalpha():
            raise Unusable(
                "destination is a two-letter country code, like DZ",
                ar="الوجهة رمز دولة من حرفين، مثل DZ.",
            )
        return code
    if kind == "bool":
        return bool(value)
    if kind == "list":
        if isinstance(value, str) or not isinstance(value, list):
            raise Unusable(f"{key} is a list")
        return [str(item)[:_MAX_TEXT] for item in value][:_MAX_ITEMS]
    return str(value)[:_MAX_TEXT]


def apply(
    profile: dict[str, Any],
    changes: dict[str, Any],
    *,
    source: Source,
    now: datetime,
    evidence_message_id: UUID | str | None = None,
) -> dict[str, Any]:
    """The profile with `changes` written in, honouring who set what.

    An AI run may fill a field nobody has answered and may correct its own
    earlier guess. It may never touch a field a person set. A person may set
    anything, including back to nothing.
    """
    updated = dict(profile)
    for key, raw in changes.items():
        value = check(key, raw)
        held = updated.get(key)
        if source == "ai" and isinstance(held, dict) and held.get("source") == "human":
            continue
        if value is None:
            updated.pop(key, None)
            continue
        updated[key] = {
            "value": value,
            "source": source,
            "evidence_message_id": str(evidence_message_id) if evidence_message_id else None,
            "updated_at": now.isoformat(),
        }
    return updated
