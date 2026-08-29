"""The suite every connector must pass, unmodified.

Meta and WhatsApp are written against this in M4. If a real connector needs
this file changed to go green, the change belongs in the connector — that is the
whole point of having one contract instead of per-platform expectations
scattered through the agents.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from dealerai.connectors.base import (
    ConnectorHealth,
    Insights,
    MediaAsset,
    MessageRequest,
    NotSupported,
    OutsideMessagingWindow,
    PublishRequest,
    RateLimited,
    SocialConnector,
    TokenExpired,
)
from dealerai.connectors.mock import MockConnector, instagram_like, whatsapp_like

#: M4 appends the real connectors here, each with credentials from a fixture.
FACTORIES: list[tuple[str, Callable[[], SocialConnector]]] = [
    ("mock", MockConnector),
    ("mock_instagram", instagram_like),
    ("mock_whatsapp", whatsapp_like),
]


@pytest.fixture(params=[f for _, f in FACTORIES], ids=[n for n, _ in FACTORIES])
def connector(request: pytest.FixtureRequest) -> SocialConnector:
    return request.param()  # type: ignore[no-any-return]


def a_post(key: str = "idem-1") -> PublishRequest:
    return PublishRequest(
        kind="post",
        assets=[MediaAsset(url="https://cdn.test/car.jpg", mime="image/jpeg")],
        caption="MG6 XLINE Trophy — AED 66,000",
        idempotency_key=key,
    )


# --------------------------------------------------------------------------
# shape
# --------------------------------------------------------------------------


def test_declares_its_identity_and_capabilities(connector: SocialConnector) -> None:
    assert connector.platform
    assert isinstance(connector.supports, frozenset)
    assert isinstance(connector.enforces_messaging_window, bool)


def test_satisfies_the_protocol(connector: SocialConnector) -> None:
    assert isinstance(connector, SocialConnector)


async def test_health_always_answers(connector: SocialConnector) -> None:
    """Health must never raise — a broken channel cannot take the API down."""
    health = await connector.health()
    assert isinstance(health, ConnectorHealth)
    assert health.checked_at.tzinfo is not None


# --------------------------------------------------------------------------
# publishing
# --------------------------------------------------------------------------


async def test_publish_returns_an_external_id(connector: SocialConnector) -> None:
    if "post" not in connector.supports:
        pytest.skip(f"{connector.platform} does not publish posts")
    result = await connector.publish(a_post())
    assert result.external_id


async def test_publish_is_idempotent(connector: SocialConnector) -> None:
    """A retried worker must not post the same car twice in public."""
    if "post" not in connector.supports:
        pytest.skip(f"{connector.platform} does not publish posts")
    first = await connector.publish(a_post("same-key"))
    second = await connector.publish(a_post("same-key"))
    assert first.external_id == second.external_id


async def test_different_keys_publish_separately(connector: SocialConnector) -> None:
    if "post" not in connector.supports:
        pytest.skip(f"{connector.platform} does not publish posts")
    first = await connector.publish(a_post("key-a"))
    second = await connector.publish(a_post("key-b"))
    assert first.external_id != second.external_id


async def test_unsupported_kind_raises_not_supported(connector: SocialConnector) -> None:
    """Callers branch on the type; they never carry a capability table."""
    unsupported = next(
        (k for k in ("post", "story", "reel", "carousel") if k not in connector.supports),
        None,
    )
    if unsupported is None:
        pytest.skip(f"{connector.platform} supports everything")
    req = PublishRequest(
        kind=unsupported,  # type: ignore[arg-type]
        assets=[MediaAsset(url="https://cdn.test/x.jpg", mime="image/jpeg")],
        caption="x",
        idempotency_key="unsupported",
    )
    with pytest.raises(NotSupported):
        await connector.publish(req)


async def test_publish_without_assets_is_rejected(connector: SocialConnector) -> None:
    if "post" not in connector.supports:
        pytest.skip(f"{connector.platform} does not publish posts")
    req = PublishRequest(kind="post", assets=[], caption="c", idempotency_key="empty")
    with pytest.raises(NotSupported):
        await connector.publish(req)


# --------------------------------------------------------------------------
# comments
# --------------------------------------------------------------------------


async def test_fetch_comments_respects_since_and_order(connector: SocialConnector) -> None:
    now = datetime.now(UTC)
    if isinstance(connector, MockConnector):
        connector.seed_comment("old one", created_at=now - timedelta(days=2))
        connector.seed_comment("newer", created_at=now - timedelta(minutes=5))
        connector.seed_comment("newest", created_at=now - timedelta(minutes=1))

    comments = await connector.fetch_comments(since=now - timedelta(hours=1))
    assert all(c.created_at >= now - timedelta(hours=1) for c in comments)
    assert comments == sorted(comments, key=lambda c: c.created_at)


async def test_reply_comment_returns_an_id(connector: SocialConnector) -> None:
    result = await connector.reply_comment("cmt_1", "Sent you the details in DM.")
    assert result.external_id


# --------------------------------------------------------------------------
# messaging
# --------------------------------------------------------------------------


async def test_send_message_returns_an_id(connector: SocialConnector) -> None:
    result = await connector.send_message(
        MessageRequest(recipient_external_id="cust_1", text="Hello", idempotency_key="m1")
    )
    assert result.external_id


async def test_send_message_is_idempotent(connector: SocialConnector) -> None:
    """Sending a customer the same message twice is the retry bug that gets you blocked."""
    req = MessageRequest(recipient_external_id="cust_1", text="Hi", idempotency_key="dupe")
    first = await connector.send_message(req)
    second = await connector.send_message(req)
    assert first.external_id == second.external_id
    if isinstance(connector, MockConnector):
        assert len(connector.sent) == 1


async def test_empty_message_is_rejected(connector: SocialConnector) -> None:
    with pytest.raises(NotSupported):
        await connector.send_message(
            MessageRequest(recipient_external_id="cust_1", idempotency_key="empty-msg")
        )


async def test_closed_window_rejects_free_form_but_allows_a_template(
    connector: SocialConnector,
) -> None:
    """WhatsApp's 24-hour rule, as a typed error the Follow-up Agent branches on."""
    if not connector.enforces_messaging_window:
        pytest.skip(f"{connector.platform} has no messaging window")
    assert isinstance(connector, MockConnector)
    connector.window_open = False

    with pytest.raises(OutsideMessagingWindow):
        await connector.send_message(
            MessageRequest(recipient_external_id="c", text="hi", idempotency_key="ff")
        )

    result = await connector.send_message(
        MessageRequest(
            recipient_external_id="c",
            template="price_drop",
            template_params={"model": "MG6"},
            idempotency_key="tmpl",
        )
    )
    assert result.external_id


