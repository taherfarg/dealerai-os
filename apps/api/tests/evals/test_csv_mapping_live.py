"""Live eval: does the real model read a dealer's column headers correctly?

Excluded from the default run. `npm run eval:csv`

A wrong mapping is not a wrong answer, it is 50 wrong rows — and the human
confirmation step means a *nearly* right proposal is fine while a confidently
wrong one is the danger. So these assert two different things: that the obvious
columns are found, and that the ambiguous ones are left null rather than
guessed.
"""

from __future__ import annotations

import pytest

from conftest import TENANT_A
from dealerai.config import get_settings
from dealerai.inventory import propose_mapping

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

HEADERS = [
    "Ref",
    "الماركة",
    "Model / الموديل",
    "Year",
    "Km",
    "Price (AED)",
    "Net",
    "Colour",
    "Extras",
    "Salesperson",
    "Arrived",
]

ROWS = [
    {
        "Ref": "TY-4471",
        "الماركة": "تويوتا",
        "Model / الموديل": "Land Cruiser",
        "Year": "2022",
        "Km": "18,400",
        "Price (AED)": "265,000",
        "Net": "248,000",
        "Colour": "Pearl White",
        "Extras": "Sunroof; Leather",
        "Salesperson": "Ahmed",
        "Arrived": "2025-11-02",
    },
    {
        "Ref": "NS-2210",
        "الماركة": "نيسان",
        "Model / الموديل": "Patrol",
        "Year": "2023",
        "Km": "9,100",
        "Price (AED)": "310,000",
        "Net": "295,000",
        "Colour": "Black",
        "Extras": "360 camera",
        "Salesperson": "Sara",
        "Arrived": "2025-12-14",
    },
]


async def test_a_bilingual_header_row_maps_correctly(db: None, seeded: None) -> None:
    proposal = await propose_mapping(tenant_id=TENANT_A, headers=HEADERS, sample=ROWS)
    mapping = proposal.as_dict()

    expected = {
        "Ref": "stock_number",
        "الماركة": "make",
        "Model / الموديل": "model",
        "Year": "model_year",
        "Km": "mileage_km",
        "Price (AED)": "price",
        "Colour": "exterior_color",
        "Extras": "features",
    }
    wrong = {h: (mapping.get(h), f) for h, f in expected.items() if mapping.get(h) != f}
    assert not wrong, f"mis-mapped: {wrong}"


async def test_the_internal_price_column_is_not_the_advertised_one(db: None, seeded: None) -> None:
    """The Net column is the discount floor. Mapping it to `price` would advertise every
    car at the dealer's own bottom line."""
    mapping = (await propose_mapping(tenant_id=TENANT_A, headers=HEADERS, sample=ROWS)).as_dict()
    assert mapping.get("Net") in (None, "min_price"), f"Net mapped to {mapping.get('Net')!r}"


async def test_columns_with_no_home_are_left_alone(db: None, seeded: None) -> None:
    """A guess here writes a salesperson's name into every record. Null costs
    the dealer one glance at a confirmation screen."""
    mapping = (await propose_mapping(tenant_id=TENANT_A, headers=HEADERS, sample=ROWS)).as_dict()
    assert "Salesperson" not in mapping
    assert "Arrived" not in mapping
