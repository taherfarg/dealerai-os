"""Web Push, checked against the standards rather than against itself."""

from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from dealerai.notifications import push

# RFC 8291, Appendix A — every value as printed there.
PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
AUTH_SECRET = "BTBZMqHH6r4Tts7J_aSIgg"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
HEADER = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
CIPHERTEXT = "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"
# RFC 8291, Section 5 — the whole message as it goes on the wire.
MESSAGE = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
    "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)


def test_the_rfcs_own_example_comes_out_byte_for_byte() -> None:
    body = push.encrypt(
        PLAINTEXT,
        p256dh=UA_PUBLIC,
        auth=AUTH_SECRET,
        salt=push.unb64(SALT),
        server_key=push.private_key(AS_PRIVATE),
    )
    assert body == push.unb64(HEADER) + push.unb64(CIPHERTEXT)
    assert push.b64(body) == MESSAGE


def test_two_messages_to_one_device_share_nothing() -> None:
    """A fresh key and salt each time: the same words never look the same twice."""
    first = push.encrypt(PLAINTEXT, p256dh=UA_PUBLIC, auth=AUTH_SECRET)
    second = push.encrypt(PLAINTEXT, p256dh=UA_PUBLIC, auth=AUTH_SECRET)
    assert first[:16] != second[:16] and first[21:86] != second[21:86]


def test_the_request_is_signed_for_the_push_service_it_goes_to() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    scalar = push.b64(key.private_numbers().private_value.to_bytes(32, "big"))
    header = push.vapid(
        "https://fcm.googleapis.com/fcm/send/abc", private=scalar, subject="mailto:ops@pollux.test"
    )
    scheme, _, rest = header.partition(" ")
    fields = dict(part.strip().split("=", 1) for part in rest.split(","))
    assert scheme == "vapid" and fields["k"] == push.public_key(scalar)
    claims = jwt.decode(
        fields["t"], key.public_key(), algorithms=["ES256"], audience="https://fcm.googleapis.com"
    )
    assert claims["sub"] == "mailto:ops@pollux.test"
    assert 0 < claims["exp"] - claims["iat"] <= 24 * 3600, "push services refuse a longer one"


def test_a_long_notification_still_fits_the_one_record() -> None:
    payload = push.message("ع" * 500, "ب" * 5000, href="/pollux-motors/inbox/x", tag="assigned")
    assert len(push.encrypt(payload, p256dh=UA_PUBLIC, auth=AUTH_SECRET)) <= push.RECORD_SIZE


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
    ],
)
def test_the_push_services_browsers_use_are_accepted(endpoint: str) -> None:
    assert push.is_push_service(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://localhost:8000/v1/tenants",
        "https://10.0.0.5/internal",
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com.evil.example/abc",
        "https://evilfcm.googleapis.com.example/abc",
        "https://fcm.googleapis.com@evil.example/abc",
        "not a url",
    ],
)
def test_nobody_aims_the_worker_at_a_host_of_their_choosing(endpoint: str) -> None:
    assert not push.is_push_service(endpoint)
