"""What only the Cloud API client can get wrong: Meta's request shapes and error codes."""

from __future__ import annotations

import json

import httpx
import pytest
from fake_graph import PHONE_NUMBER_ID, TOKEN, WABA_ID, FakeGraph

from dealerai.connectors.base import (
    ConnectorError,
    MessageRequest,
    NotSupported,
    OutsideMessagingWindow,
    RequestRejected,
)
from dealerai.connectors.whatsapp import WhatsAppCloud, template_status


def _connector(graph: FakeGraph | httpx.MockTransport) -> WhatsAppCloud:
    transport = graph if isinstance(graph, httpx.MockTransport) else httpx.MockTransport(graph)
    return WhatsAppCloud(
        phone_number_id=PHONE_NUMBER_ID,
        waba_id=WABA_ID,
        access_token=TOKEN,
        graph_version="v25.0",
        transport=transport,
    )


async def test_a_text_has_meta_s_shape() -> None:
    graph = FakeGraph()
    await _connector(graph).send_message(
        MessageRequest(recipient_external_id="+971500000101", idempotency_key="k", text="Hello")
    )
    assert graph.sent == [
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": "+971500000101",
            "type": "text",
            "text": {"body": "Hello", "preview_url": False},
        }
    ]
    assert graph.requests[0].url.path == f"/v25.0/{PHONE_NUMBER_ID}/messages"


async def test_a_business_scoped_user_id_goes_in_recipient() -> None:
    graph = FakeGraph()
    await _connector(graph).send_message(
        MessageRequest(recipient_external_id="AE.1349120865530274", idempotency_key="k", text="Hi")
    )
    assert graph.sent[0]["recipient"] == "AE.1349120865530274"
    assert "to" not in graph.sent[0]


async def test_template_parameters_are_sent_in_numeric_order() -> None:
    graph = FakeGraph()
    params = {str(n): f"value {n}" for n in (10, 2, 1, 3, 4, 5, 6, 7, 8, 9)}
    await _connector(graph).send_message(
        MessageRequest(
            recipient_external_id="+971500000101",
            idempotency_key="k",
            template="price_update",
            template_language="en_US",
            template_params=params,
        )
    )
    template = graph.sent[0]["template"]
    assert template["name"] == "price_update"
    assert template["language"] == {"code": "en_US"}
    [body] = template["components"]
    assert [p["text"] for p in body["parameters"]] == [f"value {n}" for n in range(1, 11)]


async def test_a_template_without_its_language_is_refused() -> None:
    with pytest.raises(NotSupported):
        await _connector(FakeGraph()).send_message(
            MessageRequest(
                recipient_external_id="+971500000101",
                idempotency_key="k",
                template="price_update",
            )
        )


async def test_meta_s_explanation_reaches_the_error() -> None:
    graph = FakeGraph(window_open=False)
    with pytest.raises(OutsideMessagingWindow) as exc:
        await _connector(graph).send_message(
            MessageRequest(recipient_external_id="+971500000101", idempotency_key="k", text="Hi")
        )
    assert "24 hours" in str(exc.value.detail)


async def test_a_rejection_keeps_meta_s_code() -> None:
    with pytest.raises(RequestRejected) as exc:
        await _connector(FakeGraph()).download_media("missing")
    assert exc.value.code == "100"


async def test_server_errors_and_network_failures_are_not_rejections() -> None:
    server_error = httpx.MockTransport(lambda _: httpx.Response(500, text="oops"))
    with pytest.raises(ConnectorError) as exc:
        await _connector(server_error).download_media("m")
    assert type(exc.value) is ConnectorError

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ConnectorError) as exc:
        await _connector(httpx.MockTransport(unreachable)).send_message(
            MessageRequest(recipient_external_id="+971500000101", idempotency_key="k", text="Hi")
        )
    assert type(exc.value) is ConnectorError


async def test_media_download_sends_the_token_to_the_file_host_too() -> None:
    graph = FakeGraph(media={"media-1": (b"OggS", "audio/ogg")})
    assert await _connector(graph).download_media("media-1") == (b"OggS", "audio/ogg")
    file_request = graph.requests[-1]
    assert file_request.url.host == "lookaside.fbsbx.com"
    assert file_request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_templates_follow_pagination_in_our_vocabulary() -> None:
    graph = FakeGraph(
        templates=[
            {
                "id": "1",
                "name": "vehicle_available",
                "language": "en_US",
                "category": "UTILITY",
                "status": "APPROVED",
                "components": [{"type": "BODY", "text": "Hi {{1}}"}],
            },
            {
                "id": "2",
                "name": "new_arrivals",
                "language": "ar",
                "category": "MARKETING",
                "status": "REJECTED",
                "rejected_reason": "INVALID_FORMAT",
                "components": [],
            },
        ]
    )
    first, second = await _connector(graph).list_templates()
    assert (first.name, first.language, first.category, first.status, first.rejected_reason) == (
        "vehicle_available",
        "en_US",
        "utility",
        "approved",
        None,
    )
    assert (second.category, second.status, second.rejected_reason) == (
        "marketing",
        "rejected",
        "INVALID_FORMAT",
    )
    assert len(graph.requests) == 2
    assert json.loads(json.dumps(first.components)) == [{"type": "BODY", "text": "Hi {{1}}"}]


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("APPROVED", "approved"),
        ("REINSTATED", "approved"),
        ("IN_APPEAL", "pending"),
        ("REJECTED", "rejected"),
        ("PAUSED", "paused"),
        ("DISABLED", "disabled"),
        ("PENDING_DELETION", "disabled"),
        (None, "disabled"),
    ],
)
def test_template_status_in_our_vocabulary(event: str | None, expected: str) -> None:
    assert template_status(event) == expected
