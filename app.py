"""FastAPI front end for the autonomous researcher."""

import json
import logging
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from main import LLM_BASE_URL, research

try:
    from observer import ensure, store as observer_store
    ensure()
except Exception:
    observer_store = None

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")
STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
MONITOR_HTML = STATIC_DIR / "monitor.html"

app = FastAPI(title="Autonomous Researcher", version="2.0.0")


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


class ResearchResponse(BaseModel):
    report: str


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    if not INDEX_HTML.is_file():
        raise HTTPException(status_code=500, detail="index.html not found")
    return FileResponse(INDEX_HTML)


@app.get("/monitor", include_in_schema=False)
async def monitor_page() -> FileResponse:
    if not MONITOR_HTML.is_file():
        raise HTTPException(status_code=500, detail="monitor.html not found")
    return FileResponse(MONITOR_HTML)


@app.get("/api/health")
async def health() -> dict:
    health_url = f"{LLM_BASE_URL.rstrip('/').removesuffix('/v1')}/health"
    llm_ok = searx_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(health_url)
        llm_ok = resp.status_code == 200
    except httpx.HTTPError as exc:
        logger.error("health llm: %s", exc)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(SEARXNG_URL)
        searx_ok = resp.status_code < 500
    except httpx.HTTPError as exc:
        logger.error("health searxng: %s", exc)
    return {
        "status": "ok",
        "mode": os.getenv("RESEARCH_MODE", "plan_a"),
        "llm_reachable": llm_ok,
        "searxng_reachable": searx_ok,
        "llm_base_url": LLM_BASE_URL,
        "searxng_url": SEARXNG_URL,
    }


@app.get("/api/events/stream")
async def events_stream(since: int = 0):
    if observer_store is None:
        raise HTTPException(status_code=503, detail="observer not available")

    async def generate():
        last = since
        import asyncio

        while True:
            rows = observer_store.tail_events(since_id=last, limit=50)
            for row in rows:
                eid, ts, component, kind, run_id, step, status, detail = row
                last = eid
                payload = {
                    "id": eid,
                    "ts": ts,
                    "component": component,
                    "kind": kind,
                    "run_id": run_id,
                    "step": step,
                    "status": status,
                    "detail": detail,
                }
                yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/graph/{run_id}")
async def get_graph(run_id: str) -> dict:
    try:
        from research_graph import store as graph_store

        return graph_store.load(run_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/research", response_model=ResearchResponse)
async def run_research(req: ResearchRequest) -> ResearchResponse:
    question = req.question.strip()
    logger.info("research request: %r", question[:120])
    try:
        report = await run_in_threadpool(research, question)
    except RuntimeError as exc:
        logger.error("research failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("research crashed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal error during research") from exc
    return ResearchResponse(report=report)
