"""Optional sentence embeddings for semantic boundary detection."""
import logging
import math
import os
import re

import httpx

logger = logging.getLogger(__name__)

EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "")
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_BOUNDARY_THRESHOLD", "0.35"))
_SENT_RE = re.compile(r"(?<=[.!?])\s+")

_client: httpx.Client | None = None


def _client_get() -> httpx.Client | None:
    global _client
    if not EMBED_BASE_URL:
        return None
    if _client is None:
        _client = httpx.Client(base_url=EMBED_BASE_URL, timeout=60.0)
    return _client


def sentence_split(text: str) -> list[str]:
    parts = _SENT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def embed_sentences(sentences: list[str]) -> list[list[float]] | None:
    client = _client_get()
    if not client or not sentences:
        return None
    try:
        resp = client.post(
            "/embeddings",
            json={"model": "nomic", "input": [f"search_document: {s}" for s in sentences]},
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        return [row["embedding"] for row in data]
    except httpx.HTTPError as exc:
        logger.warning("semantic embed unavailable: %s", exc)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 1.0
    return dot / (na * nb)


def semantic_split(text: str, threshold: float = SEMANTIC_THRESHOLD) -> list[str]:
    sentences = sentence_split(text)
    if len(sentences) <= 1:
        return [text] if text.strip() else []
    vecs = embed_sentences(sentences)
    if not vecs or len(vecs) != len(sentences):
        return [text]
    blocks: list[str] = []
    current = sentences[0]
    for i in range(1, len(sentences)):
        sim = cosine(vecs[i - 1], vecs[i])
        if sim < threshold:
            blocks.append(current.strip())
            current = sentences[i]
        else:
            current = f"{current} {sentences[i]}"
    if current.strip():
        blocks.append(current.strip())
    return blocks
