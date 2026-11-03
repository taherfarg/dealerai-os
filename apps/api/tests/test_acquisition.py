"""Lifecycle L1: how a car was bought, what it cost, and who may know.

Three layers, each tested where it lives:

* the arithmetic — currency conversion and the invoice checks — is pure;
* the wall — a person's session that is not cleared sees no cost, even with
  SQL — is Postgres, tested as the application role;
* the door — who may call what — is the API, tested per role.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from PIL import Image

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, TENANT_B, USER_B, reseed_with_people
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.core.money import Money
from dealerai.core.security import mint_test_token
from dealerai.db import session
from dealerai.lifecycle.invoices import Reading, ReadLine, numbers_in, verify
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"

VIEWER = uuid.UUID("cccccccc-1111-4000-8000-0000000000a1")
MARKETER = uuid.UUID("cccccccc-1111-4000-8000-0000000000a2")
ADMIN = uuid.UUID("cccccccc-1111-4000-8000-0000000000a3")


# --------------------------------------------------------------------------
# money in more than one currency — pure
# --------------------------------------------------------------------------


def test_the_same_currency_converts_at_one() -> None:
    assert Money(1_250_000, "AED").convert("1", "AED") == Money(1_250_000, "AED")


def test_a_dollar_amount_becomes_dirhams_at_the_peg() -> None:
    """USD 10,000.00 at 3.6725 is AED 36,725.00 — the peg Pollux pays at."""
    assert Money(1_000_000, "USD").convert("3.6725", "AED") == Money(3_672_500, "AED")


def test_rounding_happens_once_and_half_to_even() -> None:
    """USD 0.01 at 3.6725 is AED 0.036725 — rounds to 0.04, once, at the end."""
    assert Money(1, "USD").convert("3.6725", "AED").amount_minor == 4


def test_a_three_decimal_currency_converts_without_a_factor_of_ten() -> None:
    """KWD has 1000 fils to the dinar. Getting the exponent wrong is a car
    recorded at a tenth of what it cost."""
    assert Money(1_000_000, "KWD").convert("12", "AED") == Money(1_200_000, "AED")


def test_a_float_rate_is_refused() -> None:
    with pytest.raises(TypeError, match="float"):
        Money(100, "USD").convert(3.6725, "AED")  # type: ignore[arg-type]


@pytest.mark.parametrize("rate", ["0", "-3.67"])
def test_a_rate_that_is_not_positive_is_refused(rate: str) -> None:
    with pytest.raises(ValueError, match="positive"):
        Money(100, "USD").convert(rate, "AED")


def test_a_currency_to_itself_at_any_rate_but_one_is_refused() -> None:
    """That is a typo, and silently applying it changes what the car cost."""
    with pytest.raises(ValueError, match="rate of 1"):
        Money(100, "AED").convert("3.6725", "AED")


# --------------------------------------------------------------------------
# reading an invoice — pure
# --------------------------------------------------------------------------


def line(category: str, description: str, amount: str, quote: str) -> ReadLine:
    return ReadLine(category=category, description=description, amount=amount, quote=quote)  # type: ignore[arg-type]


def reading(*lines: ReadLine, total: str | None = None, **extra: Any) -> Reading:
    return Reading(
        currency=extra.pop("currency", "USD"),
        lines=list(lines),
        total=total,
        total_quote=f"TOTAL DUE {total}" if total else None,
        **extra,
    )


COPART = [
    line("purchase", "Sale price", "12,500.00", "Sale Price ........ 12,500.00"),
    line("auction_fee", "Buyer fee", "675.00", "Buyer Fee 675.00"),
    line("auction_fee", "Gate fee", "79.00", "Gate Fee           79.00"),
    line("auction_fee", "Internet bid fee", "129.00", "Virtual Bid Fee 129.00"),
    line("transport", "Towing to port", "450.00", "Transportation 450.00"),
]


def test_a_well_read_invoice_is_proposed_whole() -> None:
    proposal = verify(reading(*COPART, total="13,833.00"))
    assert [ln.amount_minor for ln in proposal.lines] == [1_250_000, 67_500, 7_900, 12_900, 45_000]
    assert proposal.total_minor == 1_383_300
    assert proposal.warnings == []


def test_an_amount_missing_from_its_own_line_is_not_proposed() -> None:
    """The model says it read 675 from a line that says 765. It may be right;
    it is not shown as if it were checked."""
    proposal = verify(reading(line("auction_fee", "Buyer fee", "675.00", "Buyer Fee 765.00")))
    assert proposal.lines == []
    assert "does not appear in its own line" in proposal.warnings[0]


def test_a_dropped_line_shows_up_as_a_total_that_does_not_add_up() -> None:
    """The commonest misreading, caught by arithmetic and nothing else."""
    proposal = verify(reading(*COPART[:4], total="13,833.00"))
    assert len(proposal.lines) == 4
    assert any("450.00 missing" in w for w in proposal.warnings), proposal.warnings


def test_a_doubled_line_shows_up_as_too_much() -> None:
    proposal = verify(reading(*COPART, COPART[2], total="13,833.00"))
    assert any("too much" in w for w in proposal.warnings), proposal.warnings


def test_a_cent_of_rounding_on_the_document_is_not_an_error() -> None:
    proposal = verify(reading(*COPART, total="13,833.01"))
    assert proposal.warnings == []


def test_a_total_not_found_where_it_was_read_is_not_used() -> None:
    proposal = verify(
        Reading(currency="USD", lines=COPART, total="13,833.00", total_quote="Balance 0.00")
    )
    assert proposal.total_minor is None
    assert "does not appear where it was read" in proposal.warnings[0]


def test_an_exchange_rate_printed_on_the_document_is_kept() -> None:
    proposal = verify(reading(*COPART, fx_rate="3.6725", fx_quote="USD 1 = AED 3.6725"))
    assert proposal.fx_rate == Decimal("3.6725")


def test_an_exchange_rate_the_document_does_not_print_is_discarded() -> None:
    """A rate from a model's memory is a guess with four decimal places."""
    proposal = verify(reading(*COPART, fx_rate="3.6725", fx_quote="Payment by wire transfer"))
    assert proposal.fx_rate is None
    assert "exchange rate" in proposal.warnings[0]


