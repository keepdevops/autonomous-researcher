"""Shared LLM client for in-process research agents."""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8081/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "local")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))


def chat(prompt: str, *, system: str = "", max_tokens: int = 2048) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = httpx.post(
            f"{LLM_BASE_URL}/chat/completions",
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": max_tokens,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.error("agent LLM call failed: %s", exc)
        raise RuntimeError(f"LLM call failed: {exc}") from exc
