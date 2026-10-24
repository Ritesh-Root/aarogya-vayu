"""
Speech-to-text for frontline voice notes: Gemini transcribes the recorded audio (English, Hindi,
Odia or a mix). The browser converts each recording to 16 kHz mono WAV first, because Gemini
rejects the Opus/WebM audio that MediaRecorder produces. Claude has no audio input, so there is
no Claude fallback here; the client falls back to the browser's own speech recognition instead.
"""

import array
import math
import struct
from typing import Optional, Tuple

from pydantic import BaseModel

from app.llm import decode_media, generate_json

MAX_AUDIO_BYTES = 2 * 1024 * 1024  # ~60 s of 16 kHz mono 16-bit PCM
ALLOWED_AUDIO_MIME = {"audio/wav", "audio/x-wav", "audio/wave"}


class Transcript(BaseModel):
    is_speech: bool
    transcript: str
    language: str


def decode_audio(audio_base64: str, mime_type: Optional[str]) -> Tuple[bytes, str]:
    """Accepts raw base64 or a data URL of a WAV file; raises ValueError on bad input."""
    raw, _ = decode_media(audio_base64, mime_type, "audio/wav", ALLOWED_AUDIO_MIME, MAX_AUDIO_BYTES, "audio")
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("Audio is not a WAV file")
    return raw, "audio/wav"


MIN_SPEECH_SECONDS = 1.0
MIN_SPEECH_RMS = 60  # of 32767; quieter than this is silence or line noise


def is_too_short_or_silent(raw: bytes) -> bool:
    """Models invent text for near-empty clips, so don't send them. Reads 16-bit PCM WAV (what the client sends)."""
    try:
        channels, rate = struct.unpack_from("<HI", raw, 22)
        bits = struct.unpack_from("<H", raw, 34)[0]
        data_at = raw.find(b"data", 36)
        if bits != 16 or data_at < 0 or rate <= 0:
            return False  # unknown layout: let the model decide
        pcm = array.array("h", raw[data_at + 8:data_at + 8 + (len(raw) - data_at - 8) // 2 * 2])
    except struct.error:
        return False
    if len(pcm) / (rate * max(1, channels)) < MIN_SPEECH_SECONDS:
        return True
    step = max(1, len(pcm) // 50000)  # sample enough points for a stable estimate
    sampled = pcm[::step]
    return math.sqrt(sum(v * v for v in sampled) / len(sampled)) < MIN_SPEECH_RMS


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