def test_an_arabic_receipt_is_read() -> None:
    proposal = verify(
        reading(
            line("customs", "رسوم جمركية", "١٬٢٥٠", "رسوم جمركية ١٬٢٥٠ درهم"),
            currency="AED",
        )
    )
    assert proposal.lines[0].amount_minor == 125_000


def test_a_zero_or_unreadable_amount_is_skipped_with_a_reason() -> None:
    proposal = verify(
        reading(
            line("other", "Discount", "0.00", "Discount 0.00"),
            line("other", "Smudged", "see attached", "Storage see attached"),
        )
    )
    assert proposal.lines == []
    assert len(proposal.warnings) == 2


def test_numbers_in_a_line_are_found_with_the_importers_rules() -> None:
    assert Decimal("12500.00") in numbers_in("Sale Price ........ 12,500.00")
    assert Decimal("1250") in numbers_in("١٬٢٥٠ درهم")


# --------------------------------------------------------------------------
# the wall — Postgres, as the application role
# --------------------------------------------------------------------------


async def _vehicle_with_costs(su: asyncpg.Connection) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, price_minor, min_price_minor)
           values ($1, $2, 'Nissan', 'Patrol', 31000000, 29000000)""",
        vehicle_id,
        TENANT_A,
    )
    await su.execute(
        """insert into vehicle_acquisitions (vehicle_id, tenant_id, source, purchased_at)
           values ($1, $2, 'auction', '2026-10-01')""",
        vehicle_id,
        TENANT_A,
    )
    await su.execute(
        """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                      fx_rate, amount_tenant_minor, incurred_at)
           values ($1, $2, 'purchase', 25000000, 'AED', 1, 25000000, '2026-10-01')""",
        TENANT_A,
        vehicle_id,
    )
    return vehicle_id


async def test_a_salespersons_session_sees_no_cost_even_with_sql(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """The point of the whole slice. A route that forgets to check the
    permission still cannot leak what the dealer paid."""
    vehicle_id = await _vehicle_with_costs(su)
    async with session.tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        assert await conn.fetchval("select count(*) from vehicle_costs") == 0
        assert await conn.fetchval("select count(*) from vehicle_acquisitions") == 0
        landed = await conn.fetchval(
            "select landed_cost_minor from v_vehicle_economics where vehicle_id = $1", vehicle_id
        )
    assert landed == 0, "the view goes through the same wall"


async def test_a_cleared_session_sees_them(db: None, seeded: None, su: asyncpg.Connection) -> None:
    """The control. Without it the test above passes on a table nobody can read."""
    await _vehicle_with_costs(su)
    async with session.tenant_session(TENANT_A, user_id=OWNER, buy_side=True) as conn:
        assert await conn.fetchval("select count(*) from vehicle_costs") == 1
        assert await conn.fetchval("select count(*) from vehicle_acquisitions") == 1


async def test_the_worker_sees_them_without_a_person(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """Pricing (L2) runs in the worker. A session with no person acts on rows
    that were already authorised, as it does everywhere else."""
    await _vehicle_with_costs(su)
    async with session.tenant_session(TENANT_A) as conn:
        assert await conn.fetchval("select count(*) from vehicle_costs") == 1


async def test_an_uncleared_session_cannot_write_a_cost_either(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _vehicle_with_costs(su)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with session.tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
            await conn.execute(
                """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor,
                                              currency, fx_rate, amount_tenant_minor,
                                              incurred_at)
                   values ($1, $2, 'other', 1, 'AED', 1, 1, current_date)""",
                TENANT_A,
                vehicle_id,
            )


async def test_another_tenants_cleared_session_sees_nothing(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    await _vehicle_with_costs(su)
    async with session.tenant_session(TENANT_B, user_id=USER_B, buy_side=True) as conn:
        assert await conn.fetchval("select count(*) from vehicle_costs") == 0


def test_no_customer_facing_code_reads_the_buy_side() -> None:
    """The second lock. Tools and agents run in the worker, which the wall lets
    through — so nothing an agent can call may name these tables at all."""
    src = Path(__file__).resolve().parents[1] / "src" / "dealerai"
    names = ("vehicle_costs", "vehicle_acquisitions", "v_vehicle_economics")
    offenders = [
        f"{path.relative_to(src)} reads {name}"
        for folder in ("tools", "agents", "sales")
        for path in (src / folder).rglob("*.py")
        for name in names
        if name in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


# --------------------------------------------------------------------------
# the door — the API, per role
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


async def _more_people() -> uuid.UUID:
    """The visibility people, plus the three roles they do not include, and one car."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        # The shared wipe knows only the people it seeded; these three are ours.
        await conn.execute(
            "delete from auth.users where id = any($1::uuid[])", [VIEWER, MARKETER, ADMIN]
        )
        for user_id, name, role in (
            (VIEWER, "l1-viewer", "viewer"),
            (MARKETER, "l1-marketer", "marketer"),
            (ADMIN, "l1-admin", "admin"),
        ):
            await conn.execute(
                "insert into auth.users (id, email) values ($1, $2)",
                user_id,
                f"{name}@example.test",
            )
            await conn.execute(
                "insert into profiles (id, full_name, email) values ($1, $2, $3)",
                user_id,
                name,
                f"{name}@example.test",
            )
            await conn.execute(
                "insert into memberships (tenant_id, user_id, role) values ($1, $2, $3)",
                TENANT_A,
                user_id,
                role,
            )
        vehicle_id = uuid.uuid4()
        await conn.execute(
            """insert into vehicles (id, tenant_id, make, model, model_year, vin,
                                     price_minor, min_price_minor, currency)
               values ($1, $2, 'Nissan', 'Patrol', 2023, 'JN8AY2NY0P9000001',
                       31000000, 29000000, 'AED')""",
            vehicle_id,
            TENANT_A,
        )
        return vehicle_id
    finally:
        await conn.close()


