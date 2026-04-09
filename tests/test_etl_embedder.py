"""
tests/test_etl_embedder.py

Unit tests for etl/embedder.py — LegalEmbedder (HASH_FALLBACK mode),
_hash_embed, _l2_normalize, _mean_pool, EmbeddingResult.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np

from etl.embedder import (
    LegalEmbedder,
    EmbeddingResult,
    EmbedderMode,
    _hash_embed,
    _l2_normalize,
    _mean_pool,
    HASH_FALLBACK_DIM,
    DEFAULT_EMBEDDING_DIM,
)
from etl.text_chunker import LegalChunk


def _make_chunk(text="test legal text", idx=0):
    return LegalChunk(
        chunk_id=f"abc-c{idx:04d}",
        source_doc="test.pdf",
        file_sha256="abcdef12",
        doc_type="MVA_ACT",
        page_numbers=[1],
        section_id="183",
        chunk_index=idx,
        text=text,
        char_count=len(text),
    )


# ---------------------------------------------------------------------------
# _hash_embed
# ---------------------------------------------------------------------------

class TestHashEmbed:

    def test_output_shape(self):
        v = _hash_embed("hello", HASH_FALLBACK_DIM)
        assert v.shape == (HASH_FALLBACK_DIM,)

    def test_output_dtype_float32(self):
        v = _hash_embed("hello", HASH_FALLBACK_DIM)
        assert v.dtype == np.float32

    def test_output_is_unit_vector(self):
        v = _hash_embed("hello world", HASH_FALLBACK_DIM)
        assert abs(np.linalg.norm(v) - 1.0) < 1e-5

    def test_deterministic(self):
        v1 = _hash_embed("same text", HASH_FALLBACK_DIM)
        v2 = _hash_embed("same text", HASH_FALLBACK_DIM)
        assert np.allclose(v1, v2)

    def test_different_texts_different_vectors(self):
        v1 = _hash_embed("legal text A", HASH_FALLBACK_DIM)
        v2 = _hash_embed("legal text B", HASH_FALLBACK_DIM)
        assert not np.allclose(v1, v2)

    def test_custom_dim(self):
        v = _hash_embed("test", 512)
        assert v.shape == (512,)

    def test_empty_string(self):
        v = _hash_embed("", HASH_FALLBACK_DIM)
        assert v.shape == (HASH_FALLBACK_DIM,)
        assert np.isfinite(v).all()


# ---------------------------------------------------------------------------
# _l2_normalize
# ---------------------------------------------------------------------------

class TestL2Normalize:

    def test_unit_vectors_unchanged(self):
        v = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        result = _l2_normalize(v)
        assert np.allclose(result, v)

    def test_normalizes_to_unit(self):
        v = np.array([[3.0, 4.0]], dtype=np.float32)  # norm=5
        result = _l2_normalize(v)
        assert abs(np.linalg.norm(result[0]) - 1.0) < 1e-5

    def test_batch_normalization(self):
        v = np.ones((4, 8), dtype=np.float32)
        result = _l2_normalize(v)
        norms = np.linalg.norm(result, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)

    def test_zero_vector_no_nan(self):
        """Clip prevents division by zero — result must be finite (all zeros)."""
        v = np.zeros((1, 4), dtype=np.float32)
        result = _l2_normalize(v)
        assert np.isfinite(result).all()
        assert not np.any(np.isnan(result))

    def test_output_shape_preserved(self):
        v = np.random.rand(3, 16).astype(np.float32)
        result = _l2_normalize(v)
        assert result.shape == v.shape


# ---------------------------------------------------------------------------
# _mean_pool
# ---------------------------------------------------------------------------

class TestMeanPool:

    def test_basic_mean_pooling(self):
        token_embeddings = np.array([[[1.0, 2.0], [3.0, 4.0]]], dtype=np.float32)  # (1, 2, 2)
        attention_mask = np.array([[1, 1]], dtype=np.float32)
        result = _mean_pool(token_embeddings, attention_mask)
        expected = np.array([[2.0, 3.0]], dtype=np.float32)
        assert np.allclose(result, expected, atol=1e-5)

    def test_masked_tokens_excluded(self):
        token_embeddings = np.array([[[1.0, 2.0], [100.0, 200.0]]], dtype=np.float32)
        attention_mask = np.array([[1, 0]], dtype=np.float32)  # second token masked
        result = _mean_pool(token_embeddings, attention_mask)
        assert np.allclose(result, [[1.0, 2.0]], atol=1e-5)

    def test_output_shape(self):
        B, T, H = 3, 10, 32
        token_embeddings = np.random.rand(B, T, H).astype(np.float32)
        attention_mask = np.ones((B, T), dtype=np.float32)
        result = _mean_pool(token_embeddings, attention_mask)
        assert result.shape == (B, H)


# ---------------------------------------------------------------------------
# LegalEmbedder (HASH_FALLBACK mode)
# ---------------------------------------------------------------------------

class TestLegalEmbedderHashFallback:
    """
    These tests force HASH_FALLBACK mode by passing force_hash=True or
    by not having sentence-transformers installed.  Since sentence-transformers
    IS installed, we patch the import to trigger the fallback.
    """

    def _embedder(self):
        e = LegalEmbedder(force_hash_fallback=True)
        e.load()
        return e

    def test_load_returns_hash_fallback_mode(self):
        e = self._embedder()
        assert e.mode == EmbedderMode.HASH_FALLBACK

    def test_embed_chunks_returns_list(self):
        e = self._embedder()
        chunks = [_make_chunk("legal text", i) for i in range(3)]
        results = e.embed_chunks(chunks)
        assert isinstance(results, list)
        assert len(results) == 3

    def test_embed_chunks_output_type(self):
        e = self._embedder()
        results = e.embed_chunks([_make_chunk()])
        assert isinstance(results[0], EmbeddingResult)

    def test_embed_chunks_vector_shape(self):
        e = self._embedder()
        results = e.embed_chunks([_make_chunk()])
        assert results[0].vector.shape == (HASH_FALLBACK_DIM,)

    def test_embed_chunks_vector_is_float32(self):
        e = self._embedder()
        results = e.embed_chunks([_make_chunk()])
        assert results[0].vector.dtype == np.float32

    def test_embed_chunks_chunk_ref_preserved(self):
        e = self._embedder()
        chunk = _make_chunk("unique text 9876", idx=7)
        results = e.embed_chunks([chunk])
        assert results[0].chunk_ref is chunk

    def test_embed_chunks_chunk_id_matches(self):
        e = self._embedder()
        chunk = _make_chunk("text", idx=3)
        results = e.embed_chunks([chunk])
        assert results[0].chunk_id == chunk.chunk_id

    def test_embed_chunks_raises_without_load(self):
        e = LegalEmbedder(force_hash_fallback=True)
        with pytest.raises(RuntimeError, match="load()"):
            e.embed_chunks([_make_chunk()])

    def test_embed_chunks_empty_list(self):
        e = self._embedder()
        results = e.embed_chunks([])
        assert results == []

    def test_embed_chunks_deterministic(self):
        e = self._embedder()
        chunk = _make_chunk("deterministic text")
        r1 = e.embed_chunks([chunk])[0]
        r2 = e.embed_chunks([chunk])[0]
        assert np.allclose(r1.vector, r2.vector)

    def test_embed_chunks_different_texts_different_vectors(self):
        e = self._embedder()
        r1 = e.embed_chunks([_make_chunk("text about speeding")])[0]
        r2 = e.embed_chunks([_make_chunk("text about helmet")])[0]
        assert not np.allclose(r1.vector, r2.vector)
