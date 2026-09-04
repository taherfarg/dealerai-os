"""CSV import.

The parsing rules are pure and tested directly. The endpoint tests use a
hand-written mapping, which is exactly what a confirmed one is — whether the
model *proposes* a good mapping is a model question, and lives in
tests/evals/test_csv_mapping_live.py.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import TENANT_A, USER_A, reseed
from dealerai import inventory
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.inventory import _number, build, coerce, decode, read_rows, rows_to_vehicles
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed())
    asyncio.run(_clear_events())
    with TestClient(app) as c:
        yield c


async def _clear_events() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("delete from events")
    finally:
        await conn.close()


def auth() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(USER_A, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


# --------------------------------------------------------------------------
# numbers — the part that costs money to get wrong
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("165000", "165000"),
        ("165,000", "165000"),
        ("165.000", "165000"),
        ("AED 165,000", "165000"),
        ("165 000", "165000"),
        ("165,000.50", "165000.50"),
        ("165.000,50", "165000.50"),
        ("١٦٥٠٠٠", "165000"),
        ("١٦٥,٠٠٠ درهم", "165000"),
        ("12 000 km", "12000"),
    ],
)
def test_numbers_survive_a_spreadsheet(raw: str, expected: str) -> None:
    assert _number(raw) == Decimal(expected)


def test_a_dotted_thousands_group_is_not_a_decimal() -> None:
    """The expensive one. Reading "165.000" as 165 prices a Land Cruiser at 165
    dirhams, and nobody notices until a customer arrives to buy it."""
    assert _number("165.000") == Decimal(165000)


def test_a_cell_with_no_number_is_an_error_not_a_zero() -> None:
    """A price of zero is a free car. Refusing the row is the only safe read."""
    for junk in ("N/A", "-", "call us", ""):
        with pytest.raises(ValueError):
            _number(junk)


def test_price_becomes_minor_units_under_the_row_currency() -> None:
    assert coerce("price", "165,000", "AED") == ("price_minor", 16_500_000)
    assert coerce("price", "1,000", "KWD") == ("price_minor", 1_000_000)


# --------------------------------------------------------------------------
# reading the file
# --------------------------------------------------------------------------


def test_a_semicolon_file_is_not_one_giant_column() -> None:
    """What Excel writes on a machine whose locale uses comma as the decimal
    mark, which is most of the Gulf."""
    headers, rows = read_rows("Make;Model;Price\nToyota;Land Cruiser;165.000\n")
    assert headers == ["Make", "Model", "Price"]
    assert rows[0]["Price"] == "165.000"


def test_a_utf8_bom_does_not_become_part_of_the_first_header() -> None:
    """Excel writes one. Without utf-8-sig the first column is named
    '﻿Make', which matches no mapping the user confirmed."""
    headers, _ = read_rows(decode("Make,Model\nKia,Sportage\n".encode("utf-8-sig")))
    assert headers[0] == "Make"


def test_an_arabic_windows_export_is_readable() -> None:
    raw = "الماركة,الموديل\nتويوتا,لاند كروزر\n".encode("cp1256")
    headers, rows = read_rows(decode(raw))
    assert headers == ["الماركة", "الموديل"]
    assert rows[0]["الموديل"] == "لاند كروزر"


def test_blank_rows_are_skipped() -> None:
    _, rows = read_rows("Make,Model\nKia,Sportage\n,\n\nHonda,Civic\n")
    assert len(rows) == 2


def test_a_file_with_no_header_is_refused() -> None:
    with pytest.raises(ValueError, match="header"):
        read_rows("")


# --------------------------------------------------------------------------
# mapping a row
# --------------------------------------------------------------------------

MAPPING = {"Make": "make", "Model": "model", "Price": "price", "KM": "mileage_km"}


def test_a_mapped_row_becomes_a_vehicle() -> None:
    vehicle = build(
        MAPPING, {"Make": "Toyota", "Model": "Land Cruiser", "Price": "165,000", "KM": "12,000"}
    )
    assert vehicle.make == "Toyota"
    assert vehicle.price_minor == 16_500_000
    assert vehicle.mileage_km == 12_000


def test_an_empty_cell_leaves_the_field_unset() -> None:
    """Not an empty string. `engine = ''` in the record reads as "we know the
    engine and it is nothing"."""
    vehicle = build({**MAPPING, "Engine": "engine"}, {"Make": "Kia", "Model": "Rio", "Engine": " "})
    assert vehicle.engine is None


