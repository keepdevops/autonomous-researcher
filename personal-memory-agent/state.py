"""Run/step state models for the durable task-graph executor.

A RunState is the single source of truth for one execution. It is checkpointed
(see checkpoint.py) after every transition, so a crash or an approval pause can
be resumed from the exact step it stopped on.
"""
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    PENDING = "pending"            # not yet started
    RUNNING = "running"            # in flight this tick
    DONE = "done"                  # completed successfully
    FAILED = "failed"             # raised; resumable after inspection
    SKIPPED = "skipped"           # branch not taken
    AWAITING_APPROVAL = "awaiting_approval"  # paused for a human gate


# Terminal-for-this-attempt states the executor must not re-run automatically.
SETTLED = {Status.DONE, Status.SKIPPED}


class StepState(BaseModel):
    name: str
    status: Status = Status.PENDING
    output: dict | None = None
    error: str | None = None
    attempts: int = 0


class RunState(BaseModel):
    run_id: str
    goal: str
    steps: dict[str, StepState] = Field(default_factory=dict)
    scratch: dict = Field(default_factory=dict)  # cross-step blackboard (e.g. approvals)

    def approved(self, step: str) -> bool:
        return step in self.scratch.get("approved", [])

    def approve(self, step: str) -> None:
        self.scratch.setdefault("approved", [])
        if step not in self.scratch["approved"]:
            self.scratch["approved"].append(step)
