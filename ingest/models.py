from typing import Any, Literal

from pydantic import BaseModel, Field


DocType = Literal["web", "markdown", "text", "pdf", "code"]


class ChunkMetadata(BaseModel):
    title: str | None = None
    section: str | None = None
    subsection: str | None = None
    file_path: str | None = None
    page: int | None = None
    git_commit: str | None = None
    source_url: str | None = None
    doc_type: DocType = "text"
    chunk_index: int = 0
    parent_doc_id: str = ""
    overlap_from: str | None = None


class Chunk(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata
    token_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