def test_a_features_cell_splits_on_any_separator() -> None:
    vehicle = build(
        {"Make": "make", "Model": "model", "Extras": "features"},
        {"Make": "Kia", "Model": "Rio", "Extras": "Sunroof; Leather | 360 camera"},
    )
    assert vehicle.features == ["Sunroof", "Leather", "360 camera"]


def test_a_currency_column_applies_to_that_rows_price() -> None:
    vehicle = build(
        {"Make": "make", "Model": "model", "Price": "price", "Cur": "currency"},
        {"Make": "Kia", "Model": "Rio", "Price": "5,000", "Cur": "kwd"},
    )
    assert vehicle.price_minor == 5_000_000, "KWD is a 3-decimal currency"


def test_a_mapping_naming_a_column_we_do_not_import_is_refused() -> None:
    with pytest.raises(ValueError, match="not importable"):
        build({"Notes": "salesperson"}, {"Notes": "Ahmed"})


def test_one_broken_row_does_not_take_the_others_with_it() -> None:
    vehicles, errors = rows_to_vehicles(
        MAPPING,
        [
            {"Make": "Kia", "Model": "Rio", "Price": "50,000", "KM": "0"},
            {"Make": "", "Model": "Civic", "Price": "60,000", "KM": "0"},
            {"Make": "Honda", "Model": "Civic", "Price": "70,000", "KM": "0"},
        ],
    )
    assert [v.make for _, v in vehicles] == ["Kia", "Honda"]
    assert [e.row for e in errors] == [2]


# --------------------------------------------------------------------------
# the acceptance test: 50 messy rows, 3 of them broken
# --------------------------------------------------------------------------

MESSY_HEADER = "Ref,الماركة,Model / الموديل,Year,Km,Price (AED),Colour,Extras,Salesperson\n"

CONFIRMED = {
    "Ref": "stock_number",
    "الماركة": "make",
    "Model / الموديل": "model",
    "Year": "model_year",
    "Km": "mileage_km",
    "Price (AED)": "price",
    "Colour": "exterior_color",
    "Extras": "features",
    # "Salesperson" is deliberately unmapped — a real confirmation leaves the
    # columns we have no field for alone.
}

MAKES = ["Toyota", "Nissan", "Kia", "Honda", "Mitsubishi"]


def messy_csv() -> bytes:
    """50 rows as a dealer would actually send them, three of which are broken.

    Broken on purpose: row 10 has no make, row 20 has a price nobody can parse,
    row 30 has a year from a mistyped cell.
    """
    lines = [MESSY_HEADER]
    for i in range(1, 51):
        make = MAKES[i % len(MAKES)]
        year = 2018 + (i % 7)
        price = f'"{140 + i},000"'
        km = f'"{i * 1000:,}"'
        if i == 10:
            make = ""
        if i == 20:
            price = "on request"
        if i == 30:
            year = 20
        lines.append(
            f"TY-{4400 + i},{make},Model {i},{year},{km},{price},Pearl White,"
            f"Sunroof; Leather,Ahmed\n"
        )
    return "".join(lines).encode("utf-8-sig")


def test_fifty_messy_rows_import_with_three_reported(client: TestClient) -> None:
    response = client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        data={"mapping": json.dumps(CONFIRMED)},
        headers=auth(),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["created"] == 47
    assert [e["row"] for e in body["errors"]] == [10, 20, 30]

    listed = client.get("/v1/vehicles?limit=200", headers=auth()).json()
    imported = [v for v in listed if (v["stock_number"] or "").startswith("TY-")]
    assert len(imported) == 47

    first = next(v for v in imported if v["stock_number"] == "TY-4401")
    assert first["make"] == MAKES[1]
    assert first["price"] == {"amount_minor": 14_100_000, "currency": "AED"}
    assert first["mileage_km"] == 1000
    assert first["features"] == ["Sunroof", "Leather"]


def test_every_error_says_which_row_and_why(client: TestClient) -> None:
    """A dealer fixes the file from this list. "3 rows failed" does not help."""
    body = client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        data={"mapping": json.dumps(CONFIRMED)},
        headers=auth(),
    ).json()
    by_row = {e["row"]: e["message"] for e in body["errors"]}
    assert "make" in by_row[10]
    assert "on request" in by_row[20]
    assert "model_year" in by_row[30]


def test_an_imported_vehicle_is_queued_for_enrichment(client: TestClient) -> None:
    """Import is the front half of W2. Without the event the cars land as rows
    and nothing ever looks at them."""
    client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        data={"mapping": json.dumps(CONFIRMED)},
        headers=auth(),
    )
    count = asyncio.run(_count_events("vehicle.created"))
    assert count == 47


