"""Sparse BM25 encoder for hybrid search.

FastEmbed's 'Qdrant/bm25' is lightweight (tokenizer + term frequencies, no neural
net). IDF weighting is applied by Qdrant at query time via Modifier.IDF, so we
emit raw term-frequency sparse vectors here.
"""
import logging
from typing import List, Tuple

from fastembed import SparseTextEmbedding

logger = logging.getLogger(__name__)

_model = SparseTextEmbedding("Qdrant/bm25")


def _to_lists(embedding) -> Tuple[List[int], List[float]]:
    return embedding.indices.tolist(), embedding.values.tolist()


def embed_document(text: str) -> Tuple[List[int], List[float]]:
    if not text:
        raise ValueError("embed_document requires non-empty text")
    try:
        return _to_lists(next(iter(_model.embed([text]))))
    except Exception as e:
        logger.error("BM25 document embed failed: %s", e)
        raise


def embed_query(text: str) -> Tuple[List[int], List[float]]:
    if not text:
        raise ValueError("embed_query requires non-empty text")
    try:
        return _to_lists(next(iter(_model.query_embed([text]))))
    except Exception as e:
        logger.error("BM25 query embed failed: %s", e)
        raise
