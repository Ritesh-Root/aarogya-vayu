"""
Structured-JSON LLM calls for Aarogya-Vāyu.

Provider order:
  1) Google Gemini (primary) via the google-genai async client.
  2) Anthropic Claude (fallback) via the official anthropic SDK, used only when
     Gemini is unconfigured or fails.

Each call returns a validated Pydantic instance plus the provider label, or None
so callers can drop to their deterministic offline fallback.
"""

import os
import asyncio
import logging
from typing import Optional, Tuple, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# `or` (not a getenv default) so an env var that exists but is empty still gets the default
GEMINI_MODELS = [
    os.getenv("DEFAULT_MODEL") or "gemini-3.8-flash",
    os.getenv("FALLBACK_MODEL") or "gemini-3.5-flash-lite",
]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL") or "claude-haiku-5-5"
LLM_ATTEMPT_TIMEOUT_S = float(os.getenv("LLM_ATTEMPT_TIMEOUT_S", "12"))
# Overall budget across all attempts, so callers reach their offline fallback before a serverless timeout
LLM_TOTAL_BUDGET_S = float(os.getenv("LLM_TOTAL_BUDGET_S", "28"))
MAX_OUTPUT_TOKENS = 4096

_gemini_client = None
_claude_client = None


def _gemini_key() -> Optional[str]:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_API_KEY")


def provider_status() -> dict:
    """Which providers have credentials configured (booleans only, never key material)."""
    return {
        "gemini": bool(_gemini_key()),
        "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
        "primary": "gemini",
        "gemini_model": GEMINI_MODELS[0],
        "claude_model": CLAUDE_MODEL,
    }


def _gemini():
    global _gemini_client
    key = _gemini_key()
    if _gemini_client is None and key:
        from google import genai
        _gemini_client = genai.Client(api_key=key)
    return _gemini_client


def _claude():
    global _claude_client
    if _claude_client is None and os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        _claude_client = anthropic.AsyncAnthropic(timeout=LLM_ATTEMPT_TIMEOUT_S, max_retries=0)
    return _claude_client


async def _call_gemini(system: str, user: str, schema: Type[T]) -> Optional[T]:
    try:
        client = _gemini()
        if not client:
            return None
        from google.genai import types
    except Exception as e:
        logger.warning("Gemini client unavailable: %s", e)
        return None
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for model in GEMINI_MODELS:
        try:
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(model=model, contents=user, config=config),
                timeout=LLM_ATTEMPT_TIMEOUT_S,
            )
            if isinstance(resp.parsed, schema):
                return resp.parsed
            if resp.text:
                return schema.model_validate_json(resp.text)
        except asyncio.TimeoutError:
            # A slow Gemini is likely slow for every model; leave the budget for Claude
            logger.warning("Gemini %s timed out after %ss", model, LLM_ATTEMPT_TIMEOUT_S)
            break
        except Exception as e:
            logger.warning("Gemini %s call failed: %s", model, e)
    return None


async def _call_claude(system: str, user: str, schema: Type[T]) -> Optional[T]:
    try:
        client = _claude()
        if not client:
            return None
        import anthropic
    except Exception as e:
        logger.warning("Claude client unavailable: %s", e)
        return None
    try:
        resp = await client.messages.parse(
            model=CLAUDE_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if resp.stop_reason == "refusal":
            logger.warning("Claude refused request (request_id=%s)", resp._request_id)
            return None
        return resp.parsed_output
    except anthropic.APIStatusError as e:
        logger.warning("Claude API error %s: %s", e.status_code, e.message)
    except anthropic.APIConnectionError as e:
        logger.warning("Claude connection error: %s", e)
    except Exception as e:
        logger.warning("Claude response parse failed: %s", e)
    return None


async def _generate_json(system: str, user: str, schema: Type[T]) -> Optional[Tuple[T, str]]:
    parsed = await _call_gemini(system, user, schema)
    if parsed is not None:
        return parsed, "gemini"
    parsed = await _call_claude(system, user, schema)
    if parsed is not None:
        return parsed, "claude"
    return None


async def generate_json(system: str, user: str, schema: Type[T]) -> Optional[Tuple[T, str]]:
    """Gemini first, Claude as fallback. Returns (parsed, provider) or None."""
    try:
        return await asyncio.wait_for(_generate_json(system, user, schema), timeout=LLM_TOTAL_BUDGET_S)
    except asyncio.TimeoutError:
        logger.warning("LLM budget of %ss exhausted; using offline fallback", LLM_TOTAL_BUDGET_S)
        return None
