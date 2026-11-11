"""Lifecycle L7: the export file.

Pollux's own procedures are the specification (docs/lifecycle/pollux.md): a
deposit lays out the destination's steps, each step keeps its paper, the bill of
lading draft is checked against the order before the buyer confirms it, and the
commercial invoice is drafted from the record and signed by a person — once,
with a number, and kept as signed.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from PIL import Image

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, reseed_with_people
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.lifecycle import export
from dealerai.lifecycle.export import DocumentSettings, check_draft, draft_invoice, problems
from dealerai.lifecycle.inbound import ShippingProposal
from dealerai.main import app

AED = 100
VIN = "LGXCE4CB0T0001234"

# --------------------------------------------------------------------------
# the procedures — pure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("purchase_type", "destination", "procedure", "steps"),
    [
        ("export", "DZ", "DZ", 11),
        ("export", "TN", "TN", 11),
        ("export", "EG", "other", 9),
        ("local", None, "local", 5),
    ],
)
def test_each_destination_has_its_own_procedure(
    purchase_type: str, destination: str | None, procedure: str, steps: int
) -> None:
    chosen = export.procedure_for(purchase_type, destination)
    assert chosen == procedure
    assert len(export.PROCEDURES[chosen]) == steps


def test_the_procedures_are_pollux_own() -> None:
    """Algeria needs the Dubai Chamber certificate; Tunisia, export plates and no
    Chamber certificate; everywhere else, the customs card."""
    assert "chamber_certificate" in export.PROCEDURES["DZ"]
    assert "export_plates" in export.PROCEDURES["TN"]
    assert "chamber_certificate" not in export.PROCEDURES["TN"]
    assert "customs_card" in export.PROCEDURES["other"]
    for steps in export.PROCEDURES.values():
        assert steps[0] == "customer_documents"
        assert "commercial_invoice" in steps


def _invoice(**over: Any) -> dict[str, Any]:
    order = {
        "currency": "AED",
        "buyer_name": "SARL Atlas Auto",
        "consignee_name": "SARL Atlas Auto",
        "consignee_address": "12 Rue Didouche Mourad, Algiers",
        "consignee_phone": None,
        "purchase_type": "export",
        "destination": "DZ",
        "port_of_discharge": "Algiers",
        "shipping_method": "roro",
        **over.pop("order", {}),
    }
    car = {
        "model_year": 2026,
        "make": "BYD",
        "model": "Seal 06",
        "trim": None,
        "vin": VIN,
        "vehicle_condition": "new",
        "exterior_color": "White",
        "engine": "1.5L DM-i",
        "fuel": "PHEV",
        "transmission": "E-CVT",
        "mileage_km": 0,
        "stock_number": "6046",
        **over.pop("car", {}),
    }
    return draft_invoice(
        seller=over.pop("seller", DocumentSettings(address="DUCAMZ, Ras Al Khor, Dubai")),
        tenant_name="Pollux Motors",
        order=order,
        car=car,
        lines=[
            {"kind": "vehicle", "description": None, "amount_minor": 55_000 * AED},
            {"kind": "freight", "description": "RoRo to Algiers", "amount_minor": 4_500 * AED},
        ],
        issued_on=date(2026, 11, 4),
        number=None,
    )


def test_the_invoice_is_the_record_and_its_total_is_its_sum() -> None:
    invoice = _invoice()
    assert invoice["lines"][0]["description"] == "2026 BYD Seal 06", "the car names itself"
    assert invoice["total_minor"] == 59_500 * AED
    assert invoice["vehicle"]["vin"] == VIN
    assert invoice["seller"]["name"] == "Pollux Motors"
    assert problems(invoice) == []


@pytest.mark.parametrize(
    ("over", "problem"),
    [
        ({"car": {"vin": None}}, "the car has no VIN"),
        ({"order": {"consignee_name": None}}, "the consignee is not recorded"),
        ({"order": {"consignee_address": None}}, "the consignee's address is not recorded"),
        ({"seller": DocumentSettings()}, "the seller's address is not set in Settings → Documents"),
    ],
)
def test_an_invoice_customs_would_stop_cannot_be_signed(over: dict[str, Any], problem: str) -> None:
    assert problems(_invoice(**over)) == [problem]


def test_a_local_sale_needs_no_consignee() -> None:
    local = _invoice(
        order={"purchase_type": "local", "consignee_name": None, "consignee_address": None}
    )
    assert problems(local) == []


def _proposal(**over: Any) -> ShippingProposal:
    base: dict[str, Any] = {
        "kind": "bill_of_lading",
        "reference": "GRIM0042",
        "carrier": "Grimaldi",
        "vessel": "GRANDE TEMA",
        "container": None,
        "port_of_loading": "JEBEL ALI",
        "port_of_discharge": "ALGIERS, ALGERIA",
        "departed_on": None,
        "eta": None,
        "vins": [VIN],
        "matches": True,
        "milestone": None,
        "paper": "bill_of_lading",
        "consignee": "SARL ATLAS AUTO.",
    }
    return ShippingProposal(**{**base, **over})


def test_a_draft_that_matches_the_order_is_clean() -> None:
    checks = check_draft(_proposal(), vin=VIN, consignee="Sarl Atlas Auto", port="Algiers")
    assert [(c.name, c.ok) for c in checks] == [("vin", True), ("consignee", True), ("port", True)]


def test_a_draft_for_another_company_or_chassis_is_flagged() -> None:
    checks = check_draft(
        _proposal(vins=["LGXCE4CB0T0009999"], matches=False, consignee="EURL Sahara Cars"),
        vin=VIN,
        consignee="SARL Atlas Auto",
        port="Algiers",
    )
    assert [(c.name, c.ok) for c in checks] == [
        ("vin", False),
        ("consignee", False),
        ("port", True),
    ]


def test_what_was_not_read_is_not_called_a_match() -> None:
    checks = check_draft(_proposal(consignee=None), vin=VIN, consignee="SARL Atlas Auto", port=None)
    assert [(c.name, c.ok) for c in checks] == [("vin", True), ("consignee", None), ("port", None)]


# --------------------------------------------------------------------------
# the API
# --------------------------------------------------------------------------

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


async def _setup() -> uuid.UUID:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "update tenants set document_settings = $2::jsonb where id = $1",
            TENANT_A,
            json.dumps({"legal_name": "Pollux Motors", "address": "DUCAMZ, Ras Al Khor, Dubai"}),
        )
        vehicle_id = uuid.uuid4()
        await conn.execute(
            """insert into vehicles (id, tenant_id, make, model, model_year, vin, price_minor,
                                     min_price_minor, status)
               values ($1, $2, 'BYD', 'Seal 06', 2026, $3, 5500000, 5000000, 'available')""",
            vehicle_id,
            TENANT_A,
            VIN,
        )
        return vehicle_id
    finally:
        await conn.close()


@pytest.fixture
def car(_migrated: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return asyncio.run(_setup())


@pytest.fixture
def client(car: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _reserved(client: TestClient, car: uuid.UUID, destination: str | None = "DZ") -> str:
    order = client.post(
        f"/v1/vehicles/{car}/orders",
        json={
            "buyer_name": "SARL Atlas Auto",
            "purchase_type": "export" if destination else "local",
            "destination": destination,
            "price_minor": 55_000 * AED,
            "deposit_minor": 5_000 * AED,
            "charges": [{"kind": "freight", "description": "RoRo", "amount_minor": 4_500 * AED}],
        },
        headers=auth(SALES_1),
    ).json()
    paid = client.post(
        f"/v1/orders/{order['id']}/payments",
        json={
            "stage": "deposit",
            "amount_minor": 5_000 * AED,
            "currency": "AED",
            "received_on": "2026-11-04",
        },
        headers=auth(MANAGER),
    )
    assert paid.json()["status"] == "reserved", paid.text
    return str(order["id"])


def _file(client: TestClient, order_id: str) -> dict[str, Any]:
    return dict(client.get(f"/v1/orders/{order_id}/export", headers=auth(SALES_1)).json())


def _pdf() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


def test_a_deposit_lays_out_the_destinations_procedure(client: TestClient, car: uuid.UUID) -> None:
    """The exit criterion's second half: the car shows which step it is on."""
    file = _file(client, _reserved(client, car))
    assert file["procedure"] == "DZ"
    assert [s["code"] for s in file["steps"]] == list(export.PROCEDURES["DZ"])
    assert file["stage"] == "customer_documents"