@pytest.fixture
def car(_migrated: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return asyncio.run(_more_people())


@pytest.fixture
def client(car: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


LINE = {
    "category": "purchase",
    "description": "Hammer price",
    "vendor": "Copart Dallas",
    "amount_minor": 1_250_000,
    "currency": "USD",
    "fx_rate": "3.6725",
    "incurred_at": "2026-10-01",
}


@pytest.mark.parametrize("who", [SALES_1, MARKETER, VIEWER])
def test_who_may_not_see_what_the_dealer_paid(
    client: TestClient, car: uuid.UUID, who: uuid.UUID
) -> None:
    """Sales negotiates down to it, a marketer has no use for it, and "viewer"
    is handed out more freely than "sees what we paid"."""
    for path in (
        f"/v1/vehicles/{car}/costs",
        f"/v1/vehicles/{car}/acquisition",
        f"/v1/vehicles/{car}/economics",
        "/v1/vehicles/economics",
    ):
        assert client.get(path, headers=auth(who)).status_code == 403, path


def test_a_manager_sees_the_cost_and_cannot_change_it(client: TestClient, car: uuid.UUID) -> None:
    assert client.get(f"/v1/vehicles/{car}/costs", headers=auth(MANAGER)).status_code == 200
    response = client.post(
        f"/v1/vehicles/{car}/costs", json={"lines": [LINE]}, headers=auth(MANAGER)
    )
    assert response.status_code == 403


@pytest.mark.parametrize("who", [OWNER, ADMIN])
def test_owner_and_admin_record_costs(client: TestClient, car: uuid.UUID, who: uuid.UUID) -> None:
    response = client.post(f"/v1/vehicles/{car}/costs", json={"lines": [LINE]}, headers=auth(who))
    assert response.status_code == 201, response.text


def test_another_dealerships_car_is_not_there(client: TestClient, car: uuid.UUID) -> None:
    """404, never 403: a 403 would confirm the car exists."""
    response = client.get(f"/v1/vehicles/{car}/costs", headers=auth(USER_B, TENANT_B))
    assert response.status_code == 404


def test_a_dollar_cost_is_kept_in_dollars_and_counted_in_dirhams(
    client: TestClient, car: uuid.UUID
) -> None:
    [cost] = client.post(
        f"/v1/vehicles/{car}/costs", json={"lines": [LINE]}, headers=auth(OWNER)
    ).json()
    assert cost["amount"] == {"amount_minor": 1_250_000, "currency": "USD"}
    assert cost["amount_tenant"] == {"amount_minor": 4_590_625, "currency": "AED"}
    assert cost["fx_rate"] == "3.6725"


def test_a_foreign_cost_without_a_rate_is_refused(client: TestClient, car: uuid.UUID) -> None:
    """The API never looks a rate up. The person or the document supplies it."""
    response = client.post(
        f"/v1/vehicles/{car}/costs",
        json={"lines": [{**LINE, "fx_rate": None}]},
        headers=auth(OWNER),
    )
    assert response.status_code == 422
    assert "exchange rate" in response.text


def test_a_batch_is_all_or_nothing(client: TestClient, car: uuid.UUID) -> None:
    """A batch is one invoice. Half of one recorded is a landed cost wrong by an
    amount nobody can see."""
    response = client.post(
        f"/v1/vehicles/{car}/costs",
        json={"lines": [LINE, {**LINE, "fx_rate": None}]},
        headers=auth(OWNER),
    )
    assert response.status_code == 422
    assert client.get(f"/v1/vehicles/{car}/costs", headers=auth(OWNER)).json() == []


def test_landed_cost_and_margin(client: TestClient, car: uuid.UUID) -> None:
    """L1's exit criterion, in numbers: five lines in, a landed cost and a
    margin at list and at floor out."""
    lines = [
        {**LINE},
        {**LINE, "category": "auction_fee", "amount_minor": 67_500},
        {**LINE, "category": "transport", "amount_minor": 45_000},
        {
            **LINE,
            "category": "shipping",
            "amount_minor": 380_000,
            "currency": "AED",
            "fx_rate": None,
        },
        {
            **LINE,
            "category": "customs",
            "amount_minor": 230_000,
            "currency": "AED",
            "fx_rate": None,
            "status": "estimate",
        },
    ]
    client.post(f"/v1/vehicles/{car}/costs", json={"lines": lines}, headers=auth(OWNER))
    economics = client.get(f"/v1/vehicles/{car}/economics", headers=auth(OWNER)).json()

    # USD 12,500 + 675 + 450 = 13,625 at 3.6725 = AED 50,037.81; + 3,800 + 2,300.
    # 165,262.5 fils rounds half to even: 165,262.
    actual = 4_590_625 + 247_894 + 165_262 + 380_000
    assert economics["cost_actual"]["amount_minor"] == actual
    assert economics["cost_estimate"]["amount_minor"] == 230_000
    assert economics["landed_cost"]["amount_minor"] == actual + 230_000
    landed = actual + 230_000
    assert economics["margin_at_price"]["amount_minor"] == 31_000_000 - landed
    assert economics["margin_at_floor"]["amount_minor"] == 29_000_000 - landed
    assert economics["margin_bps_at_price"] == round((31_000_000 - landed) * 10_000 / 31_000_000)
    assert economics["cost_lines"] == 5


def test_a_car_with_no_cost_says_so_rather_than_showing_all_profit(
    client: TestClient, car: uuid.UUID
) -> None:
    economics = client.get(f"/v1/vehicles/{car}/economics", headers=auth(OWNER)).json()
    assert economics["margin_at_price"] is None
    assert economics["margin_note"] == "no cost recorded"


def test_every_change_to_a_cost_has_a_name_beside_it(client: TestClient, car: uuid.UUID) -> None:
    [cost] = client.post(
        f"/v1/vehicles/{car}/costs", json={"lines": [LINE]}, headers=auth(OWNER)
    ).json()
    client.patch(
        f"/v1/vehicles/{car}/costs/{cost['id']}",
        json={"amount_minor": 1_300_000},
        headers=auth(ADMIN),
    )
    client.delete(f"/v1/vehicles/{car}/costs/{cost['id']}", headers=auth(OWNER))

    async def actions() -> list[tuple[str, str]]:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            rows = await conn.fetch(
                "select action, actor_id from audit_log where entity_id = $1 order by id",
                uuid.UUID(cost["id"]),
            )
            return [(r["action"], r["actor_id"]) for r in rows]
        finally:
            await conn.close()

    assert asyncio.run(actions()) == [
        ("vehicle_cost.created", str(OWNER)),
        ("vehicle_cost.updated", str(ADMIN)),
        ("vehicle_cost.deleted", str(OWNER)),
    ]


def test_an_edited_amount_is_reconverted(client: TestClient, car: uuid.UUID) -> None:
    """The dirham figure is derived, never patched — or a corrected invoice
    leaves the old landed cost behind."""
    [cost] = client.post(
        f"/v1/vehicles/{car}/costs", json={"lines": [LINE]}, headers=auth(OWNER)
    ).json()
    patched = client.patch(
        f"/v1/vehicles/{car}/costs/{cost['id']}",
        json={"amount_minor": 1_000_000},
        headers=auth(OWNER),
    ).json()
    assert patched["amount_tenant"]["amount_minor"] == 3_672_500


def test_a_line_cannot_point_at_another_tenants_document(
    client: TestClient, car: uuid.UUID
) -> None:
    response = client.post(
        f"/v1/vehicles/{car}/costs",
        json={"lines": [{**LINE, "document_path": f"{TENANT_B}/invoices/2026/10/x.pdf"}]},
        headers=auth(OWNER),
    )
    assert response.status_code == 422


def test_the_acquisition_is_recorded_and_replaced(client: TestClient, car: uuid.UUID) -> None:
    body = {
        "source": "auction",
        "seller": "Copart",
        "reference": "LOT 41",
        "purchased_at": "2026-10-01",
    }
    assert (
        client.put(f"/v1/vehicles/{car}/acquisition", json=body, headers=auth(OWNER)).status_code
        == 200
    )
    client.put(
        f"/v1/vehicles/{car}/acquisition", json={**body, "reference": "LOT 42"}, headers=auth(OWNER)
    )
    got = client.get(f"/v1/vehicles/{car}/acquisition", headers=auth(MANAGER)).json()
    assert got["reference"] == "LOT 42"


def test_the_inventory_list_of_economics_needs_the_permission_and_covers_every_car(
    client: TestClient, car: uuid.UUID
) -> None:
    rows = client.get("/v1/vehicles/economics", headers=auth(OWNER)).json()
    assert car in {uuid.UUID(r["vehicle_id"]) for r in rows}


# --------------------------------------------------------------------------
# reading an invoice through the API — the model stubbed
# --------------------------------------------------------------------------

READING = {
    "currency": "USD",
    "vendor": "Copart",
    "reference": "INV-88123",
    "document_date": "2026-10-01",
    "lines": [
        {
            "category": "purchase",
            "description": "Sale price",
            "amount": "12,500.00",
            "quote": "Sale Price 12,500.00",
        },
        {
            "category": "auction_fee",
            "description": "Buyer fee",
            "amount": "675.00",
            "quote": "Buyer Fee 675.00",
        },
    ],
    "total": "13,175.00",
    "total_quote": "TOTAL DUE 13,175.00",
    "fx_rate": None,
    "fx_quote": None,
}


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    class Models:
        async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
            calls.append(kwargs)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model", parts=[types.Part(text=json.dumps(READING))]
                        ),
                        finish_reason=types.FinishReason.STOP,
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=900, candidates_token_count=200, total_token_count=1100
                ),
            )

    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": Models()})()})()
    )
    return calls


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


