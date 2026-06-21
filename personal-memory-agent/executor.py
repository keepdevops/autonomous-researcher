"""Durable async executor for a task Graph.

The walk, each tick:
  1. Find the ready frontier: PENDING steps whose deps are satisfied.
  2. Steps marked requires_approval (and not yet approved) -> AWAITING_APPROVAL,
     then PAUSE (return) so a human can intervene.
  3. Run the frontier concurrently (asyncio + threads; steps stay plain sync
     functions, so they reuse the existing sync httpx/Qdrant clients).
  4. Record DONE/FAILED, propagate branch skips, checkpoint after each.
  5. On any FAILED step, PAUSE so the failure can be inspected and resumed.

Resume = load the checkpoint and call execute() again: DONE/SKIPPED steps are
left alone, so a run that died at "7 of 12" picks up at step 7.
"""
import asyncio
import logging

import checkpoint
from graph import Graph
from state import RunState, StepState, Status, SETTLED

logger = logging.getLogger(__name__)


class Paused(Exception):
    """Internal signal: the run cannot make progress without a human."""


def _ensure_states(graph: Graph, state: RunState) -> None:
    for name in graph.steps:
        state.steps.setdefault(name, StepState(name=name))


def _deps_done(graph: Graph, state: RunState, name: str) -> bool:
    step = graph.steps[name]
    dep_status = [state.steps[d].status for d in step.deps]
    if step.join_any:
        if not step.deps:
            return True
        if any(s == Status.DONE for s in dep_status):
            return all(s in SETTLED for s in dep_status)  # winners landed, losers skipped
        return False
    return all(s == Status.DONE for s in dep_status)


def _ready(graph: Graph, state: RunState) -> list[str]:
    return [
        n for n in graph.order
        if state.steps[n].status == Status.PENDING and _deps_done(graph, state, n)
    ]


def _skip(graph: Graph, state: RunState, name: str) -> None:
    """Skip a step and any descendant that can no longer be reached."""
    st = state.steps[name]
    if st.status not in (Status.PENDING,):
        return
    st.status = Status.SKIPPED
    checkpoint.emit(state.run_id, name, st.status.value, "branch not taken")
    for child in graph.successors(name):
        cstep = graph.steps[child]
        dep_status = [state.steps[d].status for d in cstep.deps]
        if cstep.join_any:
            if all(s == Status.SKIPPED for s in dep_status):
                _skip(graph, state, child)
        elif Status.SKIPPED in dep_status:
            _skip(graph, state, child)


def _apply_routing(graph: Graph, state: RunState, name: str) -> None:
    step = graph.steps[name]
    if step.choose is None:
        return
    successors = set(graph.successors(name))
    keep = set(step.choose(state)) & successors
    for loser in successors - keep:
        _skip(graph, state, loser)


def _run_sync(step, state: RunState) -> dict:
    """Executed inside a worker thread; returns the step's output dict."""
    out = step.run(state)
    if not isinstance(out, dict):
        raise TypeError(f"step {step.name!r} must return a dict, got {type(out).__name__}")
    return out


async def execute(graph: Graph, state: RunState) -> RunState:
    _ensure_states(graph, state)
    checkpoint.save(state)

    while True:
        ready = _ready(graph, state)
        if not ready:
            break

        # Intervention gates: pause before running an unapproved gated step.
        gated = [n for n in ready if graph.steps[n].requires_approval and not state.approved(n)]
        if gated:
            for n in gated:
                state.steps[n].status = Status.AWAITING_APPROVAL
                checkpoint.emit(state.run_id, n, "awaiting_approval", "needs human approval")
            checkpoint.save(state)
            logger.info("Run %s paused for approval: %s", state.run_id, gated)
            return state

        # Mark RUNNING + checkpoint before doing any work (write-ahead).
        for n in ready:
            st = state.steps[n]
            st.status, st.attempts = Status.RUNNING, st.attempts + 1
            checkpoint.emit(state.run_id, n, "running", f"attempt {st.attempts}")
        checkpoint.save(state)

        # Fan out the frontier concurrently.
        results = await asyncio.gather(
            *(asyncio.to_thread(_run_sync, graph.steps[n], state) for n in ready),
            return_exceptions=True,
        )

        failed = False
        for n, res in zip(ready, results):
            st = state.steps[n]
            if isinstance(res, Exception):
                st.status, st.error = Status.FAILED, repr(res)
                logger.error("Step %s failed (attempt %d): %r", n, st.attempts, res)
                checkpoint.emit(state.run_id, n, "failed", repr(res))
                failed = True
            else:
                st.status, st.output, st.error = Status.DONE, res, None
                checkpoint.emit(state.run_id, n, "done", "")
                _apply_routing(graph, state, n)
            checkpoint.save(state)

        if failed:
            logger.info("Run %s paused after failure; resume to retry.", state.run_id)
            return state

    return state


def resume_state(graph: Graph, state: RunState) -> RunState:
    """Prep a loaded checkpoint for another execute(): clear retryable failures
    and release approved gates back to PENDING."""
    _ensure_states(graph, state)
    for st in state.steps.values():
        step = graph.steps[st.name]
        if st.status == Status.FAILED and st.attempts < step.max_attempts:
            st.status, st.error = Status.PENDING, None
        elif st.status == Status.AWAITING_APPROVAL and state.approved(st.name):
            st.status = Status.PENDING
    return state
