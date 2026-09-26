from __future__ import annotations

import pytest

from dealerai.guards.pii import REDACTION, check, check_outbound, redact


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


# ---------------------------------------------------------------------------
# check_outbound — a reply to one customer, rather than a public caption
# ---------------------------------------------------------------------------


def test_the_showroom_number_may_be_given_out() -> None:
    """The difference from `check`: a reply should be able to say where we are."""
    assert (
        check_outbound(
            "You can reach the showroom on +971 4 123 4567.", own_contacts={"+97141234567"}
        )
        == []
    )


def test_somebody_elses_number_may_not() -> None:
    findings = check_outbound(
        "The other buyer, on +971 50 999 8888, offered more.", own_contacts={"+97141234567"}
    )
    assert [f.detail for f in findings] == ["+971 50 999 8888"]
    assert "not the dealership's own" in findings[0].message


def test_formatting_cannot_smuggle_our_own_number_past() -> None:
    """Compared digit by digit, because nobody writes a number the same way twice."""
    assert check_outbound("Call 04-123-4567.", own_contacts={"+971 4 123 4567"}) == []


def test_an_internal_note_is_not_repeated_to_the_customer() -> None:
    note = "He is desperate to buy before the end of the month, push the Prado hard"
    findings = check_outbound(
        "I understand you are desperate to buy before the end of the month, so the Prado suits.",
        own_contacts=set(),
        notes=[note],
    )
    assert findings and "internal note" in findings[0].message


def test_agreeing_with_a_note_is_not_quoting_it() -> None:
    findings = check_outbound(
        "The Prado would suit you well.", own_contacts=set(), notes=["Push the Prado"]
    )
    assert findings == []


def test_an_empty_note_is_not_a_quotation() -> None:
    assert check_outbound("Hello.", own_contacts=set(), notes=[""]) == []


def test_a_reply_with_nothing_to_hide_passes() -> None:
    assert check_outbound("The Hilux is available at AED 165,000.", own_contacts=set()) == []


def test_the_dealerships_own_email_may_be_given_out() -> None:
    """No digits to compare, so it falls back to the address itself."""
    assert (
        check_outbound(
            "Send the passport copy to Sales@PolluxMotors.ae.",
            own_contacts={"sales@polluxmotors.ae"},
        )
        == []
    )


def test_another_customers_email_is_still_caught() -> None:
    findings = check_outbound(
        "Forward it to karim@example.com.", own_contacts={"sales@polluxmotors.ae"}
    )
    assert [f.detail for f in findings] == ["karim@example.com"]
