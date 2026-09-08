"""CSV import: decode, map, coerce, and report per row.

A dealer's stock list is a spreadsheet somebody has been editing for four years.
Headers are in two languages, prices carry currency symbols and thousands
separators, half the rows have a trailing empty column, and three rows are
broken. Rejecting the file teaches them to stop trying; importing 47 of 50 rows
and naming the other three is the outcome they actually want.

Everything here is pure except `propose_mapping`, so the parsing rules are
testable without a database, a model, or a fixture file.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from .ai.gateway import SystemLayers, complete
from .ai.models import TaskKind
from .ai.prompts import load
from .core.money import Money
from .core.text import ascii_digits
from .routes.vehicles import VehicleCreate

#: Beyond this the request stops being a request. A dealer with a bigger file
#: gets the async path, and will tell us before we need to guess the number.
# ponytail: synchronous import; move to storage + an event when someone hits it.
MAX_ROWS = 2000
SAMPLE_ROWS = 3

#: Columns whose CSV form is major units. A spreadsheet says 165,000, not
#: 16500000, and the conversion is the one place this module touches money.
MONEY_FIELDS = {"price": "price_minor", "min_price": "min_price_minor"}
INT_FIELDS = {"model_year", "mileage_km", "seats"}
LIST_FIELDS = {"features", "target_markets"}

#: `specs` is excluded: a CSV cell cannot carry a JSON object, and letting one
#: try invites a column of escaped braces into the record.
TEXT_FIELDS = frozenset(VehicleCreate.model_fields) - {
    "specs",
    "price_minor",
    "min_price_minor",
    *INT_FIELDS,
    *LIST_FIELDS,
}

MAPPABLE: frozenset[str] = frozenset(
    TEXT_FIELDS | INT_FIELDS | LIST_FIELDS | set(MONEY_FIELDS) | {"currency"}
)

MappableField = Literal[
    "make",
    "model",
    "trim",
    "model_year",
    "vehicle_condition",
    "mileage_km",
    "price",
    "min_price",
    "currency",
    "stock_number",
    "vin",
    "engine",
    "transmission",
    "fuel",
    "exterior_color",
    "interior_color",
    "seats",
    "features",
    "target_markets",
    "steering",
    "location",
]


class MappedColumn(BaseModel):
    header: str
    field: MappableField | None = Field(
        default=None, description="The vehicle field this column holds, or null to ignore it."
    )


class MappingProposal(BaseModel):
    columns: list[MappedColumn]

    def as_dict(self) -> dict[str, str]:
        return {c.header: c.field for c in self.columns if c.field}


class RowError(BaseModel):
    row: int = Field(description="1-based row number in the file, excluding the header.")
    message: str


class ImportResult(BaseModel):
    created: int
    errors: list[RowError]


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------

#: Excel on an Arabic Windows install writes cp1256, and it is indistinguishable
#: from broken UTF-8 unless you try it. latin-1 last because it decodes any byte
#: sequence at all — it is the "never fail" fallback, not a real guess.
ENCODINGS = ("utf-8-sig", "cp1256", "latin-1")


def decode(raw: bytes) -> str:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("could not decode the file as text")  # pragma: no cover - latin-1 catches all


def read_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Headers and rows. Sniffs the delimiter, because an Arabic Excel export is
    semicolon-separated and a comma-only reader sees one giant column."""
    sample = text[:8192]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip() for h in reader.fieldnames or []]
    if not headers:
        raise ValueError("the file has no header row")

    rows: list[dict[str, str]] = []
    for raw_row in reader:
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"more than {MAX_ROWS} rows; split the file")
        row = {(k or "").strip(): (v or "") for k, v in raw_row.items() if k is not None}
        if any(v.strip() for v in row.values()):
            rows.append(row)
    return headers, rows


# --------------------------------------------------------------------------
# coercion
# --------------------------------------------------------------------------


