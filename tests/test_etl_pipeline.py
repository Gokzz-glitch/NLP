"""
tests/test_etl_pipeline.py

Unit tests for etl/pipeline.py — ETLPipeline.

All external I/O (PDF reading, SQLite, embedding model) is mocked so that
the tests run in CI without any real files, database, or ML models.
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from etl.pipeline import ETLPipeline
from etl.pdf_extractor import ExtractionStatus, ExtractionResult, ExtractionMethod
from etl.text_chunker import LegalChunk
from etl.embedder import EmbeddingResult, EmbedderMode
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(status=ExtractionStatus.SUCCESS, sha="abc123"):
    return ExtractionResult(
        source_path="test.pdf",
        file_sha256=sha,
        total_pages=1,
        status=status,
    )


def _make_chunk(idx=0):
    return LegalChunk(
        chunk_id=f"abc-c{idx:04d}",
        source_doc="test.pdf",
        file_sha256="abc123",
        doc_type="MVA_ACT",
        page_numbers=[1],
        section_id="183",
        chunk_index=idx,
        text="legal text " * 10,
        char_count=110,
    )


def _make_embedding(idx=0):
    chunk = _make_chunk(idx)
    vec = np.random.rand(8).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return EmbeddingResult(
        chunk_id=chunk.chunk_id,
        vector=vec,
        embedding_dim=8,
        model_id="HASH_FALLBACK",
        inference_time_ms=0.0,
        chunk_ref=chunk,
    )


# ---------------------------------------------------------------------------
# Helpers that build a fully-wired mock pipeline
# ---------------------------------------------------------------------------

def _mock_pipeline(tmp_dir: str, pdf_names=("test.pdf",)):
    """
    Returns (pipeline, mocked_extractor, mocked_chunker, mocked_embedder,
             mocked_ingestor) with each component returning sensible defaults.
    Writes dummy PDF files into tmp_dir so glob("*.pdf") finds them.
    """
    for name in pdf_names:
        (Path(tmp_dir) / name).write_bytes(b"%PDF-1.4 dummy")

    pipeline = ETLPipeline(db_path=":memory:")

    # Replace each component with a MagicMock
    mock_extractor = MagicMock()
    mock_chunker   = MagicMock()
    mock_embedder  = MagicMock()
    mock_ingestor  = MagicMock()

    mock_extractor.extract.return_value        = _make_result()
    mock_chunker.chunk.return_value            = [_make_chunk()]
    mock_embedder.embed_chunks.return_value    = [_make_embedding()]
    mock_embedder.load.return_value            = EmbedderMode.HASH_FALLBACK
    mock_ingestor.ingest.return_value  = {
        "written": 1, "skipped_duplicate": 0, "failed": 0, "processing_ms": 1.0
    }

    pipeline.extractor = mock_extractor
    pipeline.chunker   = mock_chunker
    pipeline.embedder  = mock_embedder
    pipeline.ingestor  = mock_ingestor

    return pipeline, mock_extractor, mock_chunker, mock_embedder, mock_ingestor


# ---------------------------------------------------------------------------
# ETLPipeline.run_once — basic flow
# ---------------------------------------------------------------------------

class TestETLPipelineRunOnce:

    def test_run_once_missing_dir_does_not_crash(self):
        """Non-existent data directory must log and return gracefully."""
        pipeline = ETLPipeline(db_path=":memory:")
        # Should not raise
        pipeline.run_once("/path/that/does/not/exist_xyzzy")

    def test_run_once_empty_dir_does_not_call_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, mock_ext, *_ = _mock_pipeline(tmp, pdf_names=[])
            # Remove the dummy file we didn't create
            pipeline.run_once(tmp)
            mock_ext.extract.assert_not_called()

    def test_run_once_calls_extract_for_each_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, mock_ext, mock_chunk, mock_emb, mock_ing = _mock_pipeline(
                tmp, pdf_names=["a.pdf", "b.pdf"]
            )
            pipeline.run_once(tmp)
            assert mock_ext.extract.call_count == 2

    def test_run_once_calls_embedder_load_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, mock_emb, _ = _mock_pipeline(tmp)
            pipeline.run_once(tmp)
            mock_emb.load.assert_called_once()

    def test_run_once_calls_ingestor_connect(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, _, mock_ing = _mock_pipeline(tmp)
            pipeline.run_once(tmp)
            mock_ing.connect.assert_called_once()

    def test_run_once_calls_ingestor_ensure_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, _, mock_ing = _mock_pipeline(tmp)
            pipeline.run_once(tmp)
            mock_ing.ensure_schema.assert_called_once()

    def test_run_once_calls_ingestor_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, _, mock_ing = _mock_pipeline(tmp)
            pipeline.run_once(tmp)
            mock_ing.close.assert_called_once()

    def test_run_once_calls_chunker_with_extraction_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, mock_ext, mock_chunk, _, _ = _mock_pipeline(tmp)
            pipeline.run_once(tmp)
            assert mock_chunk.chunk.call_count == 1
            called_arg = mock_chunk.chunk.call_args[0][0]
            assert called_arg.status == ExtractionStatus.SUCCESS

    def test_run_once_calls_embed_chunks_with_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, mock_chunk, mock_emb, _ = _mock_pipeline(tmp)
            chunks = [_make_chunk(i) for i in range(3)]
            mock_chunk.chunk.return_value = chunks
            pipeline.run_once(tmp)
            mock_emb.embed_chunks.assert_called_once_with(chunks)

    def test_run_once_calls_ingest_with_embeddings(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, mock_emb, mock_ing = _mock_pipeline(tmp)
            embeddings = [_make_embedding(i) for i in range(2)]
            mock_emb.embed_chunks.return_value = embeddings
            pipeline.run_once(tmp)
            mock_ing.ingest.assert_called_once_with(embeddings)

    def test_run_once_skips_failed_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, mock_ext, mock_chunk, _, _ = _mock_pipeline(tmp)
            mock_ext.extract.return_value = _make_result(status=ExtractionStatus.FAILED)
            pipeline.run_once(tmp)
            mock_chunk.chunk.assert_not_called()

    def test_run_once_processes_partial_extraction(self):
        """PARTIAL extractions (not FAILED) must still be processed."""
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, mock_ext, mock_chunk, _, _ = _mock_pipeline(tmp)
            mock_ext.extract.return_value = _make_result(status=ExtractionStatus.PARTIAL)
            pipeline.run_once(tmp)
            mock_chunk.chunk.assert_called_once()

    def test_run_once_exception_in_pipeline_does_not_stop_next_file(self):
        """An exception on one PDF must not stop processing of subsequent PDFs."""
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, mock_ext, mock_chunk, _, _ = _mock_pipeline(
                tmp, pdf_names=["a.pdf", "b.pdf"]
            )
            call_count = [0]
            def extract_side_effect(path):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("Simulated extractor failure")
                return _make_result()

            mock_ext.extract.side_effect = extract_side_effect
            # Should not raise — must process second file
            pipeline.run_once(tmp)
            assert mock_ext.extract.call_count == 2

    def test_run_once_multiple_pdfs_all_ingested(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, mock_ext, _, _, mock_ing = _mock_pipeline(
                tmp, pdf_names=["a.pdf", "b.pdf", "c.pdf"]
            )
            pipeline.run_once(tmp)
            assert mock_ing.ingest.call_count == 3


# ---------------------------------------------------------------------------
# ETLPipeline constructor
# ---------------------------------------------------------------------------

class TestETLPipelineConstructor:

    def test_default_db_path(self):
        p = ETLPipeline()
        assert p.ingestor.db_path == "edge_rag.db"

    def test_custom_db_path(self):
        p = ETLPipeline(db_path=":memory:")
        assert p.ingestor.db_path == ":memory:"

    def test_components_instantiated(self):
        p = ETLPipeline(db_path=":memory:")
        from etl.pdf_extractor import PDFExtractor
        from etl.text_chunker import LegalTextChunker
        from etl.embedder import LegalEmbedder
        from etl.sqlite_vss_ingestor import SQLiteVSSIngestor
        assert isinstance(p.extractor, PDFExtractor)
        assert isinstance(p.chunker, LegalTextChunker)
        assert isinstance(p.embedder, LegalEmbedder)
        assert isinstance(p.ingestor, SQLiteVSSIngestor)
