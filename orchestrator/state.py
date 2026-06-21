from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"


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
    scratch: dict = Field(default_factory=dict)

    def approved(self, step: str) -> bool:
        return step in self.scratch.get("approved", [])

    def approve(self, step: str) -> None:
        self.scratch.setdefault("approved", [])
        if step not in self.scratch["approved"]:
            self.scratch["approved"].append(step)

    def phase(self) -> str:
        return self.scratch.get("phase", "init")

    def set_phase(self, phase: str) -> None:
        self.scratch["phase"] = phase

    def chunks(self) -> list[dict]:
        return self.scratch.setdefault("chunks", [])

    def add_chunks(self, items: list[dict]) -> None:
        self.chunks().extend(items)
