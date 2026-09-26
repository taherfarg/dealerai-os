"""A fake Graph API that answers like Meta, for the WhatsApp connector's tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from dealerai.connectors.base import TemplateInfo

VERSION = "v25.0"
PHONE_NUMBER_ID = "106540352242922"
WABA_ID = "102290129340398"
TOKEN = "EAAG-test-token"


def _error(status: int, code: int, message: str, **extra: Any) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {
                "message": message,
                "type": "OAuthException",
                "code": code,
                "fbtrace_id": "AbCdEfGh",
                **extra,
            }
        },
    )


@dataclass
class FakeGraph:
    window_open: bool = True
    token_valid: bool = True
    rate_limited_for: int | None = None
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    templates: list[dict[str, Any]] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.token_valid or request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return _error(401, 190, "Error validating access token: Session has expired.")
        if self.rate_limited_for is not None:
            response = _error(400, 130429, "Rate limit hit")
            response.headers["Retry-After"] = str(self.rate_limited_for)
            return response

        if request.url.host == "lookaside.fbsbx.com":
            data, mime = self.media[request.url.params["mid"]]
            return httpx.Response(200, content=data, headers={"Content-Type": mime})

        path = request.url.path
        if request.method == "POST" and path == f"/{VERSION}/{PHONE_NUMBER_ID}/messages":
            body = json.loads(request.content)
            self.sent.append(body)
            if body["type"] != "template" and not self.window_open:
                return _error(
                    400,
                    131047,
                    "Re-engagement message",
                    error_data={
                        "details": "Message failed to send because more than 24 hours "
                        "have passed since the customer last replied."
                    },
                )
            recipient = body.get("to") or body.get("recipient")
            return httpx.Response(
                200,
                json={
                    "messaging_product": "whatsapp",
                    "contacts": [{"input": recipient, "wa_id": recipient}],
                    "messages": [{"id": f"wamid.FAKE{len(self.sent)}"}],
                },
            )

        if request.method == "GET" and path == f"/{VERSION}/{WABA_ID}/message_templates":
            index = int(request.url.params.get("after", "0"))
            page: dict[str, Any] = {"data": self.templates[index : index + 1]}
            if index + 1 < len(self.templates):
                page["paging"] = {
                    "next": f"https://graph.facebook.com/{VERSION}/{WABA_ID}"
                    f"/message_templates?after={index + 1}"
                }
            return httpx.Response(200, json=page)

        media_id = path.rsplit("/", 1)[-1]
        if request.method == "GET" and media_id in self.media:
            data, mime = self.media[media_id]
            return httpx.Response(
                200,
                json={
                    "url": f"https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid={media_id}",
                    "mime_type": mime,
                    "sha256": "0" * 64,
                    "file_size": len(data),
                    "id": media_id,
                    "messaging_product": "whatsapp",
                },
            )

        return _error(400, 100, "Unsupported get request. Object with ID does not exist.")


@dataclass
class CloudControls:
    graph: FakeGraph

    def close_window(self) -> None:
        self.graph.window_open = False

    def expire_token(self) -> None:
        self.graph.token_valid = False

    def rate_limit(self, retry_after_seconds: int) -> None:
        self.graph.rate_limited_for = retry_after_seconds

    def add_media(self, media_id: str, data: bytes, mime: str) -> None:
        self.graph.media[media_id] = (data, mime)

    def add_template(self, template: TemplateInfo) -> None:
        self.graph.templates.append(
            {
                "id": template.external_id,
                "name": template.name,
                "language": template.language,
                "category": template.category.upper(),
                "status": template.status.upper(),
                "components": template.components,
            }
        )
