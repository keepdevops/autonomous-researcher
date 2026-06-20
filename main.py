"""Autonomous researcher: agentic loop over a local OpenAI-compatible LLM.

Drives a local llama.cpp server (OpenAI /v1 API) with the search/read/write
tools defined in tools.py until the model produces a final cited report.
"""

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List

import httpx
from rich.console import Console
from rich.markdown import Markdown

from tools import TOOLS_SCHEMAS, dispatch_tool

console = Console()
logger = logging.getLogger(__name__)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "local")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "12"))
# A weak model can emit malformed tool calls that the server rejects with a 500.
# Feed the error back so the model can retry, but bail after this many in a row.
MAX_CONSECUTIVE_LLM_ERRORS = int(os.getenv("MAX_CONSECUTIVE_LLM_ERRORS", "3"))

SYSTEM_PROMPT = (
    "You are an expert autonomous researcher running 100% locally. You have "
    "access to search_web, read_url, and write_file tools. Always search first; "
    "your built-in knowledge has a cutoff. Read the most promising URLs before "
    "answering. Cite every source URL in your final answer using markdown links. "
    "When you have enough information, synthesize a clear, cited report. "
    "Today's date is June 19, 2026."
)


def call_llm(client: httpx.Client, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Post the conversation to the local server and return the assistant message."""
    try:
        resp = client.post(
            "/chat/completions",
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
                "tools": TOOLS_SCHEMAS,
                "tool_choice": "auto",
            },
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Surface the server body (e.g. llama.cpp "Failed to parse input ..." on a
        # malformed tool call), which raise_for_status() otherwise discards.
        detail = exc.response.text.strip()
        logger.error("call_llm got %s: %s", exc.response.status_code, detail)
        raise RuntimeError(f"LLM request failed ({exc.response.status_code}): {detail}") from exc
    except httpx.HTTPError as exc:
        logger.error("call_llm request failed: %s", exc)
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    try:
        return resp.json()["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as exc:
        logger.error("call_llm got malformed response: %s", exc)
        raise RuntimeError(f"Malformed LLM response: {exc}") from exc


def run_tool_call(tool_call: Dict[str, Any]) -> str:
    """Execute one tool call and return its result serialized as a string."""
    name = tool_call.get("function", {}).get("name", "")
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except json.JSONDecodeError as exc:
        logger.error("run_tool_call: bad JSON args for %r: %s", name, exc)
        return f"Error: invalid tool arguments for {name}: {exc}"

    console.print(f"[dim]→ {name}({json.dumps(args)[:200]})[/dim]")
    try:
        result = dispatch_tool(name, args)
    except Exception as exc:  # surface tool failures back to the model, but log loudly
        logger.error("run_tool_call: tool %r failed: %s", name, exc)
        return f"Error running {name}: {exc}"

    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def research(question: str) -> str:
    """Run the agentic loop for one question and return the final report text."""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    consecutive_errors = 0
    with httpx.Client(base_url=LLM_BASE_URL, timeout=None) as client:
        for step in range(MAX_ITERATIONS):
            try:
                message = call_llm(client, messages)
            except RuntimeError as exc:
                consecutive_errors += 1
                logger.error(
                    "research: LLM error %d/%d at step %d: %s",
                    consecutive_errors, MAX_CONSECUTIVE_LLM_ERRORS, step, exc,
                )
                if consecutive_errors >= MAX_CONSECUTIVE_LLM_ERRORS:
                    raise RuntimeError(
                        f"LLM failed {consecutive_errors} times in a row: {exc}"
                    ) from exc
                # Nudge the model to recover (e.g. emit one well-formed tool call).
                messages.append({
                    "role": "user",
                    "content": (
                        f"The previous request failed: {exc}. Emit exactly one "
                        "well-formed tool call, or give your final answer."
                    ),
                })
                continue

            consecutive_errors = 0
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                content = message.get("content") or ""
                if not content.strip():
                    logger.error("research: empty final message at step %d", step)
                    raise RuntimeError("LLM returned an empty final answer")
                return content

            for tool_call in tool_calls:
                output = run_tool_call(tool_call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": output,
                    }
                )

    logger.error("research: hit MAX_ITERATIONS=%d without a final answer", MAX_ITERATIONS)
    raise RuntimeError(f"No final answer after {MAX_ITERATIONS} iterations")


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous local researcher backed by a llama.cpp server."
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="Research question (if omitted, read from an interactive prompt).",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s"
    )
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    question = " ".join(args.question).strip()
    if not question:
        try:
            question = console.input("[bold]Research question:[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Aborted.[/yellow]")
            return 130
    if not question:
        console.print("[red]No question provided.[/red]")
        return 2

    try:
        report = research(question)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    console.rule("[bold green]Report")
    console.print(Markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
