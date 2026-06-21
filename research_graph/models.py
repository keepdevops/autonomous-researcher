from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ClaimStatus(str, Enum):
    DRAFT = "draft"
    SUPPORTED = "supported"
    DISPUTED = "disputed"
    UNSUPPORTED = "unsupported"


class Claim(BaseModel):
    id: str
    text: str
    status: ClaimStatus = ClaimStatus.DRAFT
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    commentary: str = ""


class ResearchGraph(BaseModel):
    run_id: str
    question: str
    claims: list[Claim] = Field(default_factory=list)