def test_a_duplicate_stock_number_fails_only_its_own_row(client: TestClient) -> None:
    csv_bytes = b"Ref,Make,Model\nTY-1,Kia,Rio\nTY-2,Honda,Civic\nTY-1,Toyota,Yaris\n"
    mapping = {"Ref": "stock_number", "Make": "make", "Model": "model"}
    body = client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", csv_bytes, "text/csv")},
        data={"mapping": json.dumps(mapping)},
        headers=auth(),
    ).json()
    assert body["created"] == 2
    assert body["errors"][0]["row"] == 3
    assert "duplicate" in body["errors"][0]["message"]


# --------------------------------------------------------------------------
# the mapping must be confirmed, and must be sane
# --------------------------------------------------------------------------


def test_import_requires_a_mapping(client: TestClient) -> None:
    """There is no path from a model's guess to a written row. Omitting the
    mapping is a refusal, not a fallback to the proposal."""
    response = client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        headers=auth(),
    )
    assert response.status_code == 400
    assert client.get("/v1/vehicles?limit=200", headers=auth()).json() == [
        v
        for v in client.get("/v1/vehicles?limit=200", headers=auth()).json()
        if not (v["stock_number"] or "").startswith("TY-")
    ], "rows were written without a confirmed mapping"


@pytest.mark.parametrize(
    ("mapping", "reason"),
    [
        ("not json", "valid JSON"),
        ('{"Ref": "salesperson"}', "not importable"),
        ('{"Ref": "stock_number"}', "make and model"),
        ('["Ref"]', "header -> field"),
    ],
)
def test_a_bad_mapping_is_refused_before_anything_is_written(
    client: TestClient, mapping: str, reason: str
) -> None:
    response = client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        data={"mapping": mapping},
        headers=auth(),
    )
    assert response.status_code == 422
    assert reason in response.text


def test_import_needs_more_than_a_viewer(client: TestClient) -> None:
    from conftest import USER_B

    response = client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        data={"mapping": json.dumps(CONFIRMED)},
        headers={
            "Authorization": f"Bearer {mint_test_token(USER_B, secret=SECRET)}",
            "X-Tenant-Id": str(TENANT_A),
        },
    )
    assert response.status_code == 404, "another tenant's user sees no tenant, not a 403"


def test_a_row_cap_exists(client: TestClient) -> None:
    huge = "Make,Model\n" + "Kia,Rio\n" * (inventory.MAX_ROWS + 1)
    response = client.post(
        "/v1/vehicles/import",
        files={"file": ("stock.csv", huge.encode(), "text/csv")},
        data={"mapping": json.dumps({"Make": "make", "Model": "model"})},
        headers=auth(),
    )
    assert response.status_code == 422
    assert "split the file" in response.text


async def _count_events(event_type: str) -> int:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        value: Any = await conn.fetchval(
            "select count(*) from events where event_type = $1 and tenant_id = $2",
            event_type,
            TENANT_A,
        )
        return int(value)
    finally:
        await conn.close()


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------

PROPOSAL = {
    "columns": [
        {"header": "Ref", "field": "stock_number"},
        {"header": "الماركة", "field": "make"},
        {"header": "Model / الموديل", "field": "model"},
        {"header": "Salesperson", "field": None},
        {"header": "A column not in the file", "field": "vin"},
    ]
}


@pytest.fixture
def stub_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.genai import types

    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=json.dumps(PROPOSAL))]),
                finish_reason=types.FinishReason.STOP,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=50, total_token_count=150
        ),
    )

    class Models:
        async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
            return response

    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": Models()})()})()
    )


def test_preview_returns_a_proposal_and_writes_nothing(
    client: TestClient, stub_model: None
) -> None:
    response = client.post(
        "/v1/vehicles/import/preview",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        headers=auth(),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["row_count"] == 50
    assert body["headers"][0] == "Ref"
    assert len(body["sample"]) == inventory.SAMPLE_ROWS
    assert body["mapping"]["الماركة"] == "make"
    assert "Salesperson" not in body["mapping"], "a null field means leave the column alone"

    listed = client.get("/v1/vehicles?limit=200", headers=auth()).json()
    assert not [v for v in listed if (v["stock_number"] or "").startswith("TY-")]


def test_a_proposed_header_that_is_not_in_the_file_is_discarded(
    client: TestClient, stub_model: None
) -> None:
    """Nothing stops the model returning a header it invented, and a mapping for
    a column that does not exist maps nothing while looking like it does."""
    body = client.post(
        "/v1/vehicles/import/preview",
        files={"file": ("stock.csv", messy_csv(), "text/csv")},
        headers=auth(),
    ).json()
    assert "A column not in the file" not in body["mapping"]
    assert set(body["mapping"]) <= set(body["headers"])
