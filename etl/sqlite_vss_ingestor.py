"""
etl/sqlite_vss_ingestor.py
SmartSalai Edge-Sentinel — Persona 6: ETL Data Scavenger
Stage 4 of 4: EmbeddingResults → SQLite-VSS Edge-RAG Database

Schema:
  legal_chunks        — chunk metadata + embedding BLOB
  legal_embeddings    — sqlite-vss virtual table (HNSW ANN)
  ingest_log          — per-file processing audit trail

Deduplication: per file_sha256. Re-dropping same PDF → SKIPPED_DUPLICATE.
Fallback: pure-SQL cosine similarity when sqlite-vss unavailable.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import struct
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .embedder import EmbeddingResult

logger = logging.getLogger("edge_sentinel.etl.sqlite_vss_ingestor")
logger.setLevel(logging.DEBUG)

DEFAULT_DB_PATH: str = "edge_rag.db"


# ---------------------------------------------------------------------------
# Vector serialization
# ---------------------------------------------------------------------------

def _vec_to_blob(vec: np.ndarray) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def _blob_to_vec(blob: bytes, dim: int) -> np.ndarray:
    return np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32)


# ---------------------------------------------------------------------------
# VSS extension loader
# ---------------------------------------------------------------------------

def _load_vss(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vss
        conn.enable_load_extension(True)
        sqlite_vss.load(conn)
        conn.enable_load_extension(False)
        logger.info("[P6/Stage4] sqlite-vss loaded.")
        return True
    except Exception as exc:
        logger.warning(f"[P6/Stage4] sqlite-vss unavailable ({exc}). Pure-SQL cosine fallback active.")
        return False


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS legal_chunks (
    chunk_id          TEXT PRIMARY KEY,
    source_doc        TEXT NOT NULL,
    file_sha256       TEXT NOT NULL,
    doc_type          TEXT,
    page_numbers      TEXT,
    section_id        TEXT,
    chunk_index       INTEGER,
    chunk_text        TEXT NOT NULL,
    char_count        INTEGER,
    statutory_refs    TEXT,
    gazette_ref       TEXT,
    go_ref            TEXT,
    model_id          TEXT,
    embedding_blob    BLOB NOT NULL,
    embedding_dim     INTEGER NOT NULL,
    ingested_at_epoch INTEGER
);
CREATE TABLE IF NOT EXISTS ingest_log (
    log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_sha256      TEXT NOT NULL,
    source_doc       TEXT NOT NULL,
    status           TEXT,
    chunks_written   INTEGER DEFAULT 0,
    processing_ms    REAL    DEFAULT 0.0,
    logged_at_epoch  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_sha ON legal_chunks(file_sha256);
CREATE INDEX IF NOT EXISTS idx_chunks_sec ON legal_chunks(section_id);
CREATE INDEX IF NOT EXISTS idx_chunks_dt  ON legal_chunks(doc_type);
"""


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

