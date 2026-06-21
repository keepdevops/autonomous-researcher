"""SQLite persistence for research graphs (claims + commentary)."""
import json
import logging
import os
import sqlite3
import threading
from pathlib import Path

from research_graph.models import Claim, ClaimStatus, ResearchGraph

logger = logging.getLogger(__name__)

_DB = Path(os.environ.get("RESEARCH_GRAPH_DB", Path(__file__).resolve().parent / "graph.db"))
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS graphs ("
        "run_id TEXT PRIMARY KEY, question TEXT, graph_json TEXT, updated REAL)"
    )
    _conn = conn
    return conn


def save(graph: ResearchGraph) -> None:
    import time

    payload = graph.model_dump(mode="json")
    try:
        with _lock:
            _connect().execute(
                "INSERT INTO graphs(run_id, question, graph_json, updated) VALUES(?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET question=excluded.question, "
                "graph_json=excluded.graph_json, updated=excluded.updated",
                (graph.run_id, graph.question, json.dumps(payload), time.time()),
            )
        _emit_save(graph.run_id, len(graph.claims))
    except sqlite3.Error as exc:
        logger.error("research_graph save failed: %s", exc)


def _emit_save(run_id: str, claim_count: int) -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.GRAPH,
                kind=EventKind.STORAGE,
                run_id=run_id,
                status="saved",
                metadata={"claims": claim_count},
            )
        )
    except Exception:
        pass


def load(run_id: str) -> ResearchGraph:
    with _lock:
        row = _connect().execute(
            "SELECT graph_json FROM graphs WHERE run_id=?", (run_id,)
        ).fetchone()
    if not row:
        raise KeyError(f"no research graph for {run_id!r}")
    return ResearchGraph.model_validate(json.loads(row[0]))


def upsert_claim(run_id: str, claim: Claim) -> None:
    graph = load(run_id) if _exists(run_id) else ResearchGraph(run_id=run_id, question="")
    for i, c in enumerate(graph.claims):
        if c.id == claim.id:
            graph.claims[i] = claim
            break
    else:
        graph.claims.append(claim)
    save(graph)


def _exists(run_id: str) -> bool:
    with _lock:
        row = _connect().execute(
            "SELECT 1 FROM graphs WHERE run_id=?", (run_id,)
        ).fetchone()
    return row is not None
