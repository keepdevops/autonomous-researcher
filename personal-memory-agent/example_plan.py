"""A 12-step demo plan exercising every executor feature.

Topology:
    intake -> triage(router) --deep--> expand -> [search_a|search_b|search_c]
                                                       \\  parallel fan-out  /
                                                        -> dedupe(step 7) -> synthesize -> critique
              triage --quick--> quick_note                                                     |
                                                                            finalize(join_any) <-
                                                                                   |
                                                                            persist(approval gate)

Demonstrates: branching (triage), parallelism+merge (search_a/b/c -> dedupe),
persistence/resume (dedupe fails on attempt 1 -> the "7 of 12"), reconverge
(finalize join_any), and intervention (persist requires approval).
"""
import logging
import os
import time

import httpx

from graph import Graph, Step
from memory import add_memory
from state import RunState

logger = logging.getLogger(__name__)

CHAT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8081/v1")
ORDER = [
    "intake", "triage", "expand", "search_a", "search_b", "search_c",
    "dedupe", "synthesize", "critique", "quick_note", "finalize", "persist",
]


def _llm(prompt: str, max_tokens: int = 256) -> str:
    try:
        resp = httpx.post(
            f"{CHAT_BASE_URL}/chat/completions",
            json={"model": "local", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": max_tokens},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.error("LLM call failed: %s", e)
        raise


# --- step bodies -----------------------------------------------------------
def intake(s: RunState) -> dict:
    return {"goal": s.goal}

def triage(s: RunState) -> dict:
    # Router decision. Deterministic here; could be an LLM classification.
    mode = "quick" if len(s.goal) < 25 else "deep"
    return {"decision": mode}

def expand(s: RunState) -> dict:
    return {"queries": [f"{s.goal} — angle {i}" for i in range(1, 4)]}

def _search(angle: str):
    def _do(s: RunState) -> dict:
        time.sleep(1.0)  # simulate I/O; runs concurrently with sibling searches
        return {"angle": angle, "hits": [f"result {angle}-{i}" for i in range(2)]}
    return _do

def dedupe(s: RunState) -> dict:
    # Fails on the first attempt to demonstrate resume-at-7.
    if s.steps["dedupe"].attempts < 2:
        raise RuntimeError("transient: dedupe index not warm yet")
    hits = []
    for branch in ("search_a", "search_b", "search_c"):
        hits += (s.steps[branch].output or {}).get("hits", [])
    return {"unique": sorted(set(hits))}

def synthesize(s: RunState) -> dict:
    facts = (s.steps["dedupe"].output or {}).get("unique", [])
    text = _llm(f"In 2 sentences, summarize findings for goal {s.goal!r}: {facts}")
    return {"summary": text}

def critique(s: RunState) -> dict:
    return {"ok": True, "notes": "summary reviewed"}

def quick_note(s: RunState) -> dict:
    return {"summary": f"(quick) {s.goal}"}

def finalize(s: RunState) -> dict:
    # Whichever branch ran has the summary: deep -> synthesize, quick -> quick_note.
    deep = s.steps["synthesize"].output
    quick = s.steps["quick_note"].output
    return {"final": (deep or quick or {}).get("summary", "(no summary)")}

def persist(s: RunState) -> dict:
    summary = (s.steps["finalize"].output or {}).get("final", "")
    mid = add_memory("assistant", f"[run {s.run_id}] {summary}", {"type": "run_result"})
    return {"memory_id": mid}


def build_graph() -> Graph:
    steps = [
        Step("intake", intake),
        Step("triage", triage, deps=["intake"],
             choose=lambda s: {"expand"} if s.steps["triage"].output["decision"] == "deep"
                              else {"quick_note"}),
        Step("expand", expand, deps=["triage"]),
        Step("search_a", _search("a"), deps=["expand"]),
        Step("search_b", _search("b"), deps=["expand"]),
        Step("search_c", _search("c"), deps=["expand"]),
        Step("dedupe", dedupe, deps=["search_a", "search_b", "search_c"]),
        Step("synthesize", synthesize, deps=["dedupe"]),
        Step("critique", critique, deps=["synthesize"]),
        Step("quick_note", quick_note, deps=["triage"]),
        Step("finalize", finalize, deps=["critique", "quick_note"], join_any=True),
        Step("persist", persist, deps=["finalize"], requires_approval=True),
    ]
    return Graph(steps, order=ORDER)
