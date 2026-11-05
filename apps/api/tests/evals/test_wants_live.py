"""Live eval: does a real model read what a customer asked for into the car?

Excluded from the default run. `npm run eval:wants`

test_sourcing.py proves the checks with a stubbed reading. This answers what the
stub cannot: whether Gemini, given a customer's words in Arabic, English or
French as the sales team recorded them, names the car the dealer stocks under
the dealer's own spelling — and names none when the words name no car.
"""

from __future__ import annotations

import pytest

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.lifecycle.sourcing import read_interest

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

CATALOGUE = [
    ("BYD", "Leopard 7"),
    ("BYD", "Destroyer 05"),
    ("Nissan", "Patrol"),
    ("Toyota", "Hilux Travo"),
    ("Toyota", "Land Cruiser"),
]


@pytest.mark.parametrize(
    ("interest", "named"),
    [
        ("لاند كروزر ابيض 2025", [("Toyota", "Land Cruiser")]),
        ("Land Cruiser 4.0 GXR, white, export to Algeria", [("Toyota", "Land Cruiser")]),
        (
            "Je cherche un Hilux Travo ou un Patrol",
            [("Toyota", "Hilux Travo"), ("Nissan", "Patrol")],
        ),
        ("بي واي دي ليوبارد", [("BYD", "Leopard 7")]),
        # Never stocked: the cars the buying list is for.
        ("Je cherche un Mitsubishi Pajero 2025", [("Mitsubishi", "Pajero")]),
        ("مرسيدس جي 63", [("Mercedes-Benz", "G 63")]),
        ("a family SUV under 150k", []),
    ],
)
async def test_a_customers_words_are_read_into_the_dealers_own_cars(
    db: None, seeded: None, interest: str, named: list[tuple[str, str]]
) -> None:
    cars = await read_interest(tenant_id=TENANT_A, interest=interest, catalogue=CATALOGUE)
    assert sorted((c.make, c.model) for c in cars) == sorted(named), cars
    assert all(c.quoted.casefold() in interest.casefold() for c in cars)
