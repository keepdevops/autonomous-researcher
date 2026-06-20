import os
import logging
from pathlib import Path
from typing import Callable, Dict, List

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
# Cap extracted page text so a single read_url can't overflow the LLM context.
# ~12k chars ≈ ~3k tokens, leaving room for history within an 8k window.
READ_URL_MAX_CHARS = int(os.getenv("READ_URL_MAX_CHARS", "12000"))


class SearchQuery(BaseModel):
    query: str = Field(..., description="Exact search query string")
    num_results: int = Field(8, ge=1, le=15, description="Number of results, max 15")


class ReadUrl(BaseModel):
    url: str = Field(..., description="Full URL to fetch and extract clean text from")


class WriteFile(BaseModel):
    path: str = Field(..., description="Relative or absolute path to write")
    content: str = Field(..., description="Full content to write")

    @field_validator("path")
    @classmethod
    def prevent_path_traversal(cls, v: str) -> str:
        resolved = Path(v).resolve()
        cwd = Path.cwd().resolve()
        if ".." in Path(v).parts or not str(resolved).startswith(str(cwd)):
            raise ValueError("Path traversal attempt blocked")
        return v


TOOLS_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the internet via local SearXNG instance and return title+url+snippet.",
            "parameters": SearchQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "Fetch a webpage and return a clean markdown body.",
            "parameters": ReadUrl.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file inside the current working directory only.",
            "parameters": WriteFile.model_json_schema(),
        },
    },
]


def search_web(args: dict) -> List[Dict[str, str]]:
    """Query the local SearXNG instance and return title+url+snippet results."""
    params = SearchQuery.model_validate(args)
    try:
        resp = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": params.query, "format": "json"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("search_web failed for %r: %s", params.query, exc)
        raise RuntimeError(f"SearXNG request failed: {exc}") from exc

    results = resp.json().get("results", [])[: params.num_results]
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in results
    ]


def read_url(args: dict) -> str:
    """Fetch a webpage and return its main text as a clean markdown-ish body."""
    params = ReadUrl.model_validate(args)
    try:
        resp = httpx.get(
            params.url, timeout=HTTP_TIMEOUT, follow_redirects=True
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("read_url failed for %r: %s", params.url, exc)
        raise RuntimeError(f"Fetch failed: {exc}") from exc

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    text = "\n".join(lines)
    if len(text) > READ_URL_MAX_CHARS:
        logger.warning(
            "read_url: truncated %r from %d to %d chars",
            params.url, len(text), READ_URL_MAX_CHARS,
        )
        text = text[:READ_URL_MAX_CHARS] + "\n\n[...truncated...]"
    return text


def write_file(args: dict) -> str:
    """Write content to a file inside the current working directory only."""
    params = WriteFile.model_validate(args)
    target = Path(params.path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(params.content, encoding="utf-8")
    except OSError as exc:
        logger.error("write_file failed for %r: %s", params.path, exc)
        raise RuntimeError(f"Write failed: {exc}") from exc
    return f"Wrote {len(params.content)} chars to {params.path}"


TOOL_FUNCTIONS: Dict[str, Callable[[dict], object]] = {
    "search_web": search_web,
    "read_url": read_url,
    "write_file": write_file,
}


def dispatch_tool(name: str, args: dict) -> object:
    """Route a tool call by name to its implementation. Fails loudly on unknown names."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        logger.error("dispatch_tool: unknown tool %r", name)
        raise ValueError(f"Unknown tool: {name}")
    return fn(args)
