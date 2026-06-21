"""Qdrant-backed memory with hybrid (dense + sparse BM25) search.

Each memory becomes one Qdrant point carrying two vectors:
  dense  — 768-d nomic embedding (semantic similarity, via the :8082 server)
  bm25   — sparse term-frequency vector (lexical match, IDF-weighted by Qdrant)
Queries run both and fuse the rankings with Reciprocal Rank Fusion (RRF).
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from qdrant_client import QdrantClient, models

import sparse
from embedder import EMBED_DIM

logger = logging.getLogger(__name__)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "agent_memories")

client = QdrantClient(url=QDRANT_URL)


def _ensure_collection() -> None:
    if client.collection_exists(COLLECTION):
        return
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config={
            "dense": models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE)
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    # Indexes so we can filter by role and order_by timestamp (for reflection).
    client.create_payload_index(COLLECTION, "role", models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(COLLECTION, "ts", models.PayloadSchemaType.FLOAT)
    logger.info("Created Qdrant collection %r", COLLECTION)


_ensure_collection()


def add_memory(role: str, content: str, metadata: Optional[dict] = None) -> str:
    """Embed (dense + sparse) and upsert one memory. Returns the point id."""
    if not role or not content:
        raise ValueError("add_memory requires non-empty role and content")

    from embedder import embedder  # local import keeps module load order simple

    now = datetime.now(timezone.utc)
    dense_vec = embedder.embed(content, task="document")[0]
    s_idx, s_val = sparse.embed_document(content)
    point_id = str(uuid.uuid4())

    try:
        client.upsert(
            collection_name=COLLECTION,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense_vec,
                        "bm25": models.SparseVector(indices=s_idx, values=s_val),
                    },
                    payload={
                        "role": role,
                        "content": content,
                        "timestamp": now.isoformat(),
                        "ts": now.timestamp(),
                        "metadata": metadata or {},
                    },
                )
            ],
        )
    except Exception as e:
        logger.error("Qdrant upsert failed for memory %s: %s", point_id, e)
        raise
    return point_id


def _row(point) -> Dict[str, Any]:
    p = point.payload or {}
    return {
        "id": point.id,
        "role": p.get("role"),
        "content": p.get("content"),
        "timestamp": p.get("timestamp"),
        "score": getattr(point, "score", None),
    }


def search_memories(query: str, k: int = 8) -> List[Dict[str, Any]]:
    """Hybrid recall: dense + BM25 prefetch, fused with RRF. Nearest first."""
    if not query:
        return []
    if not isinstance(k, int) or k <= 0:
        raise ValueError(f"k must be a positive int, got {k!r}")

    from embedder import embedder

    dense_q = embedder.embed(query, task="query")[0]
    s_idx, s_val = sparse.embed_query(query)
    over = max(k * 4, 20)  # pull a wider net per branch before fusing

    try:
        result = client.query_points(
            collection_name=COLLECTION,
            prefetch=[
                models.Prefetch(query=dense_q, using="dense", limit=over),
                models.Prefetch(
                    query=models.SparseVector(indices=s_idx, values=s_val),
                    using="bm25",
                    limit=over,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        )
    except Exception as e:
        logger.error("Qdrant hybrid query failed: %s", e)
        raise
    return [_row(pt) for pt in result.points]


def recent_memories(role: str, days: int, limit: int = 200) -> List[str]:
    """Scroll the newest `content` strings for a role within the last `days`."""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    points, _ = client.scroll(
        collection_name=COLLECTION,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(key="role", match=models.MatchValue(value=role)),
                models.FieldCondition(key="ts", range=models.Range(gte=cutoff)),
            ]
        ),
        order_by=models.OrderBy(key="ts", direction=models.Direction.DESC),
        limit=limit,
        with_payload=True,
    )
    return [(p.payload or {}).get("content", "") for p in points]
