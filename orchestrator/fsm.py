"""Run-level FSM phases for Plan A research."""
from enum import Enum


class RunPhase(str, Enum):
    INIT = "init"
    PLANNING = "planning"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    VERIFYING = "verifying"
    CRITIQUE = "critique"
    DONE = "done"
    FAILED = "failed"
