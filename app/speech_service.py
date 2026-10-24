"""
Speech-to-text for frontline voice notes: Gemini transcribes the recorded audio (English, Hindi,
Odia or a mix). The browser converts each recording to 16 kHz mono WAV first, because Gemini
rejects the Opus/WebM audio that MediaRecorder produces. Claude has no audio input, so there is
no Claude fallback here; the client falls back to the browser's own speech recognition instead.
"""

import base64
import binascii
from typing import Optional, Tuple

from pydantic import BaseModel

from app.llm import generate_json

MAX_AUDIO_BYTES = 2 * 1024 * 1024  # ~60 s of 16 kHz mono 16-bit PCM
ALLOWED_AUDIO_MIME = {"audio/wav", "audio/x-wav", "audio/wave"}


class Transcript(BaseModel):
    is_speech: bool
    transcript: str
    language: str


def decode_audio(audio_base64: str, mime_type: Optional[str]) -> Tuple[bytes, str]:
    """Accepts raw base64 or a data URL of a WAV file; raises ValueError on bad input."""
    data = audio_base64 or ""
    if data.startswith("data:"):
        header, _, data = data.partition(",")
        mime_type = header[5:].split(";")[0] or mime_type
    mime = (mime_type or "audio/wav").split(";")[0].strip().lower()
    if mime not in ALLOWED_AUDIO_MIME:
        raise ValueError("Unsupported audio type; send 16 kHz mono WAV")
    if len(data) > MAX_AUDIO_BYTES * 4 // 3 + 4:
        raise ValueError("Recording too long (max 2 MB)")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("audio_base64 is not valid base64")
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("audio_base64 is not a WAV file")
    return raw, "audio/wav"


async def transcribe(audio: Tuple[bytes, str]) -> Optional[Tuple[Transcript, str]]:
    system = (
        "You transcribe voice notes recorded by health workers at Indian primary health centres. "
        "The speech may be English, Hindi, Odia or a mix of them. Transcribe exactly what is said, without "
        "translating, summarising or adding anything. Write Hindi in Devanagari and Odia in Odia script, keep "
        "medicine and facility names as spoken, and write quantities as digits. Set language to an ISO 639-1 "
        "code (en, hi, or) or 'mixed'. If there is no intelligible speech, set is_speech to false and leave "
        "transcript empty."
    )
    return await generate_json(system, "Transcribe this voice note.", Transcript, media=audio)
