"""
orchestrator/app/tools/rag.py
Qdrant-backed Retrieval-Augmented Generation (RAG) query stub.

Stores and retrieves road-rule / driving-advice documents using Qdrant as the
vector database.  Embeddings are computed with a simple TF-IDF-style character
n-gram hashing so no external model download is required for the MVP.

TODO:
 - Replace the hash-based embeddings with a real sentence-transformer model
   (e.g. ``paraphrase-multilingual-MiniLM-L12-v2``) for accurate retrieval.
 - Seed the collection with Tamil Nadu-specific driving regulations, MV Act
   sections, and NHAI advisories.
 - Add multilingual support (Tamil + English).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
_QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
_COLLECTION = "nndl_driving_kb"
_VECTOR_DIM = 128  # must match the embedding size below


# ── tiny deterministic embedding (no ML model required) ──────────────────────

def _embed(text: str) -> list[float]:
    """
    Produce a 128-dimensional deterministic float vector from *text* by
    hashing character bi-grams.  Suitable for smoke-testing; replace with a
    real encoder for production.
    """
    vec = [0.0] * _VECTOR_DIM
    text = text.lower()
    for i in range(len(text) - 1):
        bigram = text[i : i + 2]
        digest = int(hashlib.md5(bigram.encode()).hexdigest(), 16)
        idx = digest % _VECTOR_DIM
        vec[idx] += 1.0

    # L2-normalise
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


# ── Qdrant helper (lazy import so orchestrator starts without qdrant-client) ──

def _get_client():
    """Return a QdrantClient pointed at the configured Qdrant instance."""
    try:
        from qdrant_client import QdrantClient  # type: ignore  # noqa: PLC0415
        return QdrantClient(host=_QDRANT_HOST, port=_QDRANT_PORT, timeout=3)
    except ImportError:
        logger.debug("qdrant-client not installed; RAG disabled")
        return None
    except Exception as exc:
        logger.debug("Qdrant not reachable: %s", exc)
        return None


def _ensure_collection(client) -> None:
    """Create the Qdrant collection if it does not yet exist."""
    try:
        from qdrant_client.models import Distance, VectorParams  # type: ignore  # noqa: PLC0415
        existing = [c.name for c in client.get_collections().collections]
        if _COLLECTION not in existing:
            client.create_collection(
                collection_name=_COLLECTION,
                vectors_config=VectorParams(size=_VECTOR_DIM, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection '%s'", _COLLECTION)
    except Exception as exc:
        logger.warning("Could not create Qdrant collection: %s", exc)


# ── public API ────────────────────────────────────────────────────────────────

def query(question: str, top_k: int = 1) -> Optional[str]:
    """
    Retrieve the most relevant answer for *question* from the Qdrant knowledge
    base.

    Returns the payload ``"answer"`` field of the top hit, or ``None`` if
    nothing useful is found (score < 0.5) or Qdrant is unavailable.

    Parameters
    ----------
    question:
        The driver's spoken question (already transcribed).
    top_k:
        Number of candidates to retrieve (default 1 for low-latency).
    """
    client = _get_client()
    if client is None:
        return None

    _ensure_collection(client)

    try:
        results = client.search(
            collection_name=_COLLECTION,
            query_vector=_embed(question),
            limit=top_k,
            with_payload=True,
        )
        if results and results[0].score >= 0.5:
            return results[0].payload.get("answer")
    except Exception as exc:
        logger.warning("Qdrant search error: %s", exc)

    return None


def index_document(doc_id: str, question: str, answer: str) -> bool:
    """
    Insert or update a Q&A pair in the knowledge base.

    Parameters
    ----------
    doc_id:
        Unique string identifier for the document (will be hashed to int).
    question:
        Canonical question text used to compute the embedding.
    answer:
        Answer text stored as payload and returned by :func:`query`.

    Returns
    -------
    bool
        ``True`` on success, ``False`` on error.
    """
    client = _get_client()
    if client is None:
        return False

    _ensure_collection(client)

    try:
        from qdrant_client.models import PointStruct  # type: ignore  # noqa: PLC0415
        point_id = int(hashlib.md5(doc_id.encode()).hexdigest(), 16) % (2**63)
        client.upsert(
            collection_name=_COLLECTION,
            points=[
                PointStruct(
                    id=point_id,
                    vector=_embed(question),
                    payload={"question": question, "answer": answer},
                )
            ],
        )
        return True
    except Exception as exc:
        logger.warning("Qdrant upsert error: %s", exc)
        return False
