"""`--update-goldens` writes the goldens instead of comparing against them.

A separate script would have to import the test's own sample slots and its
stand-in photograph, or duplicate them — and a golden generated from slightly
different input than the test renders is a golden that fails for a reason
nobody can see. Same code path, one flag.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="rewrite the creative goldens for this machine instead of comparing",
    )


@pytest.fixture(scope="module")
def update_goldens(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-goldens"))
