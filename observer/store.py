"""Durable SQLite backing store for system events."""
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from observer.events import Component, SystemEvent

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).resolve().parent / "system_events.db"
DB_PATH = os.environ.get("OBSERVER_DB", str(_DEFAULT_DB))
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, component TEXT, kind TEXT, "
        "run_id TEXT, step TEXT, status TEXT, detail TEXT, metadata_json TEXT)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_system_events_run_ts "
        "ON system_events(run_id, ts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_system_events_component_ts "
        "ON system_events(component, ts)"
    )
    _conn = conn
    return conn


def persist(event: SystemEvent) -> None:
    ts = event.ts if event.ts is not None else time.time()
    meta = json.dumps(event.metadata, ensure_ascii=False) if event.metadata else ""
    try:
        with _lock:
            _connect().execute(
                "INSERT INTO system_events"
                "(ts, component, kind, run_id, step, status, detail, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    ts,
                    event.component.value,
                    event.kind.value,
                    event.run_id,
                    event.step,
                    event.status,
                    event.detail,
                    meta,
                ),
            )
    except sqlite3.Error as exc:
        logger.error("observer store persist failed: %s", exc)


def list_events(
    *,
    run_id: str | None = None,
    component: Component | None = None,
    limit: int = 200,
) -> list[tuple]:
    clauses: list[str] = []
    params: list[object] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if component:
        clauses.append("component = ?")
        params.append(component.value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with _lock:
        return _connect().execute(
            f"SELECT ts, component, kind, step, status, detail, metadata_json "
            f"FROM system_events {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()


def tail_events(since_id: int = 0, limit: int = 100) -> list[tuple]:
    with _lock:
        return _connect().execute(
            "SELECT id, ts, component, kind, run_id, step, status, detail "
            "FROM system_events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (since_id, limit),
        ).fetchall()


def latest_event_id() -> int:
    with _lock:
        row = _connect().execute("SELECT MAX(id) FROM system_events").fetchone()
    return int(row[0] or 0)
