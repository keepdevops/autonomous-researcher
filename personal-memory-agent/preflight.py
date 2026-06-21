"""Startup capability checks — fail loudly if the servers are mis-wired.

The agent needs TWO distinct llama.cpp servers: a chat (generation) server and
an embedding server. Pointing chat traffic at the embedding server yields a
cryptic mid-run 500 ("the current context does not logits computation. skipping").
This module probes both endpoints up front and aborts with a clear message if the
ports are crossed, unreachable, or the wrong kind of server.
"""
import _repo_path  # noqa: F401
import logging

import httpx

from embedder import EMBED_BASE_URL
from main import CHAT_BASE_URL  # single source of truth for the chat endpoint

logger = logging.getLogger(__name__)


class PreflightError(RuntimeError):
    """Raised when an endpoint is missing or the wrong kind of server."""


def _check_chat(base_url: str) -> None:
    """The chat endpoint must complete generation. An embedding server returns
    500 'does not logits computation'; a dead server raises a connection error."""
    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            json={"model": "local", "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 1, "temperature": 0},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        logger.error("Chat preflight: cannot reach %s: %s", base_url, e)
        raise PreflightError(
            f"chat server unreachable at {base_url} — start it with ../start-llm.sh"
        ) from e
    if resp.status_code != 200:
        detail = resp.text[:200]
        if "logits" in detail:
            raise PreflightError(
                f"LLM_BASE_URL ({base_url}) points at an EMBEDDING server, which "
                f"cannot generate text. Point chat at the :8081 server and set "
                f"EMBED_BASE_URL to the :8082 embedding server."
            )
        logger.error("Chat preflight failed (%s): %s", resp.status_code, detail)
        raise PreflightError(f"chat server at {base_url} returned {resp.status_code}: {detail}")


def _check_embed(base_url: str) -> None:
    """The embedding endpoint must return vectors. A chat server typically lacks
    /embeddings (404) or errors; a dead server raises a connection error."""
    try:
        resp = httpx.post(
            f"{base_url}/embeddings",
            json={"model": "nomic", "input": ["search_query: ping"]},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        logger.error("Embed preflight: cannot reach %s: %s", base_url, e)
        raise PreflightError(
            f"embedding server unreachable at {base_url} — start it with ../start-embed.sh"
        ) from e
    if resp.status_code != 200 or not resp.json().get("data"):
        detail = resp.text[:200]
        logger.error("Embed preflight failed (%s): %s", resp.status_code, detail)
        raise PreflightError(
            f"EMBED_BASE_URL ({base_url}) is not a working embedding server "
            f"(status {resp.status_code}). It must be the :8082 --embedding server, "
            f"not the chat server."
        )


def _observe(status: str, detail: str = "", **metadata) -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.PREFLIGHT,
                kind=EventKind.HEALTH,
                status=status,
                detail=detail,
                metadata=metadata,
            )
        )
    except Exception as e:
        logger.debug("observer emit skipped: %s", e)


def check(chat_url: str = CHAT_BASE_URL, embed_url: str = EMBED_BASE_URL) -> None:
    """Verify both servers are up and of the correct kind. Raises PreflightError."""
    if chat_url.rstrip("/") == embed_url.rstrip("/"):
        err = (
            f"chat and embedding endpoints are identical ({chat_url}); they must be "
            f"two separate servers (chat :8081, embeddings :8082)."
        )
        _observe("failed", err)
        raise PreflightError(err)
    try:
        _check_chat(chat_url)
        _check_embed(embed_url)
    except PreflightError as e:
        _observe("failed", str(e))
        raise
    _observe("ok", chat_url=chat_url, embed_url=embed_url)
    logger.info("Preflight OK — chat %s, embeddings %s", chat_url, embed_url)
