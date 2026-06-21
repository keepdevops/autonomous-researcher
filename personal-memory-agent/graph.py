"""Static task graph: nodes (Step) wired by dependencies, with optional routing.

A Step is one unit of work. Edges are implied by `deps` (B deps on A => A->B).
Branching is a `choose` callback on a router step that picks which of its direct
successors stay alive; the rest are SKIPPED. Parallelism is automatic: any set of
PENDING steps whose deps are all DONE is a runnable frontier the executor fans out.
"""
from dataclasses import dataclass, field
from typing import Callable

from state import RunState


@dataclass
class Step:
    name: str
    run: Callable[[RunState], dict]                 # does the work; returns its output dict
    deps: list[str] = field(default_factory=list)   # prerequisite step names
    # Router: given state, return the subset of THIS step's direct successors to
    # keep. Successors not returned (and their now-unreachable descendants) are
    # skipped. None => keep all successors (no branching).
    choose: Callable[[RunState], set[str]] | None = None
    # join_any: run once all *non-skipped* deps are DONE (>=1 DONE). Use at the
    # point where branches reconverge. Default: every dep must be DONE.
    join_any: bool = False
    requires_approval: bool = False                 # pause for a human gate
    max_attempts: int = 2                           # bounded retries on resume


class Graph:
    def __init__(self, steps: list[Step], order: list[str] | None = None):
        self.steps: dict[str, Step] = {s.name: s for s in steps}
        # Display order (for `status`); falls back to insertion order.
        self.order = order or [s.name for s in steps]
        self._validate()
        # Reverse adjacency: name -> steps that depend on it.
        self._succ: dict[str, list[str]] = {n: [] for n in self.steps}
        for s in steps:
            for d in s.deps:
                self._succ[d].append(s.name)

    def _validate(self) -> None:
        for s in self.steps.values():
            for d in s.deps:
                if d not in self.steps:
                    raise ValueError(f"step {s.name!r} depends on unknown step {d!r}")
        missing = set(self.steps) - set(self.order)
        if missing:
            raise ValueError(f"order is missing steps: {sorted(missing)}")

    def successors(self, name: str) -> list[str]:
        return self._succ.get(name, [])
