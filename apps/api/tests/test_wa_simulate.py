from __future__ import annotations

import hashlib
import hmac

from dealerai.scripts.wa_simulate import build_payload, signed_body


def test_inbound_payload_and_signature_match_the_real_webhook_shape() -> None:
    payload = build_payload(
        "inbound",
        phone_number_id="phone-1",
        account_id="waba-1",
        customer="AE.seed.1",
        text="Is it available?",
        message_id="wamid.local.1",
        timestamp=1_789_646_400,
    )
    change = payload["entry"][0]["changes"][0]
    assert change["field"] == "messages"
    assert change["value"]["messages"][0]["from_user_id"] == "AE.seed.1"
    raw, signature = signed_body(payload, "secret")
    assert signature == "sha256=" + hmac.new(b"secret", raw, hashlib.sha256).hexdigest()


def test_voice_and_echo_use_their_platform_specific_shapes() -> None:
    voice = build_payload(
        "voice",
        phone_number_id="phone-1",
        account_id="waba-1",
        customer="AE.seed.1",
        text="hello",
        message_id="wamid.local.2",
        timestamp=1,
    )
    echo = build_payload(
        "echo",
        phone_number_id="phone-1",
        account_id="waba-1",
        customer="AE.seed.1",
        text="hello",
        message_id="wamid.local.2",
        timestamp=1,
    )
    assert voice["entry"][0]["changes"][0]["value"]["messages"][0]["type"] == "audio"
    assert echo["entry"][0]["changes"][0]["field"] == "smb_message_echoes"
