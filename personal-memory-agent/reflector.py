"""Daily self-reflection: scan recent assistant memories for contradictions."""
import os
import logging

import httpx

from memory import add_memory, recent_memories

logger = logging.getLogger(__name__)

CHAT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8081/v1")

REFLECTION_PROMPT = """You are a self-reflective agent examining your past \
memories for contradictions or errors. If you find a clear mistake or outdated \
belief, write a concise correction memory that supersedes it. Only output if \
you find something worth correcting."""


def run_daily_reflection() -> None:
    recent = recent_memories("assistant", days=7, limit=200)
    if not recent:
        logger.info("Reflection: no recent assistant memories, skipping.")
        return

    try:
        resp = httpx.post(
            f"{CHAT_BASE_URL}/chat/completions",
            json={
                "model": "local",
                "messages": [
                    {"role": "system", "content": REFLECTION_PROMPT},
                    {"role": "user", "content": "Recent memories:\n" + "\n".join(recent)},
                ],
                "temperature": 0.1,
                "max_tokens": 1024,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        reflection = resp.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.error("Reflection request failed: %s", e)
        return

    if reflection and len(reflection) > 50:
        add_memory("reflection", reflection, {"type": "correction"})
        logger.info("Reflection: stored a correction memory.")