class SQLiteVSSIngestor:
    """
    Persists EmbeddingResult objects into SQLite. Dual-mode:
      VSS_MODE     — HNSW ANN via sqlite-vss (~10ms/query, O(log N))
      FALLBACK_MODE — cosine similarity BLOB scan (O(N), OK for <5K chunks)

    Query API is consumed by legal_rag.py (T-010) at runtime.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH, embedding_dim: int = 384) -> None:
        self.db_path = db_path
        self.embedding_dim = embedding_dim
        self._conn: Optional[sqlite3.Connection] = None
        self._vss: bool = False

    # --- Lifecycle ---

    def connect(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA cache_size=-32768;")
        self._vss = _load_vss(self._conn)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def ensure_schema(self) -> None:
        if self._conn is None:
            raise RuntimeError("SQLiteVSSIngestor.ensure_schema() called before connect().")
        self._conn.executescript(_DDL)
        if self._vss:
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS legal_embeddings "
                f"USING vss0(embedding({self.embedding_dim}));"
            )
        self._conn.commit()
        logger.info("[P6/Stage4] Schema ready.")

    # --- Ingest ---

    def ingest(self, results: List[EmbeddingResult]) -> dict:
        if self._conn is None:
            raise RuntimeError("SQLiteVSSIngestor.ingest() called before connect().")
        if not results:
            return {"written": 0, "skipped_duplicate": 0, "failed": 0, "processing_ms": 0.0}

        t0 = time.monotonic()
        by_sha: dict = {}
        for r in results:
            by_sha.setdefault(r.chunk_ref.file_sha256, []).append(r)

        written, skipped, failed = 0, 0, 0
        for sha, group in by_sha.items():
            src = group[0].chunk_ref.source_doc
            existing = self._conn.execute(
                "SELECT COUNT(*) FROM legal_chunks WHERE file_sha256=?", (sha,)
            ).fetchone()[0]
            if existing:
                logger.info(f"[P6/Stage4] SKIPPED_DUPLICATE: {Path(src).name} ({sha[:10]}…)")
                self._log(sha, src, "SKIPPED_DUPLICATE", 0, 0.0)
                skipped += len(group)
                continue
            try:
                n = self._write_group(group)
                self._log(sha, src, "SUCCESS", n, (time.monotonic() - t0) * 1000)
                written += n
            except Exception as exc:
                self._conn.rollback()
                self._log(sha, src, "FAILED", 0, (time.monotonic() - t0) * 1000)
                logger.error(f"[P6/Stage4] FAILED {src}: {exc}")
                failed += len(group)

        elapsed = round((time.monotonic() - t0) * 1000, 2)
        summary = {"written": written, "skipped_duplicate": skipped, "failed": failed, "processing_ms": elapsed}
        logger.info(f"[P6/Stage4] {summary}")
        return summary

    def _write_group(self, group: List[EmbeddingResult]) -> int:
        rows, vss_rows = [], []
        for r in group:
            ch = r.chunk_ref
            blob = _vec_to_blob(r.vector)
            rows.append((
                ch.chunk_id, ch.source_doc, ch.file_sha256, ch.doc_type,
                json.dumps(ch.page_numbers), ch.section_id, ch.chunk_index,
                ch.text, ch.char_count, json.dumps(ch.statutory_refs),
                ch.gazette_ref, ch.go_ref, r.model_id, blob, r.embedding_dim,
                int(time.time() * 1000),
            ))
            if self._vss:
                vss_rows.append(blob)

        with self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO legal_chunks "
                "(chunk_id,source_doc,file_sha256,doc_type,page_numbers,section_id,"
                "chunk_index,chunk_text,char_count,statutory_refs,gazette_ref,go_ref,"
                "model_id,embedding_blob,embedding_dim,ingested_at_epoch) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            if self._vss and vss_rows:
                ids = [r.chunk_ref.chunk_id for r in group]
                ph = ",".join("?" * len(ids))
                rowids = [
                    row[0] for row in
                    self._conn.execute(
                        f"SELECT rowid FROM legal_chunks WHERE chunk_id IN ({ph}) ORDER BY rowid", ids
                    ).fetchall()
                ]
                self._conn.executemany(
                    "INSERT INTO legal_embeddings(rowid,embedding) VALUES(?,?)",
                    zip(rowids, vss_rows),
                )
        return len(rows)

    def _log(self, sha: str, src: str, status: str, n: int, ms: float) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO ingest_log(file_sha256,source_doc,status,chunks_written,processing_ms,logged_at_epoch) "
                    "VALUES(?,?,?,?,?,?)",
                    (sha, src, status, n, ms, int(time.time() * 1000)),
                )
        except Exception as exc:
            logger.warning(f"[P6/Stage4] ingest_log write failed: {exc}")

    # --- Query API (called by legal_rag.py T-010) ---

    def query(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        doc_type_filter: Optional[str] = None,
        section_id_filter: Optional[str] = None,
    ) -> List[dict]:
        """
        Retrieve top_k nearest chunks. VSS mode uses HNSW; fallback uses cosine scan.
        Returns list of dicts: chunk_id, source_doc, doc_type, section_id,
        chunk_text, statutory_refs, gazette_ref, go_ref, similarity_score.
        """
        if self._conn is None:
            raise RuntimeError("SQLiteVSSIngestor.query() called before connect().")
        vec = query_vector.astype(np.float32)
        if self._vss:
            return self._query_vss(vec, top_k, doc_type_filter, section_id_filter)
        return self._query_cosine(vec, top_k, doc_type_filter, section_id_filter)

    def _query_vss(self, vec, top_k, dt_f, sec_f) -> List[dict]:
        blob = _vec_to_blob(vec)
        joins, params = [], [blob, top_k]
        if dt_f:
            joins.append("c.doc_type=?"); params.append(dt_f)
        if sec_f:
            joins.append("c.section_id=?"); params.append(sec_f)
        # VSS match clause must always be present; other filters are optional.
        # Build WHERE clause to avoid "AND" without a preceding "WHERE".
        vss_clause = "e.embedding MATCH ?1 AND k=?2"
        where = "WHERE " + (" AND ".join(joins + [vss_clause]) if joins else vss_clause)
        sql = (
            "SELECT c.chunk_id,c.source_doc,c.doc_type,c.section_id,c.chunk_text,"
            "c.statutory_refs,c.gazette_ref,c.go_ref,e.distance "
            "FROM legal_embeddings e JOIN legal_chunks c ON e.rowid=c.rowid "
            + where
            + " ORDER BY e.distance"
        )
        return self._to_dicts(self._conn.execute(sql, params).fetchall())

    def _query_cosine(self, vec, top_k, dt_f, sec_f) -> List[dict]:
        sql = ("SELECT chunk_id,source_doc,doc_type,section_id,chunk_text,"
               "statutory_refs,gazette_ref,go_ref,embedding_blob,embedding_dim "
               "FROM legal_chunks")
        filters, params = [], []
        if dt_f:
            filters.append("doc_type=?"); params.append(dt_f)
        if sec_f:
            filters.append("section_id=?"); params.append(sec_f)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        rows = self._conn.execute(sql, params).fetchall()
        scored: List[Tuple[float, tuple]] = []
        for r in rows:
            cv = _blob_to_vec(r[8], r[9])
            scored.append((float(np.dot(vec, cv)), r))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [
            {
                "chunk_id": r[0], "source_doc": r[1], "doc_type": r[2],
                "section_id": r[3], "chunk_text": r[4],
                "statutory_refs": json.loads(r[5]) if r[5] else [],
                "gazette_ref": r[6], "go_ref": r[7], "similarity_score": sc,
            }
            for sc, r in scored[:top_k]
        ]

    @staticmethod
    def _to_dicts(rows) -> List[dict]:
        return [
            {
                "chunk_id": r[0], "source_doc": r[1], "doc_type": r[2],
                "section_id": r[3], "chunk_text": r[4],
                "statutory_refs": json.loads(r[5]) if r[5] else [],
                "gazette_ref": r[6], "go_ref": r[7], "similarity_score": r[8],
            }
            for r in rows
        ]

    def stats(self) -> dict:
        if self._conn is None:
            raise RuntimeError("SQLiteVSSIngestor.stats() called before connect().")
        total = self._conn.execute("SELECT COUNT(*) FROM legal_chunks").fetchone()[0]
        docs  = self._conn.execute("SELECT COUNT(DISTINCT file_sha256) FROM legal_chunks").fetchone()[0]
        by_dt = self._conn.execute("SELECT doc_type,COUNT(*) FROM legal_chunks GROUP BY doc_type").fetchall()
        return {
            "total_chunks": total, "unique_documents": docs,
            "vss_active": self._vss, "db_path": self.db_path,
            "doc_type_breakdown": {dt: n for dt, n in by_dt},
        }
