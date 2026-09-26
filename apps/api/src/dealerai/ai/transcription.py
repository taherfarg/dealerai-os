"""Audio transcription through the model gateway (budgeting and tracing included)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import structlog
from google.genai import types
from pydantic import BaseModel, Field

from .gateway import SystemLayers, complete
from .models import TaskKind
from .prompts import load

log = structlog.get_logger()


class _Spoken(BaseModel):
    """Schema-constrained output, so the model cannot name a language we do not store."""

    #: Asked first, and asked as a question rather than an instruction, because a
    #: model handed an unreadable file will otherwise write a plausible car
    #: enquiry rather than nothing — and a salesperson would answer it.
    speech_heard: bool = Field(
        description="True only if you can actually hear a person speaking in this audio. "
        "False for silence, noise, music, or a file you cannot read."
    )
    text: str = Field(
        description="Exactly what was said, in the language and script it was spoken in. "
        "Empty when speech_heard is false."
    )
    language: Literal["ar", "en", "fr", "other"] = Field(
        description="The language most of the message is in."
    )


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    #: ar, en or fr — what the inbox can label. Anything else is None rather
    #: than a language tag no screen knows how to show.
    language: str | None = None


#: Below this a file cannot hold a second of Opus, so it is a failed upload
#: rather than a voice note. It matters because the model does not refuse
#: undecodable audio — handed a truncated file it writes a plausible car
#: enquiry, and a salesperson would answer it.
#: ponytail: a length check, not a decode. Revisit if real voice notes ever
#: arrive in a format where this is the wrong floor.
MIN_AUDIO_BYTES = 1024


async def transcribe_audio(*, tenant_id: UUID, data: bytes, mime: str) -> Transcript:
    """Return only the spoken words; WhatsApp voice notes need no codec conversion."""
    if len(data) < MIN_AUDIO_BYTES:
        log.info("audio_too_short_to_transcribe", bytes=len(data), mime=mime)
        return Transcript(text="")

    content = types.Content(
        role="user",
        parts=[
            types.Part(text="Transcribe this voice note."),
            types.Part.from_bytes(data=data, mime_type=mime),
        ],
    )
    result = await complete(
        TaskKind.TRANSCRIBE,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("transcribe")),
        messages=content,
        output_schema=_Spoken,
        max_tokens=2_000,
        trace_name="whatsapp.transcribe",
        input_kind="audio",
    )
    assert isinstance(result.parsed, _Spoken)  # noqa: S101 - schema-constrained decoding
    spoken = result.parsed
    if not spoken.speech_heard:
        # Nothing was said. An invented sentence here is worse than no
        # transcript: the audio is still in the thread for a person to play.
        return Transcript(text="")
    return Transcript(
        text=spoken.text.strip(),
        language=None if spoken.language == "other" else spoken.language,
    )