def test_reading_an_invoice_proposes_and_writes_nothing(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    response = client.post(
        f"/v1/vehicles/{car}/costs/extract",
        files={"file": ("receipt.jpg", _jpeg(), "image/jpeg")},
        headers=auth(OWNER),
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert [ln["amount_minor"] for ln in proposal["lines"]] == [1_250_000, 67_500]
    assert proposal["needs_fx_rate"] is True, "dollars, no printed rate, an AED dealer"
    assert proposal["warnings"] == []
    assert proposal["document_path"].startswith(f"{TENANT_A}/invoices/")
    assert client.get(f"/v1/vehicles/{car}/costs", headers=auth(OWNER)).json() == []


def test_the_model_is_told_which_car_the_document_is_for(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    """A shipping invoice covers a whole container; the VIN is how the model
    picks this car's lines out of it."""
    client.post(
        f"/v1/vehicles/{car}/costs/extract",
        files={"file": ("receipt.jpg", _jpeg(), "image/jpeg")},
        headers=auth(OWNER),
    )
    sent = str(model[0]["contents"])
    assert "JN8AY2NY0P9000001" in sent


def test_confirming_a_reading_records_it_against_its_document(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    proposal = client.post(
        f"/v1/vehicles/{car}/costs/extract",
        files={"file": ("receipt.jpg", _jpeg(), "image/jpeg")},
        headers=auth(OWNER),
    ).json()
    lines = [
        {
            "category": ln["category"],
            "description": ln["description"],
            "vendor": proposal["vendor"],
            "amount_minor": ln["amount_minor"],
            "currency": ln["currency"],
            "fx_rate": "3.6725",
            "incurred_at": proposal["incurred_at"],
            "source": "document",
            "document_path": proposal["document_path"],
        }
        for ln in proposal["lines"]
    ]
    saved = client.post(
        f"/v1/vehicles/{car}/costs", json={"lines": lines}, headers=auth(OWNER)
    ).json()
    assert {c["document_path"] for c in saved} == {proposal["document_path"]}
    assert all(c["source"] == "document" for c in saved)


def test_reading_needs_the_edit_permission(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    response = client.post(
        f"/v1/vehicles/{car}/costs/extract",
        files={"file": ("receipt.jpg", _jpeg(), "image/jpeg")},
        headers=auth(MANAGER),
    )
    assert response.status_code == 403
    assert model == [], "no model call was paid for"


def test_something_that_is_not_a_document_is_refused_before_a_model_call(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    response = client.post(
        f"/v1/vehicles/{car}/costs/extract",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=auth(OWNER),
    )
    assert response.status_code == 422
    assert model == []