def _number(raw: str) -> Decimal:
    """A number out of whatever the spreadsheet had in the cell.

    Separator rules, in order:
      * both `,` and `.` present — the last one is the decimal point
      * one separator with exactly three digits after it — thousands ("165.000")
      * one separator with one or two digits after it — decimal ("165.50")

    The middle rule is the one that matters: reading "165.000" as 165 prices a
    Land Cruiser at 165 dirhams, and it is the failure a dealer would not spot
    until a customer arrived to buy it.
    """
    # ponytail: this misreads a genuine 3-decimal KWD amount as thousands. No
    # car costs 1.5 KWD, so the trade is right; revisit if fils-level prices
    # ever appear in an import.
    text = ascii_digits(raw).strip()
    kept = "".join(c for c in text if c.isdigit() or c in ",.-")
    if not any(c.isdigit() for c in kept):
        raise ValueError(f"no number in {raw!r}")

    last = max(kept.rfind(","), kept.rfind("."))
    if last == -1:
        cleaned = kept
    else:
        after = len(kept) - last - 1
        head = kept[:last].replace(",", "").replace(".", "")
        cleaned = f"{head}.{kept[last + 1 :]}" if 1 <= after <= 2 else head + kept[last + 1 :]
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"could not read a number from {raw!r}") from exc


def coerce(field: str, raw: str, currency: str) -> tuple[str, Any]:
    """One cell to one field value. Returns the *record* field name, which is
    not always the CSV one — `price` becomes `price_minor`."""
    value = raw.strip()
    if field in MONEY_FIELDS:
        return MONEY_FIELDS[field], Money.from_major(_number(value), currency).amount_minor
    if field in INT_FIELDS:
        return field, int(_number(value))
    if field in LIST_FIELDS:
        return field, [
            p.strip() for p in value.replace(";", ",").replace("|", ",").split(",") if p.strip()
        ]
    if field == "vehicle_condition":
        return field, value.strip().lower()
    if field == "steering":
        return field, value.strip().lower()
    return field, value


def build(mapping: dict[str, str], row: dict[str, str]) -> VehicleCreate:
    """One CSV row to a validated vehicle. Raises on anything unusable."""
    unknown = set(mapping.values()) - MAPPABLE
    if unknown:
        raise ValueError(f"not importable columns: {', '.join(sorted(unknown))}")

    currency = next(
        (row[h].strip().upper() for h, f in mapping.items() if f == "currency" and row.get(h)),
        "AED",
    )
    data: dict[str, Any] = {}
    for header, field in mapping.items():
        if field == "currency":
            continue
        cell = row.get(header, "")
        if not cell.strip():
            continue
        name, value = coerce(field, cell, currency)
        data[name] = value
    return VehicleCreate(**data)


def rows_to_vehicles(
    mapping: dict[str, str], rows: list[dict[str, str]]
) -> tuple[list[tuple[int, VehicleCreate]], list[RowError]]:
    """Coerce every row. A broken row is reported, never fatal.

    Aborting the whole import on row 12 means the dealer fixes one cell, uploads
    again, and hits row 31. Three round trips later they go back to doing it by
    hand.
    """
    vehicles: list[tuple[int, VehicleCreate]] = []
    errors: list[RowError] = []
    for i, row in enumerate(rows, start=1):
        try:
            vehicles.append((i, build(mapping, row)))
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "row"
            errors.append(RowError(row=i, message=f"{where}: {first['msg']}"))
        except (ValueError, TypeError) as exc:
            errors.append(RowError(row=i, message=str(exc)))
    return vehicles, errors


# --------------------------------------------------------------------------
# the mapping proposal
# --------------------------------------------------------------------------


async def propose_mapping(
    *, tenant_id: UUID, headers: list[str], sample: list[dict[str, str]]
) -> MappingProposal:
    """Guess which column is which. A proposal only — see routes/vehicles.py."""
    preview = "\n".join(
        " | ".join(f"{h}={row.get(h, '')}" for h in headers) for row in sample[:SAMPLE_ROWS]
    )
    result = await complete(
        TaskKind.ANALYSIS,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("csv_mapping")),
        messages=(
            f"## Column headers\n{chr(10).join(headers)}\n\n"
            f"## First rows\n<untrusted>\n{preview}\n</untrusted>"
        ),
        output_schema=MappingProposal,
        trace_name="csv_mapping",
    )
    assert isinstance(result.parsed, MappingProposal)  # noqa: S101 - schema-constrained
    # The model is given the file's headers but nothing stops it returning one
    # it invented, and a header that is not in the file maps a column that does
    # not exist.
    known = set(headers)
    return MappingProposal(columns=[c for c in result.parsed.columns if c.header in known])
