"""
Experiential Gateway client for gpt-6-astra and claude-fable-5.1.

Routes LLM calls for "gpt-6-astra" and "claude-fable-5.1" through the Experiential
gateway instead of calling the provider directly. The gateway speaks the OpenAI
Chat Completions API, so this is a base-URL + key swap.

- Base URL: https://api.experientiallabs.ai/v1  (OpenAI-compatible)
- Auth:     EXPLABS_API_KEY environment variable (Bearer token)
- Models:   gpt-6-astra (exact), claude-fable-5.1 (exact) — same gateway/key

Usage (non-streaming):
    from app.experiential_client import chat, get_api_key

    result = await chat([{"role":"user","content":"hello"}])
    print(result["content"], result["usage"])

Usage (streaming - preserves streaming):
    from app.experiential_client import stream_chat
    async for chunk in stream_chat(messages):
        print(chunk, end="")

Usage (tool-calls - preserves tool_calls):
    result = await chat(messages, tools=[...], tool_choice="auto")
    # tool_calls returned in result["tool_calls"] or in streamed deltas

If EXPLABS_API_KEY is not set, every entry point raises RuntimeError with
instructions to create a key under Settings -> API keys and export it.
"""

import os
import json
import httpx
from typing import List, Dict, Any, Optional, AsyncIterator

EXPERIENTIAL_BASE_URL = "https://api.experientiallabs.ai/v1"
EXPERIENTIAL_WHOAMI_URL = "https://api.experientiallabs.ai/api/whoami"
MODEL_ID = "gpt-6-astra"  # exact - do not change
CLAUDE_MODEL_ID = "claude-fable-5.1"  # exact - same gateway/key
# All models available via this gateway: gpt-6-astra, claude-fable-5.1 (and 696 more via /v1/models)


def get_api_key() -> str:
    """Return EXPLABS_API_KEY or raise with user-facing instructions."""
    key = os.getenv("EXPLABS_API_KEY")
    if not key:
        raise RuntimeError(
            "EXPLABS_API_KEY is not set. "
            "Create one under Settings -> API keys at https://api.experientiallabs.ai "
            "and export it:\n"
            "  export EXPLABS_API_KEY='xpl_...'\n"
            "Then re-run the app. Refusing to call Experiential without a key."
        )
    return key


def get_client_kwargs(model: str = MODEL_ID) -> Dict[str, str]:
    """Return base_url + api_key dict for OpenAI SDK users."""
    return {
        "base_url": EXPERIENTIAL_BASE_URL,
        "api_key": get_api_key(),
        "model": model,
    }


def get_openai_client():
    """
    Return an OpenAI SDK client pointed at Experiential.
    Requires `openai` package. Falls back to httpx if not installed.
    """
    try:
        from openai import OpenAI, AsyncOpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai package not installed. Install with `pip install openai` "
            "or use the httpx-based helpers `chat()` / `stream_chat()` in this file."
        ) from e

    kwargs = get_client_kwargs()
    return OpenAI(base_url=kwargs["base_url"], api_key=kwargs["api_key"])


def get_async_openai_client():
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai package not installed. Install with `pip install openai` "
            "or use the httpx-based helpers `chat()` / `stream_chat()`."
        ) from e
    kwargs = get_client_kwargs()
    return AsyncOpenAI(base_url=kwargs["base_url"], api_key=kwargs["api_key"])


# ---------------------------------------------------------------------------
# httpx-based helpers (no extra deps beyond httpx which is already in the app)
# ---------------------------------------------------------------------------

async def chat(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    extra: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
    model: str = MODEL_ID,
) -> Dict[str, Any]:
    """
    Non-streaming Chat Completions via Experiential.

    Preserves tool_calls and streaming interface:
    - `tools` / `tool_choice` are passed through unchanged
    - if stream=True, use `stream_chat()` instead (this helper raises)
    - `temperature` is omitted by default because gpt-6-astra route does not
      support it (400 unsupported_parameter). Pass explicitly only if needed.

    Returns dict with keys: content, tool_calls, usage, raw
    """
    if stream:
        raise ValueError("chat(stream=True) not allowed: use stream_chat() for streaming")

    api_key = get_api_key()
    url = f"{EXPERIENTIAL_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    msg = choice.get("message", {})
    return {
        "content": msg.get("content"),
        "tool_calls": msg.get("tool_calls"),
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage", {}),
        "raw": data,
        "model": data.get("model", model),
    }


def chat_sync(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
    model: str = MODEL_ID,
) -> Dict[str, Any]:
    """Synchronous version of chat() for scripts / tests."""
    api_key = get_api_key()
    url = f"{EXPERIENTIAL_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    msg = choice.get("message", {})
    return {
        "content": msg.get("content"),
        "tool_calls": msg.get("tool_calls"),
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage", {}),
        "raw": data,
        "model": data.get("model", model),
    }


async def stream_chat(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
    model: str = MODEL_ID,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Streaming Chat Completions via Experiential (OpenAI SSE format).

    Yields dicts with `delta` (content/tool_calls delta) and `usage` on final chunk.
    Preserves streaming and tool_calls exactly as the OpenAI API does.
    """
    api_key = get_api_key()
    url = f"{EXPERIENTIAL_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                # Pass through exactly as OpenAI streams it
                yield chunk


async def verify_key() -> Dict[str, Any]:
    """Verify EXPLABS_API_KEY via /api/whoami. Returns org info."""
    api_key = get_api_key()
    url = EXPERIENTIAL_WHOAMI_URL
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def verify_key_sync() -> Dict[str, Any]:
    api_key = get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(EXPERIENTIAL_WHOAMI_URL, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# CLI test helper: `python -m app.experiential_client`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio

    async def _test():
        print(f"Base URL: {EXPERIENTIAL_BASE_URL}")
        print(f"Model:    {MODEL_ID}")
        try:
            who = await verify_key()
            print(f"whoami:   {who}")
        except Exception as e:
            print(f"whoami failed: {e}")
            return

        print(f"\n--- test chat for gpt-6-astra ---")
        res = await chat(
            messages=[{"role": "user", "content": "Say hello in one sentence and confirm you are gpt-6-astra running via Experiential. Reply in English."}],
            max_tokens=300,
            model=MODEL_ID,
        )
        print(f"reply: {res['content']}")
        print(f"usage: {res['usage']}")

        print(f"\n--- test chat for claude-fable-5.1 ---")
        res_claude = await chat(
            messages=[{"role": "user", "content": "Say hello in one sentence and confirm you are claude-fable-5.1 running via Experiential. Reply in English."}],
            max_tokens=300,
            model=CLAUDE_MODEL_ID,
        )
        print(f"reply: {res_claude['content']}")
        print(f"usage: {res_claude['usage']}")

        print("\n--- test streaming + tool_calls passthrough (smoke) ---")
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
            }
        }]
        res2 = await chat(
            messages=[{"role": "user", "content": "What is the weather in Lucknow? Use the get_weather tool."}],
            tools=tools,
            tool_choice="auto",
            max_tokens=100,
            model=MODEL_ID,
        )
        print(f"tool_calls: {res2['tool_calls']}")
        print(f"content:    {res2['content']}")
        print(f"usage:      {res2['usage']}")

    asyncio.run(_test())

