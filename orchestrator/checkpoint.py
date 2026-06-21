import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from orchestrator.state import RunState

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "RESEARCH_RUNS_DB",
    str(Path(__file__).resolve().parents[1] / "research_runs.db"),
)
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
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
    _conn = conn
    return conn


def save(state: RunState) -> None:
    payload = json.dumps(state.model_dump(mode="json"))
    with _lock:
        _connect().execute(
            "INSERT INTO runs(run_id, goal, state_json, updated) VALUES(?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET goal=excluded.goal, "
            "state_json=excluded.state_json, updated=excluded.updated",
            (state.run_id, state.goal, payload, time.time()),
        )


def load(run_id: str) -> RunState:
    with _lock:
        row = _connect().execute(
            "SELECT state_json FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
    if not row:
        raise KeyError(f"no checkpoint for run_id {run_id!r}")
    return RunState.model_validate(json.loads(row[0]))


def emit(run_id: str, step: str, status: str, detail: str = "") -> None:
    ts = time.time()
    try:
        from observer.events import Component, EventKind, SystemEvent
        from observer.hub import publish

        publish(
            SystemEvent(
                component=Component.ORCHESTRATOR,
                kind=EventKind.STEP,
                run_id=run_id,
                step=step,
                status=status,
                detail=detail,
                ts=ts,
            )
        )
    except Exception as exc:
        logger.debug("observer publish skipped: %s", exc)
    try:
        with _lock:
            _connect().execute(
                "INSERT INTO events(run_id, step, status, detail, ts) VALUES(?,?,?,?,?)",
                (run_id, step, status, detail, ts),
            )
    except sqlite3.Error as exc:
        logger.error("event emit failed: %s", exc)


def events(run_id: str, limit: int = 200) -> list[tuple]:
    with _lock:
        return _connect().execute(
            "SELECT ts, step, status, detail FROM events WHERE run_id=? "
            "ORDER BY id ASC LIMIT ?",
            (run_id, limit),
        ).fetchall()
