from __future__ import annotations

import pytest

from dealerai.guards.pii import REDACTION, check, redact


@pytest.mark.parametrize(
    "number",
    ["+971 50 123 4567", "0501234567", "971-55-1234567", "+966 55 123 4567", "٠٥٠١٢٣٤٥٦٧"],
)
def test_a_gulf_phone_number_is_caught(number: str) -> None:
    cleaned, findings = redact(f"Call {number} for details")
    assert findings, f"missed {number!r}"
    assert number.strip() not in cleaned


def test_an_email_is_caught() -> None:
    cleaned, findings = redact("Reach me at ahmed.k@polluxmotors.ae")
    assert cleaned == f"Reach me at {REDACTION}"
    assert "an email address" in findings[0].message


def test_an_emirates_id_is_caught_whole() -> None:
    """Redacting it as a phone number would leave half the digits visible,
    which is worse than either outcome."""
    cleaned, findings = redact("ID 784-1990-1234567-1 on file")
    assert cleaned == f"ID {REDACTION} on file"
    assert len(findings) == 1


def test_ordinary_marketing_copy_is_untouched() -> None:
    text = "2023 Land Cruiser, 18,000 km, AED 265,000. Visit our Al Quoz showroom."
    cleaned, findings = redact(text)
    assert findings == []
    assert cleaned == text


def test_the_finding_carries_what_was_found() -> None:
    """The dealer needs to know which customer's number nearly went out."""
    assert check("call 0501234567")[0].detail == "0501234567"


def test_several_kinds_at_once_are_all_removed() -> None:
    cleaned, findings = redact("a@b.co or 0501234567, ID 784-1990-1234567-1")
    assert len(findings) == 3
    assert cleaned.count(REDACTION) == 3
