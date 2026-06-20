"""FastAPI front end for the autonomous researcher.

Serves a single-page UI (static/index.html) and exposes the same research()
agent loop used by the CLI over a JSON API. The agent loop is synchronous and
long-running, so it is dispatched to a worker thread to avoid blocking the
event loop.
"""

import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from main import LLM_BASE_URL, research

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

app = FastAPI(title="Autonomous Researcher", version="1.0.0")


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000, description="Research question")


class ResearchResponse(BaseModel):
    report: str = Field(..., description="Final cited markdown report")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the single-page UI."""
    if not INDEX_HTML.is_file():
        logger.error("index.html missing at %s", INDEX_HTML)
        raise HTTPException(status_code=500, detail="UI asset index.html not found")
    return FileResponse(INDEX_HTML)


@app.get("/api/health")
async def health() -> dict:
    """Report whether the backing LLM server is reachable."""
    health_url = f"{LLM_BASE_URL.rstrip('/').removesuffix('/v1')}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(health_url)
        llm_ok = resp.status_code == 200
    except httpx.HTTPError as exc:
        logger.error("health: LLM unreachable at %s: %s", health_url, exc)
        llm_ok = False
    return {"status": "ok", "llm_reachable": llm_ok, "llm_base_url": LLM_BASE_URL}


@app.post("/api/research", response_model=ResearchResponse)
async def run_research(req: ResearchRequest) -> ResearchResponse:
    """Run the agent loop for one question and return the final report."""
    question = req.question.strip()
    logger.info("research request: %r", question[:120])
    try:
        report = await run_in_threadpool(research, question)
    except RuntimeError as exc:
        # research() raises RuntimeError for LLM/upstream failures — 502, not 500.
        logger.error("research failed for %r: %s", question[:120], exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # never swallow: log and surface a generic 500
        logger.error("research crashed for %r: %s", question[:120], exc)
        raise HTTPException(status_code=500, detail="Internal error during research") from exc
    return ResearchResponse(report=report)
