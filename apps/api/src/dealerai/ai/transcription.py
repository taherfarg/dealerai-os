"""Audio transcription through the model gateway (budgeting and tracing included)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from google.genai import types

from .gateway import SystemLayers, complete
from .models import TaskKind
from .prompts import load


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str | None = None


async def transcribe_audio(*, tenant_id: UUID, data: bytes, mime: str) -> Transcript:
    """Return only the spoken words; WhatsApp voice notes need no codec conversion."""
    content = types.Content(
        role="user",
        parts=[
            types.Part(text="Transcribe this audio exactly. Return only the transcript."),
            types.Part.from_bytes(data=data, mime_type=mime),
        ],
    )
    result = await complete(
        TaskKind.TRANSCRIBE,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("transcribe")),
        messages=content,
        max_tokens=2_000,
        trace_name="whatsapp.transcribe",
        input_kind="audio",
    )
    return Transcript(text=result.text.strip())
