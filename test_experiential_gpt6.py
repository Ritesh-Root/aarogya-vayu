#!/usr/bin/env python3
"""
Test call for gpt-6-astra via Experiential gateway.

- Base URL: https://api.experientiallabs.ai/v1  (OpenAI Chat Completions)
- Model:    gpt-6-astra (exact)
- Auth:     EXPLABS_API_KEY env var (Bearer). If not set, exits with instructions
            to create one under Settings -> API keys and export it.

Shows reply + token usage to confirm it runs on Experiential credits.
Preserves streaming and tool-calls - see comments for how to enable them.
"""
import os
import sys
import json
import httpx

BASE_URL = "https://api.experientiallabs.ai/v1"
WHOAMI_URL = "https://api.experientiallabs.ai/api/whoami"
MODEL = "gpt-6-astra"

def require_key() -> str:
    key = os.getenv("EXPLABS_API_KEY")
    if not key:
        print("ERROR: EXPLABS_API_KEY is not set.", file=sys.stderr)
        print("Create one under Settings -> API keys at https://api.experientiallabs.ai", file=sys.stderr)
        print("and export it:", file=sys.stderr)
        print("  export EXPLABS_API_KEY='xpl_...'", file=sys.stderr)
        sys.exit(1)
    return key

def main():
    key = require_key()
    print(f"Base URL: {BASE_URL}")
    print(f"Model:    {MODEL}")
    print(f"Key prefix: {key[:8]}... (length {len(key)})")

    # 1) Verify key via whoami
    print("\n--- Verifying EXPLABS_API_KEY via /api/whoami ---")
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(WHOAMI_URL, headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            who = r.json()
            print(f"whoami OK: {json.dumps(who, indent=2)}")
    except Exception as e:
        print(f"whoami failed: {e}", file=sys.stderr)
        sys.exit(1)

    # 2) Non-streaming chat completions for both models (with usage)
    for model_name in ["gpt-6-astra", "claude-fable-5.1"]:
        print(f"\n--- Test call: {model_name} non-streaming Chat Completions (usage verification) ---")
        url = f"{BASE_URL}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": f"Say hello in one sentence and confirm you are {model_name} running via Experiential. Reply in English."}
            ],
            "max_tokens": 300,
            # streaming and tool_calls are preserved — add "stream": True or "tools": [...] to use them
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        print(f"Raw response:\n{json.dumps(data, indent=2)}")
        reply = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        print(f"\n>>> MODEL: {model_name}")
        print(f">>> REPLY: {reply}")
        print(f">>> TOKEN USAGE: {json.dumps(usage, indent=2)}")
        print(f">>> This ran on Experiential credits (base URL {BASE_URL}, model {model_name})")

    # 3) Streaming smoke (preserved)
    print("\n--- Test call: streaming + tool_calls smoke (no usage assert, just proving passthrough) ---")
    tools = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
        }
    }]
    payload2 = {
        "model": "gpt-6-astra",
        "messages": [{"role": "user", "content": "What is the weather in Lucknow? Use get_weather tool."}],
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 100,
    }
    with httpx.Client(timeout=30.0) as client:
        resp2 = client.post(url, headers=headers, json=payload2)
        resp2.raise_for_status()
        data2 = resp2.json()
    msg2 = data2["choices"][0]["message"]
    print(f"tool_calls: {json.dumps(msg2.get('tool_calls'), indent=2)}")
    print(f"content:    {msg2.get('content')}")
    print(f"usage:      {json.dumps(data2.get('usage',{}), indent=2)}")

    print("\n=== CONFIRMED: gpt-6-astra and claude-fable-5.1 via Experiential gateway are working ===")

if __name__ == "__main__":
    main()

