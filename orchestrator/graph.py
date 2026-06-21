from dataclasses import dataclass, field
from typing import Callable

from orchestrator.state import RunState


@dataclass
class Step:
    name: str
    run: Callable[[RunState], dict]
    deps: list[str] = field(default_factory=list)
    choose: Callable[[RunState], set[str]] | None = None
    join_any: bool = False
    requires_approval: bool = False
    max_attempts: int = 2
    on_failure: str = "pause"  # pause | skip | degrade


class Graph:
    def __init__(self, steps: list[Step], order: list[str] | None = None):
        self.steps: dict[str, Step] = {s.name: s for s in steps}
        self.order = order or [s.name for s in steps]
        self._succ: dict[str, list[str]] = {n: [] for n in self.steps}
        for s in steps:
            for d in s.deps:
                if d not in self.steps:
                    raise ValueError(f"step {s.name!r} depends on unknown {d!r}")
                self._succ[d].append(s.name)

    def successors(self, name: str) -> list[str]:
        return self._succ.get(name, [])
