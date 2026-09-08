from __future__ import annotations

import pytest

from dealerai.guards.inventory import check


def test_an_available_vehicle_passes() -> None:
    assert check({"TY-4471": "available"}) == []


@pytest.mark.parametrize("status", ["sold", "reserved", "draft", "archived"])
def test_anything_but_available_is_blocked(status: str) -> None:
    """`reserved` too: it is somebody else's car until the deal falls through,
    and a post about it generates enquiries the dealer has to disappoint."""
    findings = check({"TY-4471": status})
    assert len(findings) == 1
    assert status in findings[0].message


def test_the_finding_names_the_car() -> None:
    """ "A vehicle in this post is sold" is unactionable when the post covers
    four of them."""
    findings = check({"TY-1": "available", "TY-2": "sold", "TY-3": "sold"})
    assert [f.detail for f in findings] == ["TY-2", "TY-3"]


def test_content_about_no_vehicle_at_all_is_blocked() -> None:
    """Almost always a bug upstream — a brief that lost its vehicle ids and
    would otherwise sail through every guard by referencing nothing."""
    assert len(check({})) == 1
