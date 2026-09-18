"""A complete, deterministic implementation of the connector contract.

This is infrastructure, not a test fixture. Meta and WhatsApp app review takes
weeks and is outside our control, so M1 through M4 are built and demoed against
this — review runs in parallel instead of blocking the launch.

It is deliberately unforgiving: it enforces idempotency, capability limits, and
the messaging window, so code written against it does not fall over the first
time it meets the real platform.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .base import (
    ConnectorHealth,
    InboundComment,
    Insights,
    InsightWindow,
    MessageRequest,
    MessageResult,
    NotSupported,
    OutsideMessagingWindow,
    PublishKind,
    PublishRequest,
    PublishResult,
    RequestRejected,
    TemplateInfo,
)

ALL_KINDS: frozenset[PublishKind] = frozenset({"post", "story", "reel", "carousel"})


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


@dataclass
class MockConnector:
    platform: str = "mock"
    supports: frozenset[PublishKind] = ALL_KINDS
    enforces_messaging_window: bool = False

    #: Raised on the next call of any kind, then cleared. Lets a test drive the
    #: retry path without patching internals.
    fail_next: Exception | None = None
    #: Free-form outbound allowed? Only consulted when enforces_messaging_window.
    window_open: bool = True
    healthy: bool = True

    published: dict[str, PublishResult] = field(default_factory=dict)
    sent: list[MessageRequest] = field(default_factory=list)
    replies: list[tuple[str, str]] = field(default_factory=list)
    comments: list[InboundComment] = field(default_factory=list)
    #: media id -> (bytes, mime), for download_media.
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    templates: list[TemplateInfo] = field(default_factory=list)

    # ---- test seams -----------------------------------------------------

    def seed_comment(
        self,
        text: str,
        *,
        author: str = "cust_1",
        created_at: datetime | None = None,
        media_external_id: str | None = None,
    ) -> InboundComment:
        comment = InboundComment(
            external_id=_stable_id("cmt", text, author),
            author_external_id=author,
            text=text,
            created_at=created_at or datetime.now(UTC),
            media_external_id=media_external_id,
        )
        self.comments.append(comment)
        return comment

    def _maybe_fail(self) -> None:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error

    # ---- the contract ---------------------------------------------------

    async def publish(self, req: PublishRequest) -> PublishResult:
        self._maybe_fail()
        if req.kind not in self.supports:
            raise NotSupported(f"{self.platform} cannot publish {req.kind}")
        if not req.assets:
            raise NotSupported("publish requires at least one asset")

        # Replaying an idempotency key returns the original result and does not
        # publish again — a retried worker must not post twice.
        if req.idempotency_key in self.published:
            return self.published[req.idempotency_key]

        external_id = _stable_id("pub", self.platform, req.idempotency_key)
        result = PublishResult(
            external_id=external_id,
            permalink=f"https://{self.platform}.test/p/{external_id}",
        )
        self.published[req.idempotency_key] = result
        return result

    async def fetch_comments(self, *, since: datetime, limit: int = 50) -> list[InboundComment]:
        self._maybe_fail()
        fresh = [c for c in self.comments if c.created_at >= since]
        fresh.sort(key=lambda c: c.created_at)
        return fresh[:limit]

    async def reply_comment(self, comment_external_id: str, text: str) -> MessageResult:
        self._maybe_fail()
        self.replies.append((comment_external_id, text))
        return MessageResult(external_id=_stable_id("rpl", comment_external_id, text))

    async def send_message(self, req: MessageRequest) -> MessageResult:
        self._maybe_fail()
        if self.enforces_messaging_window and not self.window_open and not req.template:
            raise OutsideMessagingWindow(
                "free-form messaging window has closed; send an approved template"
            )
        if not req.text and not req.template:
            raise NotSupported("a message needs either text or a template")

        for prior in self.sent:
            if prior.idempotency_key == req.idempotency_key:
                return MessageResult(
                    external_id=_stable_id("msg", self.platform, req.idempotency_key)
                )
        self.sent.append(req)
        return MessageResult(external_id=_stable_id("msg", self.platform, req.idempotency_key))

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        self._maybe_fail()
        if media_id not in self.media:
            raise RequestRejected(f"no media with id {media_id!r}", code="100")
        return self.media[media_id]

    async def list_templates(self) -> list[TemplateInfo]:
        self._maybe_fail()
        return list(self.templates)

    async def get_insights(self, media_external_id: str, window: InsightWindow) -> Insights:
        self._maybe_fail()
        # Derived from the id so the same media always reports the same numbers
        # — a flaky analytics assertion is worse than a boring one.
        seed = int(hashlib.sha256(f"{media_external_id}{window}".encode()).hexdigest()[:8], 16)
        impressions = seed % 10_000
        return Insights(
            impressions=impressions,
            reach=int(impressions * 0.8),
            likes=impressions // 20,
            comments=impressions // 200,
            shares=impressions // 400,
            saves=impressions // 100,
            raw={"source": "mock", "window": window},
        )

    async def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            ok=self.healthy,
            checked_at=datetime.now(UTC),
            detail="mock" if self.healthy else "mock connector marked unhealthy",
        )


def whatsapp_like() -> MockConnector:
    """A mock shaped like WhatsApp: messaging only, with the 24-hour window."""
    return MockConnector(
        platform="mock_whatsapp",
        supports=frozenset(),
        enforces_messaging_window=True,
    )


def instagram_like() -> MockConnector:
    """A mock shaped like Instagram: no plain video-only kinds it cannot take."""
    return MockConnector(
        platform="mock_instagram",
        supports=frozenset({"post", "story", "reel", "carousel"}),
    )