def test_a_local_sale_is_registered_and_handed_over(client: TestClient, car: uuid.UUID) -> None:
    file = _file(client, _reserved(client, car, destination=None))
    assert [s["code"] for s in file["steps"]] == list(export.PROCEDURES["local"])


def test_a_steps_paper_is_kept_and_given_back(client: TestClient, car: uuid.UUID) -> None:
    order_id = _reserved(client, car)
    url = f"/v1/orders/{order_id}/export/steps/export_certificate/document"
    after = client.post(
        url, files={"file": ("cert.jpg", _pdf(), "image/jpeg")}, headers=auth(SALES_1)
    )
    assert after.status_code == 200, after.text
    [step] = [s for s in after.json()["steps"] if s["code"] == "export_certificate"]
    assert (step["status"], step["has_document"]) == ("done", True)
    assert after.json()["stage"] == "bl_draft_confirmed", "the step after the furthest reached"

    download = client.get(url, headers=auth(SALES_1))
    assert download.status_code == 200
    assert download.content == _pdf()
    assert "export_certificate.jpg" in download.headers["content-disposition"]


def test_the_invoice_is_done_by_signing_it_and_the_file_last(
    client: TestClient, car: uuid.UUID
) -> None:
    order_id = _reserved(client, car)
    base = f"/v1/orders/{order_id}/export/steps"
    assert (
        client.post(
            f"{base}/commercial_invoice", json={"status": "done"}, headers=auth(SALES_1)
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{base}/file_delivered", json={"status": "done"}, headers=auth(SALES_1)
        ).status_code
        == 409
    )


