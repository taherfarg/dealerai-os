"""The capability interface every platform hides behind.

Agents call tools; tools call connectors. An agent must never learn that
Instagram needs a container-then-publish two-step, or that WhatsApp has a
24-hour service window. It says `publish` and `send_message`.

Everything here is a protocol or a plain dataclass — no HTTP, no SDK imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from ..core.errors import AppError

PublishKind = Literal["post", "story", "reel", "carousel"]
InsightWindow = Literal["1h", "24h", "7d", "30d", "lifetime"]


# --------------------------------------------------------------------------
# errors — the contract's failure vocabulary
#
# Every connector maps its platform's errors onto these. Callers branch on the
# type, never on a message string, so a Meta error-code change cannot silently
# turn a retryable rate limit into a permanent failure.
# --------------------------------------------------------------------------


class ConnectorError(AppError):
    status = 503
    slug = "connector-error"
    title = "Platform request failed"


class RateLimited(ConnectorError):
    status = 429
    slug = "rate-limited"
    title = "Platform rate limit reached"

    def __init__(self, detail: str | None = None, *, retry_after_seconds: int = 60) -> None:
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds


class TokenExpired(ConnectorError):
    """Not retryable by the worker — a human must reconnect the channel."""

    status = 401
    slug = "token-expired"
    title = "Channel credentials expired"


class NotSupported(ConnectorError):
    """The platform cannot do this at all. Never retry."""

    status = 422
    slug = "not-supported"
    title = "Unsupported on this platform"


class OutsideMessagingWindow(ConnectorError):
    """WhatsApp's 24-hour service window, and its equivalents.

    Outside it, only a pre-approved template may be sent. Surfaced as its own
    type because the Follow-up Agent has to branch on exactly this.
    """

    status = 422
    slug = "outside-messaging-window"
    title = "Free-form messaging window has closed"


# --------------------------------------------------------------------------
# DTOs
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MediaAsset:
    url: str
    mime: str
    aspect_ratio: str = "4:5"
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class PublishRequest:
    kind: PublishKind
    assets: list[MediaAsset]
    caption: str
    #: Required. Publishing twice because a worker retried is a public,
    #: customer-visible mistake, so idempotency is part of the contract rather
    #: than each connector's problem.
    idempotency_key: str
    first_comment: str | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    external_id: str
    permalink: str | None = None


@dataclass(frozen=True, slots=True)
class InboundComment:
    external_id: str
    author_external_id: str
    text: str
    created_at: datetime
    media_external_id: str | None = None
    parent_external_id: str | None = None
    author_name: str | None = None


@dataclass(frozen=True, slots=True)
class MessageRequest:
    recipient_external_id: str
    idempotency_key: str
    text: str | None = None
    #: Name of a pre-approved template. Required outside the messaging window.
    template: str | None = None
    template_params: dict[str, str] = field(default_factory=dict)
    thread_external_id: str | None = None


@dataclass(frozen=True, slots=True)
class MessageResult:
    external_id: str


@dataclass(frozen=True, slots=True)
class Insights:
    impressions: int = 0
    reach: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    video_views: int = 0
    watch_time_ms: int = 0
    profile_visits: int = 0
    link_clicks: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    ok: bool
    checked_at: datetime
    detail: str = ""


# --------------------------------------------------------------------------
# the protocol
# --------------------------------------------------------------------------


@runtime_checkable
class SocialConnector(Protocol):
    platform: str
    #: What this platform can publish. `publish` raises NotSupported otherwise,
    #: so callers never need a per-platform capability table of their own.
    supports: frozenset[PublishKind]
    #: True where free-form outbound closes after a window and only approved
    #: templates get through (WhatsApp, and Instagram messaging in practice).
    enforces_messaging_window: bool

    async def publish(self, req: PublishRequest) -> PublishResult: ...

    async def fetch_comments(self, *, since: datetime, limit: int = 50) -> list[InboundComment]: ...

    async def reply_comment(self, comment_external_id: str, text: str) -> MessageResult: ...

    async def send_message(self, req: MessageRequest) -> MessageResult: ...

    async def get_insights(self, media_external_id: str, window: InsightWindow) -> Insights: ...

    async def health(self) -> ConnectorHealth: ...
