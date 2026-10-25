"""
Speech-to-text for frontline voice notes: Gemini transcribes the recorded audio (English, Hindi,
Odia or a mix). The browser converts each recording to 16 kHz mono WAV first, because Gemini
rejects the Opus/WebM audio that MediaRecorder produces. Claude has no audio input, so there is
no Claude fallback here; the client falls back to the browser's own speech recognition instead.
"""

import array
import asyncio
import logging
import math
import os
import struct
from collections import OrderedDict
from typing import Optional, Tuple

from pydantic import BaseModel

from app.llm import _gemini, decode_media, generate_json

logger = logging.getLogger(__name__)

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


# ---- Text-to-speech for the CMO briefing ("Read aloud") ----
# Gemini's speech models return a complete 24 kHz mono WAV. The model reads any style instruction
# aloud, so only the briefing text is sent; the accent comes from language_code.
TTS_MODELS = [os.getenv("TTS_MODEL") or "gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]
TTS_VOICE = os.getenv("TTS_VOICE") or "Charon"
TTS_TIMEOUT_S = float(os.getenv("TTS_TIMEOUT_S", "20"))
MAX_TTS_CHARS = 700
_tts_cache: "OrderedDict[str, bytes]" = OrderedDict()  # replaying the same briefing costs nothing
TTS_CACHE_SIZE = 16


def _pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1,
                         rate, rate * 2, 2, 16, b"data", len(pcm))
    return header + pcm


async def synthesize(text: str) -> Optional[Tuple[bytes, str]]:
    """Returns (wav_bytes, model) or None when no Gemini speech model answers."""
    text = " ".join(text.split())[:MAX_TTS_CHARS]
    if not text:
        return None
    if text in _tts_cache:
        _tts_cache.move_to_end(text)
        return _tts_cache[text], "cache"
    client = _gemini()
    if not client:
        return None
    from google.genai import types
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            language_code="en-IN",
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)),
        ),
    )
    for model in TTS_MODELS:
        try:
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(model=model, contents=text, config=config),
                timeout=TTS_TIMEOUT_S,
            )
            data = resp.candidates[0].content.parts[0].inline_data.data
        except Exception as e:  # timeout, quota, empty candidate
            logger.warning("Gemini TTS %s failed: %s", model, e)
            continue
        if not data:
            continue
        wav = data if data[:4] == b"RIFF" else _pcm_to_wav(data)
        _tts_cache[text] = wav
        if len(_tts_cache) > TTS_CACHE_SIZE:
            _tts_cache.popitem(last=False)
        return wav, model
    return None
