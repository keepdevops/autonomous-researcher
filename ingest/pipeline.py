"""Plan A ingest: type-aware split → semantic refine → metadata → overlap → token cap."""
import logging
import subprocess
import uuid
from pathlib import Path

from ingest.embed import semantic_split
from ingest.models import Chunk, ChunkMetadata, DocType
from ingest.splitters import RawSegment, split_code, split_html, split_markdown, split_pdf, split_plain
from ingest.tokens import MAX_CHUNK_TOKENS, count_tokens

logger = logging.getLogger(__name__)


def _git_commit(file_path: str | None) -> str | None:
    if not file_path:
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(file_path).parent),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()[:12]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _structural_split(text: str, doc_type: DocType, file_path: str | None = None) -> list[RawSegment]:
    if doc_type == "pdf" and file_path:
        return split_pdf(file_path)
    if doc_type == "markdown":
        return split_markdown(text)
    if doc_type == "web":
        return split_html(text)
    if doc_type == "code":
        return split_code(text)
    return split_plain(text)


def _refine_segments(segments: list[RawSegment]) -> list[RawSegment]:
    refined: list[RawSegment] = []
    for seg in segments:
        for block in semantic_split(seg.text):
            refined.append(
                RawSegment(block, seg.title, seg.section, seg.subsection, seg.page)
            )
    return refined or segments


def _split_oversized(text: str, max_tokens: int) -> list[str]:
    if count_tokens(text) <= max_tokens:
        return [text]
    sentences = [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]
    parts: list[str] = []
    buf: list[str] = []
    for sent in sentences:
        candidate = ". ".join(buf + [sent])
        if count_tokens(candidate) > max_tokens and buf:
            parts.append(". ".join(buf) + ".")
            buf = [sent]
        else:
            buf.append(sent)
    if buf:
        parts.append(". ".join(buf) + ("" if buf[-1].endswith(".") else "."))
    return parts or [text[: max_tokens * 4]]


def _apply_overlap(chunks: list[Chunk]) -> list[Chunk]:
    if len(chunks) < 2:
        return chunks
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        cur = chunks[i]
        prev_sents = [s.strip() for s in prev.text.split(". ") if s.strip()]
        overlap = prev_sents[-1] if prev_sents else ""
        text = f"{overlap}. {cur.text}" if overlap else cur.text
        meta = cur.metadata.model_copy(update={"overlap_from": prev.id})
        out.append(cur.model_copy(update={"text": text.strip(), "metadata": meta}))
    return out


def ingest_document(
    text: str,
    *,
    doc_type: DocType = "text",
    source_url: str | None = None,
    file_path: str | None = None,
    title: str | None = None,
    page: int | None = None,
    max_tokens: int = MAX_CHUNK_TOKENS,
) -> list[Chunk]:
    parent_doc_id = uuid.uuid4().hex[:12]
    git_commit = _git_commit(file_path)
    segments = _structural_split(text, doc_type, file_path)
    segments = _refine_segments(segments)

    raw_chunks: list[Chunk] = []
    for seg in segments:
        for piece in _split_oversized(seg.text, max_tokens):
            cid = uuid.uuid4().hex[:12]
            meta = ChunkMetadata(
                title=title or seg.title,
                section=seg.section,
                subsection=seg.subsection,
                file_path=file_path,
                page=page or seg.page,
                git_commit=git_commit,
                source_url=source_url,
                doc_type=doc_type,
                chunk_index=len(raw_chunks),
                parent_doc_id=parent_doc_id,
            )
            raw_chunks.append(
                Chunk(id=cid, text=piece, metadata=meta, token_count=count_tokens(piece))
            )

    raw_chunks = _apply_overlap(raw_chunks)
    for i, ch in enumerate(raw_chunks):
        ch.metadata.chunk_index = i
        ch.token_count = count_tokens(ch.text)
    logger.info(
        "ingest %s → %d chunks (parent=%s url=%s)",
        doc_type, len(raw_chunks), parent_doc_id, source_url or file_path,
    )
    from ingest.observe import emit

    emit(
        "indexed",
        f"{len(raw_chunks)} chunks",
        doc_type=doc_type,
        parent_doc_id=parent_doc_id,
        source=source_url or file_path,
    )
    return raw_chunks


def ingest_path(path: str) -> list[Chunk]:
    from ingest.detect import from_path

    p = Path(path)
    doc_type = from_path(p)
    if doc_type == "pdf":
        return ingest_document("", doc_type="pdf", file_path=str(p.resolve()), title=p.name)
    text = p.read_text(encoding="utf-8", errors="replace")
    return ingest_document(
        text, doc_type=doc_type, file_path=str(p.resolve()), title=p.name
    )
