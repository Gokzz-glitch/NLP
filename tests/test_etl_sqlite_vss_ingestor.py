"""
tests/test_etl_sqlite_vss_ingestor.py

Unit tests for etl/sqlite_vss_ingestor.py — SQLiteVSSIngestor.
Uses in-memory SQLite to avoid filesystem side-effects.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import numpy as np
import pytest

from etl.sqlite_vss_ingestor import (
    SQLiteVSSIngestor,
    _vec_to_blob,
    _blob_to_vec,
)
from etl.embedder import EmbeddingResult, HASH_FALLBACK_DIM, LegalEmbedder
from etl.text_chunker import LegalChunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIM = 8  # Small dimension for tests


def _make_chunk(chunk_id="abc-c0000", idx=0, sha="deadbeef", text="legal text"):
    return LegalChunk(
        chunk_id=chunk_id,
        source_doc="test.pdf",
        file_sha256=sha,
        doc_type="MVA_ACT",
        page_numbers=[1],
        section_id="183",
        chunk_index=idx,
        text=text,
        char_count=len(text),
        statutory_refs=["Section 183"],
    )


def _make_result(chunk_id="abc-c0000", idx=0, sha="deadbeef", text="legal text", dim=DIM):
    chunk = _make_chunk(chunk_id=chunk_id, idx=idx, sha=sha, text=text)
    vec = np.random.rand(dim).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return EmbeddingResult(
        chunk_id=chunk_id,
        vector=vec,
        embedding_dim=dim,
        model_id="HASH_FALLBACK",
        inference_time_ms=0.0,
        chunk_ref=chunk,
    )


def _connected_ingestor(dim=DIM) -> SQLiteVSSIngestor:
    ing = SQLiteVSSIngestor(db_path=":memory:", embedding_dim=dim)
    ing.connect()
    ing.ensure_schema()
    return ing


# ---------------------------------------------------------------------------
# Vector serialization helpers
# ---------------------------------------------------------------------------

class TestVecHelpers:

    def test_roundtrip_float32(self):
        v = np.array([1.5, -2.3, 0.0, 9.8], dtype=np.float32)
        blob = _vec_to_blob(v)
        v2 = _blob_to_vec(blob, 4)
        assert np.allclose(v, v2)

    def test_blob_is_bytes(self):
        v = np.ones(4, dtype=np.float32)
        blob = _vec_to_blob(v)
        assert isinstance(blob, bytes)

    def test_blob_length(self):
        v = np.ones(8, dtype=np.float32)
        blob = _vec_to_blob(v)
        assert len(blob) == 8 * 4  # 4 bytes per float32

    def test_zero_vector_roundtrip(self):
        v = np.zeros(16, dtype=np.float32)
        assert np.allclose(v, _blob_to_vec(_vec_to_blob(v), 16))


# ---------------------------------------------------------------------------
# SQLiteVSSIngestor connection management
# ---------------------------------------------------------------------------

class TestConnectionLifecycle:

    def test_connect_and_close(self):
        ing = SQLiteVSSIngestor(db_path=":memory:")
        ing.connect()
        ing.close()
        assert ing._conn is None

    def test_double_close_no_error(self):
        ing = SQLiteVSSIngestor(db_path=":memory:")
        ing.connect()
        ing.close()
        ing.close()  # second close must not raise

    def test_ensure_schema_before_connect_raises(self):
        ing = SQLiteVSSIngestor(db_path=":memory:")
        with pytest.raises(RuntimeError, match="connect()"):
            ing.ensure_schema()

    def test_ingest_before_connect_raises(self):
        ing = SQLiteVSSIngestor(db_path=":memory:")
        with pytest.raises(RuntimeError, match="connect()"):
            ing.ingest([_make_result()])

    def test_query_before_connect_raises(self):
        ing = SQLiteVSSIngestor(db_path=":memory:")
        vec = np.zeros(DIM, dtype=np.float32)
        with pytest.raises(RuntimeError, match="connect()"):
            ing.query(vec)

    def test_stats_before_connect_raises(self):
        ing = SQLiteVSSIngestor(db_path=":memory:")
        with pytest.raises(RuntimeError, match="connect()"):
            ing.stats()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:

    def test_schema_creates_legal_chunks_table(self):
        ing = _connected_ingestor()
        count = ing._conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='legal_chunks'"
        ).fetchone()[0]
        assert count == 1

    def test_schema_creates_ingest_log_table(self):
        ing = _connected_ingestor()
        count = ing._conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='ingest_log'"
        ).fetchone()[0]
        assert count == 1

    def test_schema_idempotent(self):
        ing = _connected_ingestor()
        ing.ensure_schema()  # Second call must not raise


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

class TestIngest:

    def test_ingest_empty_list_returns_zero_written(self):
        ing = _connected_ingestor()
        summary = ing.ingest([])
        assert summary["written"] == 0

    def test_ingest_single_chunk(self):
        ing = _connected_ingestor()
        result = _make_result()
        summary = ing.ingest([result])
        assert summary["written"] == 1
        assert summary["failed"] == 0

    def test_ingest_multiple_chunks_same_doc(self):
        ing = _connected_ingestor()
        results = [_make_result(chunk_id=f"abc-c{i:04d}", idx=i, sha="same123") for i in range(5)]
        summary = ing.ingest(results)
        assert summary["written"] == 5

    def test_ingest_duplicate_sha_skipped(self):
        ing = _connected_ingestor()
        r1 = _make_result(sha="dup1234")
        ing.ingest([r1])
        r2 = _make_result(chunk_id="abc-c0001", idx=1, sha="dup1234")
        summary = ing.ingest([r2])
        assert summary["skipped_duplicate"] == 1
        assert summary["written"] == 0

    def test_ingest_different_sha_both_written(self):
        ing = _connected_ingestor()
        r1 = _make_result(sha="sha001")
        r2 = _make_result(chunk_id="xyz-c0000", sha="sha002")
        summary = ing.ingest([r1, r2])
        assert summary["written"] == 2

    def test_ingest_summary_has_required_keys(self):
        ing = _connected_ingestor()
        summary = ing.ingest([])
        assert {"written", "skipped_duplicate", "failed", "processing_ms"} <= set(summary)

    def test_ingested_chunk_retrievable(self):
        ing = _connected_ingestor()
        r = _make_result(text="unique speeding fine text")
        ing.ingest([r])
        row = ing._conn.execute(
            "SELECT chunk_text FROM legal_chunks WHERE chunk_id=?", (r.chunk_ref.chunk_id,)
        ).fetchone()
        assert row is not None
        assert "speeding" in row[0]


# ---------------------------------------------------------------------------
# Query (cosine fallback — no sqlite-vss)
# ---------------------------------------------------------------------------

class TestQueryCosine:

    def test_query_empty_db_returns_empty_list(self):
        ing = _connected_ingestor()
        vec = np.zeros(DIM, dtype=np.float32)
        results = ing.query(vec)
        assert results == []

    def test_query_returns_top_k(self):
        ing = _connected_ingestor()
        for i in range(10):
            ing.ingest([_make_result(chunk_id=f"abc-c{i:04d}", idx=i, sha=f"sha{i:03d}")])
        vec = np.random.rand(DIM).astype(np.float32)
        results = ing.query(vec, top_k=3)
        assert len(results) <= 3

    def test_query_result_has_required_keys(self):
        ing = _connected_ingestor()
        ing.ingest([_make_result()])
        vec = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
        results = ing.query(vec, top_k=1)
        assert len(results) == 1
        keys = set(results[0].keys())
        assert {"chunk_id", "source_doc", "doc_type", "section_id",
                "chunk_text", "statutory_refs", "gazette_ref", "go_ref",
                "similarity_score"} <= keys

    def test_query_doc_type_filter(self):
        ing = _connected_ingestor()
        r1 = _make_result(sha="sha_mva")
        # Manually change doc_type in the inserted row
        ing.ingest([r1])
        ing._conn.execute("UPDATE legal_chunks SET doc_type='GAZETTE_CENTRAL' WHERE chunk_id=?",
                          (r1.chunk_ref.chunk_id,))
        ing._conn.commit()
        vec = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
        results = ing.query(vec, doc_type_filter="GAZETTE_CENTRAL")
        assert all(r["doc_type"] == "GAZETTE_CENTRAL" for r in results)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:

    def test_stats_empty_db(self):
        ing = _connected_ingestor()
        s = ing.stats()
        assert s["total_chunks"] == 0
        assert s["unique_documents"] == 0

    def test_stats_after_ingest(self):
        ing = _connected_ingestor()
        for i in range(3):
            ing.ingest([_make_result(chunk_id=f"c{i}", idx=i, sha=f"sha{i}")])
        s = ing.stats()
        assert s["total_chunks"] == 3
        assert s["unique_documents"] == 3

    def test_stats_has_required_keys(self):
        ing = _connected_ingestor()
        s = ing.stats()
        assert {"total_chunks", "unique_documents", "vss_active", "db_path"} <= set(s)
