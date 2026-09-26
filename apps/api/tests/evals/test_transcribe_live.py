"""Live eval: a real WhatsApp voice note through the real gateway.

Excluded from the default run: `npm run eval:transcribe`.

The unit tests fake `transcribe_audio`, and a fake is always more capable than
the thing it stands in for — the faked transcript reported a language while the
real function returned none. This is the check that the real one answers.
"""

from __future__ import annotations

import pathlib

import pytest

from conftest import TENANT_A
from dealerai.ai.transcription import transcribe_audio
from dealerai.config import get_settings

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]

#: What the local simulator sends: six seconds of English speech about a car.
SAMPLE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src"
    / "dealerai"
    / "connectors"
    / "samples"
    / "voice-note.ogg"
)


async def test_a_voice_note_transcribes_with_its_language(db: None, seeded: None) -> None:
    result = await transcribe_audio(
        tenant_id=TENANT_A,
        data=SAMPLE.read_bytes(),
        # WhatsApp's exact type, parameter and all — Gemini accepts it.
        mime="audio/ogg; codecs=opus",
    )

    assert "land cruiser" in result.text.lower(), f"did not hear the car: {result.text!r}"
    assert result.language == "en"


async def test_a_recording_with_nothing_in_it_stays_empty(db: None, seeded: None) -> None:
    """A voice note that recorded silence must not become a sentence.

    Asked to transcribe, the model writes plausible dialogue rather than
    nothing, and a salesperson reading it would answer a question nobody asked.
    `speech_heard` is what stops it.
    """
    silence = pathlib.Path(__file__).with_name("fixtures") / "silence.ogg"
    result = await transcribe_audio(
        tenant_id=TENANT_A, data=silence.read_bytes(), mime="audio/ogg; codecs=opus"
    )

    assert result.text == "", f"invented {result.text!r} out of three seconds of silence"


async def test_a_truncated_upload_never_reaches_the_model(db: None, seeded: None) -> None:
    """The one case `speech_heard` does not catch, so code catches it first.

    Handed 400 bytes of a broken file the model still answered "Hello, I'm
    looking for..." — confidently, twice, with the flag set. Anything too short
    to hold a second of audio is a failed upload, and costs no model call.
    """
    result = await transcribe_audio(
        tenant_id=TENANT_A, data=SAMPLE.read_bytes()[:400], mime="audio/ogg; codecs=opus"
    )

    assert result.text == ""
