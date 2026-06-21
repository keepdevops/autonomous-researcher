"""Plan A entrypoint: orchestrated research with internet retrieval."""
import asyncio
import logging
import uuid

from orchestrator import checkpoint
from orchestrator.executor import execute
from orchestrator.plans.research import build_graph
from orchestrator.state import RunState, Status

logger = logging.getLogger(__name__)


def run_research_plan(question: str, run_id: str | None = None) -> str:
    from observer import ensure, publish
    from observer.events import Component, EventKind, SystemEvent

    ensure()
    run_id = run_id or uuid.uuid4().hex[:8]
    state = RunState(run_id=run_id, goal=question)
    publish(
        SystemEvent(
            component=Component.RESEARCHER,
            kind=EventKind.LIFECYCLE,
            status="plan_a_start",
            run_id=run_id,
            detail=question[:200],
        )
    )
    graph = build_graph()
    state = asyncio.run(execute(graph, state))

    failed = [n for n, s in state.steps.items() if s.status == Status.FAILED]
    if failed:
        raise RuntimeError(
            f"Research run {run_id} paused at {failed}. "
            f"Resume with: python -m orchestrator.cli resume {run_id}"
        )

    report = state.scratch.get("final_report", "")
    fin = state.steps.get("finalize")
    if not report and fin and fin.output:
        report = fin.output.get("report", "")
    if not report:
        raise RuntimeError(f"Research run {run_id} produced no report")
    publish(
        SystemEvent(
            component=Component.RESEARCHER,
            kind=EventKind.LIFECYCLE,
            status="plan_a_complete",
            run_id=run_id,
            metadata={"chars": len(report)},
        )
    )
    logger.info("Plan A research complete run_id=%s", run_id)
    return report
