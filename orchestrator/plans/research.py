"""Plan A research plan: internet retrieval → ingest → cite → verify."""
import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.llm import chat
from ingest import ingest_document
from orchestrator.fsm import RunPhase
from orchestrator.graph import Graph, Step
from orchestrator.state import RunState
from research_graph.models import Claim, ResearchGraph
from research_graph import store as graph_store
from tools import search_web, fetch_and_ingest_url

logger = logging.getLogger(__name__)

MAX_URLS = int(__import__("os").getenv("RESEARCH_MAX_URLS", "6"))
MAX_SEARCH_RESULTS = int(__import__("os").getenv("RESEARCH_SEARCH_RESULTS", "8"))

ORDER = [
    "plan", "search", "ingest", "synthesize", "verify", "critique", "finalize",
]


AGENT_FOR_STEP = {
    "plan": "planner",
    "search": "researcher",
    "ingest": "researcher",
    "synthesize": "synthesizer",
    "verify": "verifier",
    "critique": "critic",
    "finalize": "publisher",
}


def _observe_agent(state: RunState, step: str, status: str, detail: str = "") -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.RESEARCHER,
                kind=EventKind.STEP,
                run_id=state.run_id,
                step=step,
                status=status,
                detail=detail,
                metadata={"agent": AGENT_FOR_STEP.get(step, step)},
            )
        )
    except Exception:
        pass


def _observe_phase(state: RunState, phase: RunPhase) -> None:
    state.set_phase(phase.value)
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.RESEARCHER,
                kind=EventKind.STEP,
                run_id=state.run_id,
                step=phase.value,
                status="phase",
                detail=state.goal[:120],
                metadata={"phase": phase.value},
            )
        )
    except Exception:
        pass


def step_plan(state: RunState) -> dict:
    _observe_agent(state, "plan", "start")
    _observe_phase(state, RunPhase.PLANNING)
    prompt = (
        f"Research goal: {state.goal}\n\n"
        "Return JSON only: {\"queries\": [\"q1\", \"q2\", \"q3\"]} with 2-3 web search queries."
    )
    raw = chat(prompt, system="You plan web research. Output valid JSON only.", max_tokens=256)
    queries = [state.goal]
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            queries = json.loads(m.group()).get("queries") or queries
    except json.JSONDecodeError:
        logger.warning("planner returned non-JSON; using goal as sole query")
    _observe_agent(state, "plan", "done", detail=f"{len(queries)} queries")
    return {"queries": queries[:3]}


def step_search(state: RunState) -> dict:
    _observe_agent(state, "search", "start")
    _observe_phase(state, RunPhase.RESEARCHING)
    queries = (state.steps["plan"].output or {}).get("queries", [state.goal])
    hits: list[dict] = []
    seen: set[str] = set()
    for q in queries:
        for row in search_web({"query": q, "num_results": MAX_SEARCH_RESULTS}):
            url = row.get("url", "")
            if url and url not in seen:
                seen.add(url)
                hits.append(row)
    _observe_agent(state, "search", "done", detail=f"{len(hits)} hits")
    return {"hits": hits[: MAX_URLS * 2]}


def _ingest_one(hit: dict) -> list[dict]:
    url = hit.get("url", "")
    if not url:
        return []
    try:
        chunks = fetch_and_ingest_url(url, title=hit.get("title"))
        return [c.to_dict() for c in chunks]
    except Exception as exc:
        logger.warning("ingest failed for %s: %s", url, exc)
        return []


def step_ingest(state: RunState) -> dict:
    _observe_agent(state, "ingest", "start")
    hits = (state.steps["search"].output or {}).get("hits", [])[:MAX_URLS]
    all_chunks: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_ingest_one, h): h for h in hits}
        for fut in as_completed(futures):
            all_chunks.extend(fut.result())
    state.add_chunks(all_chunks)
    try:
        from retrieval import index_chunks

        index_chunks(all_chunks, run_id=state.run_id)
    except Exception as exc:
        logger.debug("retrieval index skipped: %s", exc)
    _observe_agent(state, "ingest", "done", detail=f"{len(all_chunks)} chunks")
    return {"url_count": len(hits), "chunk_count": len(all_chunks)}


def _chunk_context(chunks: list[dict], limit: int = 12) -> str:
    lines = []
    for ch in chunks[:limit]:
        meta = ch.get("metadata") or {}
        lines.append(
            f"[{ch['id']}] ({meta.get('source_url', '?')}) "
            f"{meta.get('section') or ''}: {ch['text'][:600]}"
        )
    return "\n\n".join(lines)


