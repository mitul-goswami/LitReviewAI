"""
Groq LLM Client
===============
Strict dual-key setup — NO fallbacks between keys:

  GROQ_API_KEY        → groq_chat() / groq_json()
                        Used by: Search, Comparison, Planner agents

  GROQ_API_KEY_WRITER → groq_chat_writer() / groq_json_writer()
                        Used by: Summarization, Writer agents

Each key has its own independent rate-limit bucket so the two groups
never block each other.
"""
import os
import httpx
import json
import logging
import time
import asyncio

logger = logging.getLogger(__name__)

# ── Groq endpoint ────────────────────────────────────────────────────────────
GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

# ── Models ───────────────────────────────────────────────────────────────────
PRIMARY_MODEL = "llama-3.3-70b-versatile"   # search / comparison / planner
WRITER_MODEL  = "llama-3.3-70b-versatile"   # summarization / writer

# ── Rate limiting (one independent bucket per key) ───────────────────────────
# ~20 req/min max → enforce ≥ 5 s between calls per bucket
RATE_INTERVAL = 5.0

_primary_lock = asyncio.Lock()
_primary_last: float = 0.0

_writer_lock = asyncio.Lock()
_writer_last: float = 0.0


async def _enforce_rate_primary() -> None:
    global _primary_last
    async with _primary_lock:
        wait = RATE_INTERVAL - (time.monotonic() - _primary_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _primary_last = time.monotonic()


async def _enforce_rate_writer() -> None:
    global _writer_last
    async with _writer_lock:
        wait = RATE_INTERVAL - (time.monotonic() - _writer_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _writer_last = time.monotonic()


# ── Key resolution — strict, no cross-fallback ───────────────────────────────
def _primary_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set.\n"
            "Add it to your .env file:\n"
            "  GROQ_API_KEY=gsk_..."
        )
    return key


def _writer_key() -> str:
    key = os.environ.get("GROQ_API_KEY_WRITER", "").strip()
    if not key:
        raise EnvironmentError(
            "GROQ_API_KEY_WRITER is not set.\n"
            "Add it to your .env file:\n"
            "  GROQ_API_KEY_WRITER=gsk_..."
        )
    return key


# ── Core HTTP call ────────────────────────────────────────────────────────────
async def _call_groq(api_key: str, model: str, system: str, user: str,
                     max_tokens: int, temperature: float) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(GROQ_BASE_URL, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            logger.error(f"Groq HTTP error {e.response.status_code}: {e.response.text}")
            raise RuntimeError(f"Groq API error {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            logger.error(f"Groq request failed: {e}")
            raise


# ── JSON parsing helper ───────────────────────────────────────────────────────
def _parse_json(text: str) -> dict:
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        logger.error(f"Cannot parse JSON from Groq response: {text[:500]}")
        raise ValueError("Could not parse JSON from Groq response")


# ════════════════════════════════════════════════════════════════════════════
#  PRIMARY API  —  Search / Comparison / Planner agents
# ════════════════════════════════════════════════════════════════════════════
async def groq_chat(
    system_prompt: str,
    user_prompt: str,
    model: str = PRIMARY_MODEL,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Chat via PRIMARY key (GROQ_API_KEY)."""
    await _enforce_rate_primary()
    return await _call_groq(
        _primary_key(), model, system_prompt, user_prompt, max_tokens, temperature
    )


async def groq_json(
    system_prompt: str,
    user_prompt: str,
    model: str = PRIMARY_MODEL,
    max_tokens: int = 4096,
) -> dict:
    """JSON chat via PRIMARY key (GROQ_API_KEY)."""
    sys_p = system_prompt + "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, just raw JSON."
    text = await groq_chat(sys_p, user_prompt, model=model, max_tokens=max_tokens)
    return _parse_json(text)


# ════════════════════════════════════════════════════════════════════════════
#  WRITER API  —  Summarization / Writer agents
# ════════════════════════════════════════════════════════════════════════════
async def groq_chat_writer(
    system_prompt: str,
    user_prompt: str,
    model: str = WRITER_MODEL,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Chat via WRITER key (GROQ_API_KEY_WRITER)."""
    await _enforce_rate_writer()
    return await _call_groq(
        _writer_key(), model, system_prompt, user_prompt, max_tokens, temperature
    )


async def groq_json_writer(
    system_prompt: str,
    user_prompt: str,
    model: str = WRITER_MODEL,
    max_tokens: int = 4096,
) -> dict:
    """JSON chat via WRITER key (GROQ_API_KEY_WRITER)."""
    sys_p = system_prompt + "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, just raw JSON."
    text = await groq_chat_writer(sys_p, user_prompt, model=model, max_tokens=max_tokens)
    return _parse_json(text)