def test_the_invoice_is_drafted_from_the_record_and_signed_once(
    client: TestClient, car: uuid.UUID
) -> None:
    order_id = _reserved(client, car)
    draft = client.get(f"/v1/orders/{order_id}/invoice", headers=auth(SALES_1)).json()
    assert draft["signed"] is False
    assert draft["document"]["total_minor"] == 59_500 * AED
    assert draft["document"]["vehicle"]["vin"] == VIN
    assert "the consignee is not recorded" in draft["problems"]
    sign = f"/v1/orders/{order_id}/invoice/sign"
    assert client.post(sign, headers=auth(MANAGER)).status_code == 409, "customs would stop it"

    client.patch(
        f"/v1/orders/{order_id}/export",
        json={
            "consignee_name": "SARL Atlas Auto",
            "consignee_address": "12 Rue Didouche Mourad, Algiers",
            "port_of_discharge": "Algiers",
            "shipping_method": "roro",
        },
        headers=auth(SALES_1),
    )
    assert client.post(sign, headers=auth(SALES_1)).status_code == 403, "a signature is a manager's"
    signed = client.post(sign, headers=auth(MANAGER))
    assert signed.status_code == 200, signed.text
    body = signed.json()
    assert body["document"]["number"] == f"INV-{date.today().year}-0001"
    assert body["signed_by"] is not None
    assert client.post(sign, headers=auth(MANAGER)).status_code == 409, "once"

    [step] = [s for s in _file(client, order_id)["steps"] if s["code"] == "commercial_invoice"]
    assert step["status"] == "done"
    moved = client.patch(
        f"/v1/orders/{order_id}/export",
        json={"consignee_name": "Somebody else"},
        headers=auth(SALES_1),
    )
    assert moved.status_code == 422, "a signed invoice keeps what it said"


def test_a_quote_has_no_invoice_to_sign(client: TestClient, car: uuid.UUID) -> None:
    order = client.post(
        f"/v1/vehicles/{car}/orders",
        json={
            "buyer_name": "Walk-in",
            "purchase_type": "local",
            "price_minor": 55_000 * AED,
            "deposit_minor": 0,
        },
        headers=auth(SALES_1),
    ).json()
    assert (
        client.post(f"/v1/orders/{order['id']}/invoice/sign", headers=auth(MANAGER)).status_code
        == 409
    )


def test_document_settings_are_the_owners(client: TestClient, car: uuid.UUID) -> None:
    assert client.get("/v1/settings/documents", headers=auth(MANAGER)).status_code == 403
    saved = client.put(
        "/v1/settings/documents",
        json={"legal_name": "Pollux Motors", "address": "DUCAMZ", "trn": "100000000000003"},
        headers=auth(OWNER),
    )
    assert saved.status_code == 200 and saved.json()["invoice_prefix"] == "INV"


# --------------------------------------------------------------------------
# the bill of lading draft, read
# --------------------------------------------------------------------------

READING: dict[str, Any] = {
    "kind": "bill_of_lading",
    "reference": "GRIM0042",
    "reference_quote": "B/L No. GRIM0042 (DRAFT)",
    "carrier": "Grimaldi",
    "shipper": "POLLUX MOTORS",
    "consignee": "SARL ATLAS AUTO",
    "port_of_loading": "JEBEL ALI",
    "port_of_discharge": "ALGIERS, ALGERIA",
    "vins": [{"vin": VIN, "quote": f"1 USED? NO - NEW BYD SEAL 06 VIN {VIN}"}],
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
                    prompt_token_count=1200, candidates_token_count=200, total_token_count=1400
                ),
            )

    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": Models()})()})()
    )
    return calls


def _consignee(client: TestClient, order_id: str) -> None:
    client.patch(
        f"/v1/orders/{order_id}/export",
        json={"consignee_name": "SARL Atlas Auto", "port_of_discharge": "Algiers"},
        headers=auth(SALES_1),
    )


def _check(client: TestClient, order_id: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/orders/{order_id}/export/bl-check",
        files={"file": ("draft.jpg", _pdf(), "image/jpeg")},
        headers=auth(SALES_1),
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_bl_draft_that_matches_is_clean_and_kept_unconfirmed(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    order_id = _reserved(client, car)
    _consignee(client, order_id)
    result = _check(client, order_id)
    assert result["clean"] is True
    assert [(c["name"], c["ok"]) for c in result["checks"]] == [
        ("vin", True),
        ("consignee", True),
        ("port", True),
    ]
    [step] = [s for s in _file(client, order_id)["steps"] if s["code"] == "bl_draft_confirmed"]
    assert step["has_document"] is True
    assert step["status"] == "pending", "the buyer confirms a draft, not the reader"


def test_a_bl_draft_for_another_consignee_is_flagged(
    client: TestClient, car: uuid.UUID, model: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(READING, "consignee", "EURL SAHARA CARS")
    order_id = _reserved(client, car)
    _consignee(client, order_id)
    result = _check(client, order_id)
    assert result["clean"] is False
    [consignee] = [c for c in result["checks"] if c["name"] == "consignee"]
    assert consignee == {
        "name": "consignee",
        "ok": False,
        "expected": "SARL Atlas Auto",
        "found": "EURL SAHARA CARS",
    }
