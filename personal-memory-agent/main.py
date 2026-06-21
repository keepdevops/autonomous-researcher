"""Personal Memory Agent — a lifelong chat assistant with vector recall.

Talks to the chat model on :8081 and embeds/recalls via the embedding server
on :8082 (see memory.py / embedder.py). Run the servers first:
    ../start-llm.sh     # chat model, :8081
    ../start-embed.sh   # embedding model, :8082
"""
import _repo_path  # noqa: F401
import os
import logging
import threading
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.markdown import Markdown

from memory import add_memory, search_memories
from reflector import run_daily_reflection

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agent")

console = Console()

CHAT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8081/v1")
client = httpx.Client(base_url=CHAT_BASE_URL, timeout=None)

SYSTEM_PROMPT = """You are my personal lifelong assistant with perfect memory.
You have access to everything we have ever discussed.
When relevant, recall past conversations accurately and cite them.
Today's date and time is {now}.
Be helpful, truthful, and concise."""

# How many recent *clean* turns to replay verbatim. Older context comes from
# vector recall, NOT from an ever-growing transcript — keeping the whole history
# in-prompt overflows the model's context window after a few turns and silently
# truncates, which is fatal for a "lifelong" agent. We cap the window here and
# rely on search_memories() to surface anything older that's relevant.
HISTORY_WINDOW_TURNS = int(os.environ.get("HISTORY_WINDOW_TURNS", "8"))

# Rolling window of clean {role, content} turns (no retrieved-context padding).
history: list[dict] = []


def retrieve_relevant_memories(query: str) -> str:
    try:
        memories = search_memories(query, k=12)
    except Exception as e:
        logger.error("Memory retrieval failed: %s", e)
        return "No relevant memories found (retrieval error)."
    if not memories:
        return "No relevant memories found."

    formatted = "\n\nRelevant past memories (most recent first):\n"
    for mem in reversed(memories):
        ts = datetime.fromisoformat(mem["timestamp"].replace("Z", "+00:00"))
        formatted += (
            f"[{ts.strftime('%Y-%m-%d %H:%M')}] "
            f"{mem['role'].title()}: {mem['content'][:500]}\n"
        )
    return formatted


def _build_messages(user_input: str) -> list[dict]:
    """System prompt + capped recent history + a transient recall-augmented turn.

    The recall context is attached only to the message sent this turn; it is
    never written back into `history`, so the prompt stays bounded regardless of
    how long the conversation runs.
    """
    context = retrieve_relevant_memories(user_input)
    system = {
        "role": "system",
        "content": SYSTEM_PROMPT.format(now=datetime.now(timezone.utc).isoformat()),
    }
    recent = history[-HISTORY_WINDOW_TURNS:]
    augmented_turn = {
        "role": "user",
        "content": f"{context}\n\nCurrent question: {user_input}",
    }
    return [system, *recent, augmented_turn]


def chat_once(user_input: str) -> str:
    try:
        from observer import publish
        from observer.events import Component, EventKind, SystemEvent

        publish(
            SystemEvent(
                component=Component.MEMORY,
                kind=EventKind.LIFECYCLE,
                status="chat_turn",
                detail=user_input[:120],
                metadata={"chars": len(user_input)},
            )
        )
    except Exception:
        pass
    resp = client.post(
        "/chat/completions",
        json={
            "model": "local",
            "messages": _build_messages(user_input),
            "temperature": 0.7,
            "max_tokens": 4096,
        },
    )
    resp.raise_for_status()
    assistant_message = resp.json()["choices"][0]["message"]["content"]

    # Append CLEAN turns to the rolling window (no context padding) and persist
    # the real exchange to long-term vector memory.
    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": assistant_message})
    add_memory("user", user_input)
    add_memory("assistant", assistant_message)
    return assistant_message


def chat_loop() -> None:
    console.print("[bold green]Personal Memory Agent ready. Type 'exit' to quit.[/bold green]\n")
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "exit":
            break
        try:
            assistant_message = chat_once(user_input)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.error("Chat turn failed: %s", e)
            console.print("[bold red]Error: chat request failed — is the LLM server up?[/bold red]")
            continue
        console.print("\n[bold cyan]Agent:[/bold cyan]")
        console.print(Markdown(assistant_message))


if __name__ == "__main__":
    import sys

    import preflight  # imported here to avoid a circular import at module load

    try:
        from observer import ensure
        ensure()
    except Exception:
        pass

    try:
        preflight.check()
    except preflight.PreflightError as e:
        console.print(f"[bold red]Preflight failed:[/bold red] {e}")
        sys.exit(1)

    # Run reflection every 24h in the background (daemon dies with the process).
    threading.Timer(86400, run_daily_reflection).start()
    chat_loop()
