"""The suite every messaging connector passes, unmodified."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import pytest

from dealerai.connectors.base import (
    MessageRequest,
    MessagingConnector,
    NotSupported,
    OutsideMessagingWindow,
    RateLimited,
    RequestRejected,
    TemplateInfo,
    TokenExpired,
)
from dealerai.connectors.mock import MockConnector, whatsapp_like


class Controls(Protocol):
    def close_window(self) -> None: ...
    def expire_token(self) -> None: ...
    def rate_limit(self, retry_after_seconds: int) -> None: ...
    def add_media(self, media_id: str, data: bytes, mime: str) -> None: ...
    def add_template(self, template: TemplateInfo) -> None: ...


@dataclass
class MockControls:
    mock: MockConnector

    def close_window(self) -> None:
        self.mock.window_open = False

    def expire_token(self) -> None:
        self.mock.fail_next = TokenExpired("reconnect required")

    def rate_limit(self, retry_after_seconds: int) -> None:
        self.mock.fail_next = RateLimited("slow down", retry_after_seconds=retry_after_seconds)

    def add_media(self, media_id: str, data: bytes, mime: str) -> None:
        self.mock.media[media_id] = (data, mime)

    def add_template(self, template: TemplateInfo) -> None:
        self.mock.templates.append(template)


def _mock() -> tuple[MessagingConnector, Controls]:
    mock = whatsapp_like()
    return mock, MockControls(mock)


FACTORIES: list[tuple[str, Callable[[], tuple[MessagingConnector, Controls]]]] = [
    ("mock_whatsapp", _mock),
]

Pair = tuple[MessagingConnector, Controls]

TEMPLATE = TemplateInfo(
    external_id="1234567890",
    name="vehicle_available",
    language="en",
    category="utility",
    status="approved",
    components=[{"type": "BODY", "text": "Hi {{1}}, the {{2}} is available."}],
)


@pytest.fixture(params=[f for _, f in FACTORIES], ids=[n for n, _ in FACTORIES])
def pair(request: pytest.FixtureRequest) -> Pair:
    return request.param()  # type: ignore[no-any-return]


def a_text(recipient: str = "+971500000101", body: str | None = "Hello") -> MessageRequest:
    return MessageRequest(recipient_external_id=recipient, idempotency_key="m-1", text=body)


def a_template() -> MessageRequest:
    return MessageRequest(
        recipient_external_id="+971500000101",
        idempotency_key="t-1",
        template="vehicle_available",
        template_language="en",
        template_params={"1": "Karim", "2": "Hilux GR Sport"},
    )


def test_satisfies_the_protocol(pair: Pair) -> None:
    connector, _ = pair
    assert isinstance(connector, MessagingConnector)
    assert connector.platform
    assert connector.enforces_messaging_window is True


async def test_a_text_returns_an_external_id(pair: Pair) -> None:
    connector, _ = pair
    assert (await connector.send_message(a_text())).external_id


async def test_a_business_scoped_user_id_is_a_valid_recipient(pair: Pair) -> None:
    connector, _ = pair
    result = await connector.send_message(a_text(recipient="AE.13491208655302741918"))
    assert result.external_id


async def test_an_empty_message_is_rejected_before_sending(pair: Pair) -> None:
    connector, _ = pair
    with pytest.raises(NotSupported):
        await connector.send_message(a_text(body=None))


async def test_a_closed_window_refuses_free_form_but_not_a_template(pair: Pair) -> None:
    connector, controls = pair
    controls.close_window()
    with pytest.raises(OutsideMessagingWindow):
        await connector.send_message(a_text())
    assert (await connector.send_message(a_template())).external_id


async def test_media_downloads_as_bytes_and_type(pair: Pair) -> None:
    connector, controls = pair
    controls.add_media("media-1", b"OggS voice", "audio/ogg")
    assert await connector.download_media("media-1") == (b"OggS voice", "audio/ogg")


async def test_unknown_media_is_rejected_not_retried(pair: Pair) -> None:
    connector, _ = pair
    with pytest.raises(RequestRejected):
        await connector.download_media("no-such-media")


async def test_templates_are_listed_in_our_vocabulary(pair: Pair) -> None:
    connector, controls = pair
    controls.add_template(TEMPLATE)
    [listed] = await connector.list_templates()
    assert (listed.name, listed.language, listed.category, listed.status) == (
        "vehicle_available",
        "en",
        "utility",
        "approved",
    )
    assert listed.components == TEMPLATE.components


async def test_an_expired_token_is_its_own_type(pair: Pair) -> None:
    connector, controls = pair
    controls.expire_token()
    with pytest.raises(TokenExpired):
        await connector.send_message(a_text())


async def test_a_rate_limit_carries_a_retry_hint(pair: Pair) -> None:
    connector, controls = pair
    controls.rate_limit(90)
    with pytest.raises(RateLimited) as exc:
        await connector.send_message(a_text())
    assert exc.value.retry_after_seconds == 90