def step_synthesize(state: RunState) -> dict:
    _observe_agent(state, "synthesize", "start")
    _observe_phase(state, RunPhase.SYNTHESIZING)
    chunks = state.chunks()
    try:
        from retrieval import search_chunks

        recall = search_chunks(state.goal, run_id=state.run_id, k=6)
        seen = {c["id"] for c in chunks}
        for hit in recall:
            if hit["id"] not in seen:
                chunks.append(hit)
                seen.add(hit["id"])
        if recall:
            _observe_agent(state, "synthesize", "recall", detail=f"{len(recall)} librarian hits")
    except Exception as exc:
        logger.debug("librarian recall skipped: %s", exc)
    if not chunks:
        raise RuntimeError("no ingested chunks — check SearXNG and network")
    ctx = _chunk_context(chunks)
    prompt = (
        f"Question: {state.goal}\n\nSources:\n{ctx}\n\n"
        "Write a cited markdown report. Then on new lines output JSON:\n"
        "{\"claims\": [{\"id\": \"C1\", \"text\": \"...\", \"chunk_ids\": [\"...\"], "
        "\"urls\": [\"...\"]}]}"
    )
    raw = chat(
        prompt,
        system="Expert researcher. Cite sources with markdown links. Be factual.",
        max_tokens=4096,
    )
    report, claims_raw = raw, "[]"
    if "{" in raw:
        idx = raw.rfind("{")
        report = raw[:idx].strip()
        claims_raw = raw[idx:]
    claims: list[Claim] = []
    try:
        parsed = json.loads(re.search(r"\{.*\}", claims_raw, re.DOTALL).group())
        for row in parsed.get("claims", []):
            claims.append(
                Claim(
                    id=str(row.get("id", uuid.uuid4().hex[:4])),
                    text=str(row.get("text", "")),
                    source_chunk_ids=list(row.get("chunk_ids") or []),
                    source_urls=list(row.get("urls") or []),
                )
            )
    except (json.JSONDecodeError, AttributeError):
        claims = [Claim(id="C1", text=report[:200], source_urls=[])]
    graph = ResearchGraph(run_id=state.run_id, question=state.goal, claims=claims)
    graph_store.save(graph)
    _observe_agent(state, "synthesize", "done", detail=f"{len(claims)} claims")
    return {"report": report, "claim_count": len(claims)}


def step_verify(state: RunState) -> dict:
    _observe_agent(state, "verify", "start")
    _observe_phase(state, RunPhase.VERIFYING)
    from research_graph.commentary import add_commentary
    from research_graph.verify import verify_graph

    graph = graph_store.load(state.run_id)
    chunks = {c["id"]: c for c in state.chunks()}
    graph, unsupported = verify_graph(graph, chunks)
    graph_store.save(graph)
    _observe_agent(state, "verify", "done", detail=f"unsupported={unsupported}")
    return {"unsupported": unsupported, "total": len(graph.claims)}


def step_critique(state: RunState) -> dict:
    _observe_agent(state, "critique", "start")
    _observe_phase(state, RunPhase.CRITIQUE)
    graph = graph_store.load(state.run_id)
    graph = add_commentary(graph)
    graph_store.save(graph)
    _observe_agent(state, "critique", "done")
    return {"commentary_added": sum(1 for c in graph.claims if c.commentary)}


def step_finalize(state: RunState) -> dict:
    _observe_agent(state, "finalize", "start")
    _observe_phase(state, RunPhase.DONE)
    import os

    verify_step = state.steps.get("verify")
    verify_out = (verify_step.output if verify_step else None) or {}
    unsupported = int(verify_out.get("unsupported") or 0)
    allow = os.getenv("RESEARCH_ALLOW_UNVERIFIED", "").lower() in ("1", "true", "yes")
    if unsupported and not allow:
        raise RuntimeError(
            f"{unsupported} unsupported claim(s). "
            "Set RESEARCH_ALLOW_UNVERIFIED=1 to publish anyway."
        )
    report = (state.steps["synthesize"].output or {}).get("report", "")
    graph = graph_store.load(state.run_id)
    footer = ["\n\n---\n## Claim verification"]
    for c in graph.claims:
        mark = c.status.value
        note = f" — {c.commentary}" if c.commentary else ""
        urls = ", ".join(c.source_urls) if c.source_urls else "no url"
        footer.append(f"- **[{c.id}]** ({mark}) {c.text[:120]}… [{urls}]{note}")
    final = report + "\n".join(footer)
    state.scratch["final_report"] = final
    _observe_agent(state, "finalize", "done", detail=f"{len(final)} chars")
    return {"report": final, "chars": len(final)}


def build_graph() -> Graph:
    steps = [
        Step("plan", step_plan, on_failure="pause"),
        Step("search", step_search, deps=["plan"], on_failure="degrade"),
        Step("ingest", step_ingest, deps=["search"], on_failure="degrade"),
        Step("synthesize", step_synthesize, deps=["ingest"], on_failure="pause"),
        Step("verify", step_verify, deps=["synthesize"], on_failure="skip"),
        Step("critique", step_critique, deps=["verify"], on_failure="skip"),
        Step("finalize", step_finalize, deps=["critique"]),
    ]
    return Graph(steps, order=ORDER)
