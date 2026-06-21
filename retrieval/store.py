"""SQLite chunk index for Plan A retrieval (librarian role)."""
import json
import logging
import os
import re
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = Path(os.environ.get("RETRIEVAL_DB", Path(__file__).resolve().parent / "chunks.db"))
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
        "CREATE TABLE IF NOT EXISTS chunks ("
        "id TEXT PRIMARY KEY, run_id TEXT, text TEXT, metadata_json TEXT)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_run ON chunks(run_id)")
    _conn = conn
    return conn


def _observe(status: str, **meta) -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.RETRIEVAL,
                kind=EventKind.STORAGE,
                status=status,
                metadata=meta,
            )
        )
    except Exception:
        pass


def index_chunks(chunks: list[dict], *, run_id: str = "") -> int:
    if not chunks:
        return 0
    with _lock:
        conn = _connect()
        for ch in chunks:
            meta = ch.get("metadata") or {}
            conn.execute(
                "INSERT OR REPLACE INTO chunks(id, run_id, text, metadata_json) VALUES(?,?,?,?)",
                (ch["id"], run_id, ch["text"], json.dumps(meta)),
            )
    _observe("indexed", run_id=run_id, count=len(chunks))
    logger.info("indexed %d chunks for run %s", len(chunks), run_id or "-")
    return len(chunks)


def search_chunks(query: str, *, run_id: str = "", k: int = 8) -> list[dict]:
    terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2][:12]
    if not terms:
        return []
    with _lock:
        if run_id:
            rows = _connect().execute(
                "SELECT id, text, metadata_json FROM chunks WHERE run_id=?",
                (run_id,),
            ).fetchall()
        else:
            rows = _connect().execute(
                "SELECT id, text, metadata_json FROM chunks ORDER BY rowid DESC LIMIT 500"
            ).fetchall()
    scored: list[tuple[int, dict]] = []
    for cid, text, meta_json in rows:
        lower = text.lower()
        score = sum(1 for t in terms if t in lower)
        if score:
            scored.append(
                (
                    score,
                    {
                        "id": cid,
                        "text": text,
                        "metadata": json.loads(meta_json) if meta_json else {},
                        "score": score,
                    },
                )
            )
    scored.sort(key=lambda x: -x[0])
    hits = [row for _, row in scored[:k]]
    _observe("search", query=query[:80], run_id=run_id, hits=len(hits))
    return hits
