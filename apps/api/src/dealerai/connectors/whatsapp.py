"""WhatsApp Cloud API: the messaging connector for one WhatsApp number.

Everything Meta-shaped lives here so workers and routes speak only the small
messaging contract in base.py.
"""

from __future__ import annotations

from typing import Any

import httpx

from .base import (
    ConnectorError,
    MessageRequest,
    MessageResult,
    NotSupported,
    OutsideMessagingWindow,
    RateLimited,
    RequestRejected,
    TemplateInfo,
    TokenExpired,
)

GRAPH_URL = "https://graph.facebook.com"

_TOKEN_CODES = frozenset({190})
_RATE_LIMIT_CODES = frozenset({4, 80007, 130429, 131056})
_WINDOW_CODES = frozenset({131047})

_TEMPLATE_STATUSES = {
    "APPROVED": "approved",
    "REINSTATED": "approved",
    "FLAGGED": "approved",
    "PENDING": "pending",
    "IN_APPEAL": "pending",
    "REJECTED": "rejected",
    "PAUSED": "paused",
}
_TEMPLATE_CATEGORIES = {
    "MARKETING": "marketing",
    "UTILITY": "utility",
    "AUTHENTICATION": "authentication",
}


def template_status(raw: str | None) -> str:
    """Translate a Meta template status into our sendability vocabulary."""
    return _TEMPLATE_STATUSES.get((raw or "").upper(), "disabled")


def _template(raw: dict[str, Any]) -> TemplateInfo:
    reason = raw.get("rejected_reason")
    return TemplateInfo(
        external_id=str(raw["id"]),
        name=str(raw["name"]),
        language=str(raw["language"]),
        category=_TEMPLATE_CATEGORIES.get(str(raw.get("category", "")).upper(), "marketing"),
        status=template_status(raw.get("status")),
        components=list(raw.get("components") or []),
        rejected_reason=None if reason in (None, "", "NONE") else str(reason),
    )


def _retry_after(response: httpx.Response) -> int:
    value = response.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else 60


def _error(response: httpx.Response) -> ConnectorError:
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    error_data = error.get("error_data")
    details = error_data.get("details") if isinstance(error_data, dict) else None
    detail = str(details or error.get("message") or response.text[:300] or response.status_code)

    if code in _TOKEN_CODES or response.status_code == 401:
        return TokenExpired(detail)
    if code in _RATE_LIMIT_CODES or response.status_code == 429:
        return RateLimited(detail, retry_after_seconds=_retry_after(response))
    if code in _WINDOW_CODES:
        return OutsideMessagingWindow(detail)
    if response.status_code >= 500:
        return ConnectorError(detail)
    return RequestRejected(detail, code=str(code or response.status_code))


class WhatsAppCloud:
    platform = "whatsapp"
    enforces_messaging_window = True

    def __init__(
        self,
        *,
        phone_number_id: str,
        waba_id: str | None,
        access_token: str,
        graph_version: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._phone_number_id = phone_number_id
        self._waba_id = waba_id
        self._token = access_token
        self._base_url = f"{GRAPH_URL}/{graph_version}"
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=self._transport,
        )

    @staticmethod
    async def _call(
        client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise ConnectorError(f"could not reach the WhatsApp Cloud API: {exc}") from exc
        if not response.is_success:
            raise _error(response)
        return response

    async def send_message(self, req: MessageRequest) -> MessageResult:
        if not req.text and not req.template:
            raise NotSupported("a message needs either text or a template")

        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
        }
        recipient_field = "to" if req.recipient_external_id.startswith("+") else "recipient"
        body[recipient_field] = req.recipient_external_id

        if req.template:
            if not req.template_language:
                raise NotSupported("a template send needs the template's language code")
            template: dict[str, Any] = {
                "name": req.template,
                "language": {"code": req.template_language},
            }
            if req.template_params:
                ordered = [req.template_params[k] for k in sorted(req.template_params, key=int)]
                template["components"] = [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": value} for value in ordered],
                    }
                ]
            body |= {"type": "template", "template": template}
        else:
            body |= {"type": "text", "text": {"body": req.text, "preview_url": False}}

        async with self._client() as client:
            response = await self._call(
                client, "POST", f"/{self._phone_number_id}/messages", json=body
            )
        return MessageResult(external_id=str(response.json()["messages"][0]["id"]))

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        async with self._client() as client:
            meta = (await self._call(client, "GET", f"/{media_id}")).json()
            file = await self._call(client, "GET", str(meta["url"]))
        mime = meta.get("mime_type") or file.headers.get("Content-Type", "application/octet-stream")
        return file.content, str(mime)

    async def list_templates(self) -> list[TemplateInfo]:
        if not self._waba_id:
            raise NotSupported("listing templates needs the WhatsApp Business Account id")
        url: str | None = f"/{self._waba_id}/message_templates"
        params: dict[str, str] | None = {
            "fields": "id,name,language,category,status,components,rejected_reason",
            "limit": "100",
        }
        templates: list[TemplateInfo] = []
        async with self._client() as client:
            while url:
                page = (await self._call(client, "GET", url, params=params)).json()
                templates += [_template(raw) for raw in page.get("data", [])]
                url = (page.get("paging") or {}).get("next")
                params = None
        return templates
