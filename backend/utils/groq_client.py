"""
Groq LLM Client - Handles all calls to Groq API
"""
import os
import httpx
import json
import logging
from typing import Optional
import time
import asyncio

logger = logging.getLogger(__name__)

# rate limit support: ensure at most ~20-25 requests per minute
_rate_lock = asyncio.Lock()
_last_request_ts = 0.0
# minimum interval between calls in seconds (≈ 60/20 = 3 sec)
RATE_INTERVAL = 5.0

async def _enforce_rate_limit() -> None:
    """Sleep if the previous request was made too recently."""
    global _last_request_ts
    async with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_ts
        if elapsed < RATE_INTERVAL:
            await asyncio.sleep(RATE_INTERVAL - elapsed)
        _last_request_ts = time.monotonic()

# base URL and default model remain constant
GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"


async def groq_chat(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Send a chat request to Groq and return the response text."""
    # enforce local rate limit to avoid hitting the per-minute cap
    await _enforce_rate_limit()

    # fetch key at call time so changes to env or .env are respected
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable not set. "
                         "Create a .env file or export it in your shell.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(GROQ_BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            logger.error(f"Groq API error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"Groq API error: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Groq request failed: {str(e)}")
            raise


async def groq_json(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
) -> dict:
    """Send a chat request and parse JSON response."""
    sys = system_prompt + "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, just raw JSON."
    text = await groq_chat(sys, user_prompt, model=model, max_tokens=max_tokens)
    # Strip potential markdown code fences
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        logger.error(f"Failed to parse JSON: {text[:500]}")
        raise ValueError(f"Could not parse JSON from Groq response")
