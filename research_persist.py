"""Optional bridge: persist Plan A reports into personal-memory-agent Qdrant."""
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def persist_research_report(run_id: str, goal: str, report: str) -> dict:
    if os.getenv("RESEARCH_PERSIST_MEMORY", "").lower() not in ("1", "true", "yes"):
        return {"persisted": False, "reason": "disabled"}
    pma = Path(__file__).resolve().parent / "personal-memory-agent"
    if str(pma) not in sys.path:
        sys.path.insert(0, str(pma))
    try:
        from memory import add_memory
    except ImportError as exc:
        logger.warning("memory persist unavailable: %s", exc)
        return {"persisted": False, "reason": str(exc)}
    body = f"[research {run_id}] Q: {goal}\n\n{report[:6000]}"
    try:
        mid = add_memory(
            "assistant",
            body,
            {"type": "research_result", "run_id": run_id},
        )
        _observe(run_id, mid)
        return {"persisted": True, "memory_id": mid}
    except Exception as exc:
        logger.warning("memory persist failed: %s", exc)
        return {"persisted": False, "reason": str(exc)}


def _observe(run_id: str, memory_id: str) -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.MEMORY,
                kind=EventKind.STORAGE,
                run_id=run_id,
                status="research_persisted",
                metadata={"memory_id": memory_id},
            )
        )
    except Exception:
        pass
