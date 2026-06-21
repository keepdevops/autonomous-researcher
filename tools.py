import json
import os
import logging
from pathlib import Path
from typing import Callable, Dict, List

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator
from rich.console import Console

from http_client import default_headers, url_allowed

console = Console()
logger = logging.getLogger(__name__)

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
# Cap extracted page text so a single read_url can't overflow the LLM context.
# ~12k chars ≈ ~3k tokens, leaving room for history within an 8k window.
READ_URL_MAX_CHARS = int(os.getenv("READ_URL_MAX_CHARS", "12000"))


class SearchQuery(BaseModel):
    query: str = Field(..., description="Exact search query string")
    num_results: int = Field(8, ge=1, le=15, description="Number of results, max 15")


class ReadUrl(BaseModel):
    url: str = Field(..., description="Full URL to fetch and extract clean text from")


class IngestFile(BaseModel):
    path: str = Field(..., description="Relative path to a local file to ingest")


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
            "name": "ingest_file",
            "description": "Ingest a local file (pdf, md, code, text) into Plan A chunks.",
            "parameters": IngestFile.model_json_schema(),
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


def fetch_url_html(url: str) -> tuple[str, str | None]:
    """Fetch raw HTML and page title."""
    if not url_allowed(url):
        raise ValueError(f"URL blocked by RESEARCH_URL_ALLOWLIST: {url}")
    resp = httpx.get(
        url,
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers=default_headers(),
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    return resp.text, title


def fetch_and_ingest_url(url: str, title: str | None = None):
    """Fetch a URL from the internet and return Plan A ingest chunks."""
    from ingest import ingest_document

    html, page_title = fetch_url_html(url)
    return ingest_document(
        html,
        doc_type="web",
        source_url=url,
        title=title or page_title,
    )


def read_url(args: dict) -> str:
    """Fetch a webpage, ingest into chunks, return excerpt for the agent."""
    params = ReadUrl.model_validate(args)
    try:
        chunks = fetch_and_ingest_url(params.url)
    except httpx.HTTPError as exc:
        logger.error("read_url failed for %r: %s", params.url, exc)
        raise RuntimeError(f"Fetch failed: {exc}") from exc

    if not chunks:
        return "(empty page)"
    preview = []
    for ch in chunks[:5]:
        meta = ch.metadata
        header = meta.section or meta.title or params.url
        preview.append(f"### {header} [{ch.id}]\n{ch.text[:800]}")
    body = "\n\n".join(preview)
    if len(chunks) > 5:
        body += f"\n\n[...{len(chunks) - 5} more chunks ingested...]"
    return body


def ingest_file(args: dict) -> str:
    params = IngestFile.model_validate(args)
    resolved = Path(params.path).resolve()
    cwd = Path.cwd().resolve()
    if ".." in Path(params.path).parts or not str(resolved).startswith(str(cwd)):
        raise ValueError("Path traversal attempt blocked")
    chunks = ingest_path(str(resolved))
    preview = [f"[{c.id}] {c.text[:400]}" for c in chunks[:5]]
    return json.dumps({"chunk_count": len(chunks), "preview": preview}, ensure_ascii=False)


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
    "ingest_file": ingest_file,
    "write_file": write_file,
}


def _observe_tool(name: str, status: str, detail: str = "", **metadata) -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.TOOLS,
                kind=EventKind.TOOL,
                step=name,
                status=status,
                detail=detail,
                metadata=metadata,
            )
        )
    except Exception as exc:
        logger.debug("observer emit skipped: %s", exc)


def dispatch_tool(name: str, args: dict) -> object:
    """Route a tool call by name to its implementation. Fails loudly on unknown names."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        logger.error("dispatch_tool: unknown tool %r", name)
        _observe_tool(name, "unknown", f"Unknown tool: {name}")
        raise ValueError(f"Unknown tool: {name}")
    _observe_tool(name, "start", metadata=args)
    try:
        result = fn(args)
    except Exception as exc:
        _observe_tool(name, "failed", str(exc), metadata=args)
        raise
    _observe_tool(name, "ok", metadata={"args": args, "result_type": type(result).__name__})
    return result
