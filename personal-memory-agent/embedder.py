"""Embedding client for the personal-memory-agent.

Talks to a dedicated llama.cpp embedding server (see ../start-embed.sh, :8082),
NOT the chat server on :8081. nomic-embed-text-v1.5 requires a task prefix on
every input: 'search_document: ' when storing, 'search_query: ' when querying.
"""
import os
import logging

import httpx

logger = logging.getLogger(__name__)

EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://127.0.0.1:8082/v1")
EMBED_DIM = 768  # nomic-embed-text-v1.5

_PREFIX = {"document": "search_document: ", "query": "search_query: "}


class LocalEmbedder:
    def __init__(self, base_url: str = EMBED_BASE_URL):
        # Generous timeout: first call blocks while the model warms up.
        self.client = httpx.Client(base_url=base_url, timeout=120.0)

    def embed(self, texts, task: str = "document"):
        if isinstance(texts, str):
            texts = [texts]
        if task not in _PREFIX:
            raise ValueError(f"task must be 'document' or 'query', got {task!r}")
        prefix = _PREFIX[task]
        payload = {"model": "nomic", "input": [prefix + t for t in texts]}

        try:
            resp = self.client.post("/embeddings", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Embedding request to %s failed: %s", EMBED_BASE_URL, e)
            raise

        data = resp.json().get("data")
        if not data:
            logger.error("Embedding response had no 'data': %s", resp.text[:200])
            raise ValueError("embedding server returned no data")

        vectors = [item["embedding"] for item in data]
        for v in vectors:
            if len(v) != EMBED_DIM:
                logger.error("Unexpected embedding dim %d (want %d)", len(v), EMBED_DIM)
                raise ValueError(f"embedding dim {len(v)} != {EMBED_DIM}")
        return vectors


embedder = LocalEmbedder()
