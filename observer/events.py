"""Canonical event model for cross-component observability."""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Component(str, Enum):
    ORCHESTRATOR = "orchestrator"
    RESEARCHER = "researcher"
    MEMORY = "memory"
    EMBEDDER = "embedder"
    TOOLS = "tools"
    PREFLIGHT = "preflight"
    REFLECTOR = "reflector"
    APP = "app"
    INGEST = "ingest"
    GRAPH = "graph"
    RETRIEVAL = "retrieval"


class EventKind(str, Enum):
    LIFECYCLE = "lifecycle"
    STEP = "step"
    TOOL = "tool"
    RETRIEVAL = "retrieval"
    STORAGE = "storage"
    HEALTH = "health"
    ERROR = "error"


class SystemEvent(BaseModel):
    component: Component
    kind: EventKind
    status: str
    step: str = ""
    run_id: str = ""
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: float | None = None
