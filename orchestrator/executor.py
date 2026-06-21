import asyncio
import logging

from orchestrator import checkpoint
from orchestrator.graph import Graph
from orchestrator.state import RunState, StepState, Status, SETTLED

logger = logging.getLogger(__name__)


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
            return all(s in SETTLED for s in dep_status)
        return False
    return all(s == Status.DONE for s in dep_status)


def _ready(graph: Graph, state: RunState) -> list[str]:
    return [
        n for n in graph.order
        if state.steps[n].status == Status.PENDING and _deps_done(graph, state, n)
    ]


def _skip(graph: Graph, state: RunState, name: str) -> None:
    st = state.steps[name]
    if st.status != Status.PENDING:
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
    keep = set(step.choose(state)) & set(graph.successors(name))
    for loser in set(graph.successors(name)) - keep:
        _skip(graph, state, loser)


def _run_sync(step, state: RunState) -> dict:
    out = step.run(state)
    if not isinstance(out, dict):
        raise TypeError(f"step {step.name!r} must return dict, got {type(out).__name__}")
    return out


async def execute(graph: Graph, state: RunState) -> RunState:
    _ensure_states(graph, state)
    checkpoint.save(state)

    while True:
        ready = _ready(graph, state)
        if not ready:
            break

        gated = [n for n in ready if graph.steps[n].requires_approval and not state.approved(n)]
        if gated:
            for n in gated:
                state.steps[n].status = Status.AWAITING_APPROVAL
                checkpoint.emit(state.run_id, n, "awaiting_approval", "needs human approval")
            checkpoint.save(state)
            return state

        for n in ready:
            st = state.steps[n]
            st.status, st.attempts = Status.RUNNING, st.attempts + 1
            checkpoint.emit(state.run_id, n, "running", f"attempt {st.attempts}")
        checkpoint.save(state)

        results = await asyncio.gather(
            *(asyncio.to_thread(_run_sync, graph.steps[n], state) for n in ready),
            return_exceptions=True,
        )

        must_pause = False
        for n, res in zip(ready, results):
            st = state.steps[n]
            policy = graph.steps[n].on_failure
            if isinstance(res, Exception):
                logger.error("Step %s failed: %r", n, res)
                checkpoint.emit(state.run_id, n, "failed", repr(res))
                if policy == "skip":
                    st.status, st.error = Status.SKIPPED, repr(res)
                    st.output = {"degraded": True, "error": repr(res)}
                elif policy == "degrade":
                    st.status, st.output, st.error = Status.DONE, {"degraded": True}, repr(res)
                else:
                    st.status, st.error = Status.FAILED, repr(res)
                    must_pause = True
            else:
                st.status, st.output, st.error = Status.DONE, res, None
                checkpoint.emit(state.run_id, n, "done", "")
                _apply_routing(graph, state, n)
            checkpoint.save(state)

        if must_pause:
            return state

    return state


def resume_state(graph: Graph, state: RunState) -> RunState:
    _ensure_states(graph, state)
    for st in state.steps.values():
        step = graph.steps[st.name]
        if st.status == Status.FAILED and st.attempts < step.max_attempts:
            st.status, st.error = Status.PENDING, None
        elif st.status == Status.AWAITING_APPROVAL and state.approved(st.name):
            st.status = Status.PENDING
    return state
