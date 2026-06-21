"""SQLite checkpoint + event store for runs.

Two tables, one local file (runs.db). `runs` holds the latest serialized
RunState per run_id (resume source of truth). `events` is an append-only trace
of every transition (observability). SQLite gives atomic, server-free durability
-- distinct from the Qdrant *memory* store, which holds chat recall, not run state.
"""
import json
import logging
import os
import sqlite3
import threading
import time

from state import RunState

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("RUNS_DB", os.path.join(os.path.dirname(__file__), "runs.db"))
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS runs ("
        "run_id TEXT PRIMARY KEY, goal TEXT, state_json TEXT, updated REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, step TEXT, "
        "status TEXT, detail TEXT, ts REAL)"
    )
    return conn


_conn = _connect()


def save(state: RunState) -> None:
    """Persist the full RunState. Called after every transition."""
    payload = json.dumps(state.model_dump(mode="json"))
    try:
        with _lock:
            _conn.execute(
                "INSERT INTO runs(run_id, goal, state_json, updated) VALUES(?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET goal=excluded.goal, "
                "state_json=excluded.state_json, updated=excluded.updated",
                (state.run_id, state.goal, payload, time.time()),
            )
    except sqlite3.Error as e:
        logger.error("Checkpoint save failed for run %s: %s", state.run_id, e)
        raise


def load(run_id: str) -> RunState:
    try:
        with _lock:
            row = _conn.execute(
                "SELECT state_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
    except sqlite3.Error as e:
        logger.error("Checkpoint load failed for run %s: %s", run_id, e)
        raise
    if not row:
        raise KeyError(f"no checkpoint for run_id {run_id!r}")
    return RunState.model_validate(json.loads(row[0]))


def list_runs() -> list[tuple[str, str, float]]:
    with _lock:
        rows = _conn.execute(
            "SELECT run_id, goal, updated FROM runs ORDER BY updated DESC"
        ).fetchall()
    return rows


def emit(run_id: str, step: str, status: str, detail: str = "") -> None:
    """Append one trace event. Failures here must never abort a run."""
    try:
        with _lock:
            _conn.execute(
                "INSERT INTO events(run_id, step, status, detail, ts) VALUES(?,?,?,?,?)",
                (run_id, step, status, detail, time.time()),
            )
    except sqlite3.Error as e:
        logger.error("Event emit failed (%s/%s): %s", run_id, step, e)


def events(run_id: str, limit: int = 200) -> list[tuple]:
    with _lock:
        return _conn.execute(
            "SELECT ts, step, status, detail FROM events WHERE run_id=? "
            "ORDER BY id ASC LIMIT ?",
            (run_id, limit),
        ).fetchall()
