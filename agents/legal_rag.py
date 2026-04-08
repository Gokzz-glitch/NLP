"""
agents/legal_rag.py  (T-010)
SmartSalai Edge-Sentinel — MVA 2019 Legal RAG Query Agent

Retrieves relevant Motor Vehicles Act statute chunks from the local
SQLite vector store and validates results against the ULS before
generating a legal event.

Graceful degradation:
  - If sentence-transformers unavailable → hash-based similarity (demo mode)
  - Falls back to the legacy legal_vector_store.db if edge_rag.db missing
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import sqlite3
import struct
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.agents.legal_rag")

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_DEFAULT_DB = str(_REPO_ROOT / "legal_vector_store.db")
_ETL_DB     = str(_REPO_ROOT / "edge_rag.db")
_ULS_PATH   = str(_REPO_ROOT / "schemas" / "universal_legal_schema.json")

TOP_K = 5


# ---------------------------------------------------------------------------
# Embedding backend (graceful degradation)
# ---------------------------------------------------------------------------
def _build_embedder():
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return ("st", model)
    except Exception:
        logger.info("[LegalRAG] sentence-transformers unavailable — using hash fallback")
        return ("hash", None)


def _embed(backend, text: str):
    kind, model = backend
    if kind == "st":
        import numpy as np
        return model.encode(text, convert_to_numpy=True)
    # Hash fallback: deterministic 64-dim float32 vector from SHA3-256
    import struct
    digest = hashlib.sha3_256(text.encode()).digest()
    floats = [struct.unpack("f", digest[i:i+4])[0] for i in range(0, 32, 4)]
    return floats * 8   # 64 dims


def _cosine(a, b) -> float:
    try:
        import numpy as np
        a, b = np.array(a, dtype=float), np.array(b, dtype=float)
        denom = (float(np.linalg.norm(a)) * float(np.linalg.norm(b)))
        return float(np.dot(a, b) / denom) if denom else 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# ULS validator
# ---------------------------------------------------------------------------
def _load_uls() -> Dict:
    try:
        with open(_ULS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _uls_matches(query_text: str, uls: Dict) -> List[Dict]:
    matches = []
    registry = uls.get("offence_registry", {})
    q = query_text.lower()
    for offence_id, rec in registry.items():
        name = rec.get("canonical_name", "").lower()
        section = rec.get("statute_ref", {}).get("section", "")
        if name and any(w in q for w in name.split() if len(w) > 3):
            matches.append({
                "offence_id": offence_id,
                "section": section,
                "canonical_name": rec["canonical_name"],
                "irad_category_code": rec.get("detection_triggers", {}).get("irad_category_code", ""),
            })
    return matches


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _open_db(path: str) -> Optional[sqlite3.Connection]:
    if os.path.exists(path):
        try:
            return sqlite3.connect(path, check_same_thread=False)
        except Exception:
            pass
    return None


def _detect_db_schema(conn: sqlite3.Connection) -> str:
    """Return 'legacy' or 'etl' based on table structure."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    if "statute_chunks" in tables:
        return "etl"
    if "embeddings" in tables:
        return "legacy"
    return "unknown"


def _query_legacy(conn: sqlite3.Connection, embedding, top_k: int) -> List[Dict]:
    cur = conn.cursor()
    cur.execute("SELECT statute_id, content, embedding_blob FROM embeddings")
    rows = cur.fetchall()
    results = []
    for statute_id, content, blob in rows:
        try:
            import numpy as np
            stored = np.frombuffer(blob, dtype=np.float32)
        except Exception:
            stored = []
        sim = _cosine(embedding, stored)
        results.append({
            "chunk_id": statute_id,
            "chunk_text": content,
            "section_id": None,
            "doc_type": "LEGACY",
            "similarity_score": sim,
        })
    results.sort(key=lambda r: r["similarity_score"], reverse=True)
    return results[:top_k]


def _query_etl(conn: sqlite3.Connection, embedding, top_k: int) -> List[Dict]:
    cur = conn.cursor()
    cur.execute("SELECT chunk_id, chunk_text, section_id, doc_type, embedding_blob FROM statute_chunks")
    rows = cur.fetchall()
    results = []
    for chunk_id, chunk_text, section_id, doc_type, blob in rows:
        try:
            import numpy as np
            stored = np.frombuffer(blob, dtype=np.float32)
        except Exception:
            stored = []
        sim = _cosine(embedding, stored)
        results.append({
            "chunk_id": chunk_id,
            "chunk_text": chunk_text,
            "section_id": section_id,
            "doc_type": doc_type or "ETL",
            "similarity_score": sim,
        })
    results.sort(key=lambda r: r["similarity_score"], reverse=True)
    return results[:top_k]


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class LegalRAGAgent:
    """
    MVA 2019 Retrieval-Augmented-Generation query agent.

    Usage:
        agent = LegalRAGAgent()
        agent.load()
        result = agent.query("No speed limit sign within 500m of camera")
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._schema: str = "unknown"
        self._backend = None
        self._uls: Dict = {}
        self._bus = None

    def attach_bus(self, bus) -> None:
        self._bus = bus
        from core.agent_bus import Topics
        bus.subscribe(Topics.RAG_QUERY, self._on_rag_query)

    def _on_rag_query(self, msg) -> None:
        from core.agent_bus import Topics
        query_text = msg.params.get("query_text", "")
        if not query_text:
            return
        result = self.query(query_text)
        if self._bus:
            self._bus.publish(Topics.RAG_RESPONSE, result)

    def load(self) -> bool:
        self._backend = _build_embedder()
        self._uls = _load_uls()

        # Prefer ETL db, fall back to legacy
        if self._db_path:
            self._conn = _open_db(self._db_path)
        if self._conn is None:
            self._conn = _open_db(_ETL_DB)
        if self._conn is None:
            self._conn = _open_db(_DEFAULT_DB)

        if self._conn:
            self._schema = _detect_db_schema(self._conn)
            return True
        logger.warning("[LegalRAG] No vector DB available — results will be empty.")
        return False

    def query(self, query_text: str, top_k: int = TOP_K) -> Dict[str, Any]:
        t0 = time.time()
        if not query_text or not query_text.strip():
            return {"query": query_text, "results": [], "uls_matches": [], "source": "empty"}

        embedding = _embed(self._backend, query_text)
        uls_matches = _uls_matches(query_text, self._uls)

        results: List[Dict] = []
        source = "no_db"

        if self._conn:
            if self._schema == "etl":
                results = _query_etl(self._conn, embedding, top_k)
                source = "rag_db"
            elif self._schema == "legacy":
                results = _query_legacy(self._conn, embedding, top_k)
                source = "legacy_db"

        elapsed_ms = round((time.time() - t0) * 1000)
        logger.info(
            f"[LegalRAG] Query: {query_text[:60]!r} → "
            f"{len(results)} results ({source}) in {elapsed_ms}ms | "
            f"ULS matches: {[m['offence_id'] for m in uls_matches]}"
        )
        return {
            "query": query_text,
            "results": results,
            "uls_matches": uls_matches,
            "source": source,
            "elapsed_ms": elapsed_ms,
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


_agent: Optional[LegalRAGAgent] = None


def get_agent() -> LegalRAGAgent:
    global _agent
    if _agent is None:
        _agent = LegalRAGAgent()
        _agent.load()
    return _agent