# --------------------------------------------------------------------------
# insights
# --------------------------------------------------------------------------


async def test_insights_are_non_negative_and_stable(connector: SocialConnector) -> None:
    first = await connector.get_insights("media_1", "24h")
    second = await connector.get_insights("media_1", "24h")
    assert isinstance(first, Insights)
    assert first.impressions >= 0
    assert first.reach >= 0
    assert first == second, "insights for the same media and window must not drift"


# --------------------------------------------------------------------------
# failure vocabulary
# --------------------------------------------------------------------------


async def test_rate_limit_surfaces_with_a_retry_hint(connector: SocialConnector) -> None:
    if not isinstance(connector, MockConnector):
        pytest.skip("failure injection is a mock capability")
    connector.fail_next = RateLimited("slow down", retry_after_seconds=90)
    with pytest.raises(RateLimited) as exc:
        await connector.get_insights("media_1", "24h")
    assert exc.value.retry_after_seconds == 90


async def test_expired_token_is_its_own_type(connector: SocialConnector) -> None:
    """Not retryable: a human has to reconnect the channel, so the worker must
    be able to tell this apart from a transient failure."""
    if not isinstance(connector, MockConnector):
        pytest.skip("failure injection is a mock capability")
    connector.fail_next = TokenExpired("reconnect required")
    with pytest.raises(TokenExpired):
        await connector.get_insights("media_1", "24h")


async def test_injected_failure_clears_after_one_call(connector: SocialConnector) -> None:
    if not isinstance(connector, MockConnector):
        pytest.skip("failure injection is a mock capability")
    connector.fail_next = RateLimited("once")
    with pytest.raises(RateLimited):
        await connector.get_insights("m", "24h")
    assert (await connector.get_insights("m", "24h")).impressions >= 0
