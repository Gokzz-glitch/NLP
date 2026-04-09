"""
etl/embedder.py
SmartSalai Edge-Sentinel — Persona 6: ETL Data Scavenger
Stage 3 of 4: Legal Chunks → Float32 Embedding Vectors

FUNCTION:
  Generates dense embedding vectors from LegalChunk.embedding_input strings.
  Fully offline. Zero cloud API calls.

MODEL SELECTION HIERARCHY (in order of preference):
  1. ONNX_INT8_LOCAL  : sentence-transformers model exported to ONNX INT8.
                        Fastest on NPU / CPU. Default for production.
                        Recommended model: "koc-nlp/roberta-base-indic-squad"
                        or "ai4bharat/indic-bert" (both have ONNX exports).
  2. SENTENCE_TRANSFORMERS_FP32 : Direct sentence-transformers inference (FP32).
                        Used during training / development.
                        Default model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                        Rationale: supports Hindi + Tamil + English in 384 dims.
  3. HASH_FALLBACK     : TF-IDF-style sparse hash embedding (2048 dims).
                        Zero ML dependency. Used in CI or if torch unavailable.
                        NOT suitable for semantic RAG — debug/CI only.

OUTPUT:
  List[EmbeddingResult] — each contains chunk_id + float32 numpy vector.

DIMENSION:
  384 (MiniLM-L12-v2) or 768 (IndicBERT). Configurable.
  sqlite_vss_ingestor.py must be initialized with matching dimension.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

import numpy as np

from .text_chunker import LegalChunk

logger = logging.getLogger("edge_sentinel.etl.embedder")
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default offline embedding model — multilingual, covers Hindi + Tamil + English.
# 384 dimensions, max_seq_length=512, ~117MB on disk.
# Source: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
DEFAULT_ST_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

DEFAULT_EMBEDDING_DIM: int = 384

# ONNX INT8 model path (relative to project root). Operator must export using
# export_sentence_transformer_to_onnx() below before switching to ONNX mode.
DEFAULT_ONNX_MODEL_PATH: str = "models/embedder_int8.onnx"

HASH_FALLBACK_DIM: int = 2048  # Sparse hash fallback dimension

# Batch size for embedding inference — larger = faster; cap for RAM safety
DEFAULT_BATCH_SIZE: int = 32


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

class EmbedderMode(Enum):
    ONNX_INT8_LOCAL             = "ONNX_INT8_LOCAL"
    SENTENCE_TRANSFORMERS_FP32  = "SENTENCE_TRANSFORMERS_FP32"
    HASH_FALLBACK               = "HASH_FALLBACK"


@dataclass
class EmbeddingResult:
    """
    Output of the embedding stage for a single chunk.
    Passed directly to sqlite_vss_ingestor.py (Stage 4).
    """
    chunk_id: str
    vector: np.ndarray           # float32, shape (embedding_dim,)
    embedding_dim: int
    model_id: str               # Model name or "HASH_FALLBACK"
    inference_time_ms: float
    chunk_ref: LegalChunk        # Back-reference to source chunk


# ---------------------------------------------------------------------------
# ONNX Export Utility
# ---------------------------------------------------------------------------

def export_sentence_transformer_to_onnx(
    model_name: str = DEFAULT_ST_MODEL,
    output_path: str = DEFAULT_ONNX_MODEL_PATH,
    quantize_int8: bool = True,
    max_seq_length: int = 512,
) -> str:
    """
    Exports a sentence-transformers model to ONNX (FP32) then optionally
    applies dynamic INT8 weight quantization for NPU deployment.

    Must be called ONCE on a host machine with full PyTorch installed.
    The resulting .onnx file is then deployed to the Android device.

    Args:
        model_name    : HuggingFace model identifier
        output_path   : Destination for the quantized .onnx file
        quantize_int8 : Apply onnxruntime dynamic INT8 quantization
        max_seq_length: Maximum token sequence length

    Usage:
        python -c "from etl.embedder import export_sentence_transformer_to_onnx; \
                   export_sentence_transformer_to_onnx()"
    """
    import torch
    from pathlib import Path
    from transformers import AutoTokenizer, AutoModel

    logger.info(f"[P6/Embedder] Exporting {model_name} → ONNX")

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()

    dummy_text = "Section 183 Motor Vehicles Act speeding penalty Tamil Nadu"
    inputs = tokenizer(
        dummy_text,
        return_tensors="pt",
        max_length=max_seq_length,
        padding="max_length",
        truncation=True,
    )

    fp32_path = output_path.replace(".onnx", "_fp32.onnx")
    Path(fp32_path).parent.mkdir(parents=True, exist_ok=True)

    with torch.no_grad():
        torch.onnx.export(
            model,
            (inputs["input_ids"], inputs["attention_mask"]),
            fp32_path,
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state"],
            dynamic_axes={
                "input_ids":       {0: "batch", 1: "seq_len"},
                "attention_mask":  {0: "batch", 1: "seq_len"},
                "last_hidden_state": {0: "batch", 1: "seq_len"},
            },
            opset_version=17,
            do_constant_folding=True,
        )
    logger.info(f"[P6/Embedder] FP32 ONNX → {fp32_path}")

    if quantize_int8:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(fp32_path, output_path, weight_type=QuantType.QInt8)
        logger.info(f"[P6/Embedder] INT8 ONNX → {output_path}")
        return output_path
    return fp32_path


# ---------------------------------------------------------------------------
# Mean Pooling (shared across ST and ONNX modes)
# ---------------------------------------------------------------------------

def _mean_pool(
    token_embeddings: np.ndarray,   # (batch, seq_len, hidden_dim)
    attention_mask: np.ndarray,     # (batch, seq_len)
) -> np.ndarray:
    """
    Mean pooling over token dimension, masked by attention_mask.
    Returns shape (batch, hidden_dim).
    """
    mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)  # (B, S, 1)
    sum_embeddings = (token_embeddings * mask_expanded).sum(axis=1)      # (B, H)
    sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)  # (B, 1)
    return sum_embeddings / sum_mask                                       # (B, H)


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize embedding vectors. Shape: (batch, dim)."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.clip(norms, a_min=1e-12, a_max=None)
    return vectors / norms


# ---------------------------------------------------------------------------
# Hash Fallback Embedder (no ML — CI / cold-start / zero-dep mode)
# ---------------------------------------------------------------------------

def _hash_embed(text: str, dim: int = HASH_FALLBACK_DIM) -> np.ndarray:
    """
    Deterministic sparse-hash embedding using SHA-256 seeded random projection.
    NOT semantically meaningful. Used only for pipeline smoke-tests or CI.

    For every token (whitespace-split), hash to a bin in [0, dim) and
    accumulate ±1 based on hash parity. L2-normalize. Returns float32 (dim,).
    """
    vec = np.zeros(dim, dtype=np.float32)
    tokens = text.lower().split()
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        # Use first 4 bytes as bin index, next byte as sign
        idx  = int.from_bytes(digest[:4], "big") % dim
        sign = 1 if digest[4] & 1 else -1
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


# ---------------------------------------------------------------------------
# Main Embedder Class
# ---------------------------------------------------------------------------

class LegalEmbedder:
    """
    Converts LegalChunk objects into float32 embedding vectors.

    Modes (auto-selected based on available libraries + model files):
      ONNX_INT8_LOCAL            → fastest; requires built .onnx file
      SENTENCE_TRANSFORMERS_FP32 → development; requires sentence-transformers
      HASH_FALLBACK              → zero-dependency; not semantic

    Usage:
        embedder = LegalEmbedder()
        embedder.load()
        results = embedder.embed_chunks(chunks)
        # pass results to SQLiteVSSIngestor
    """

    def __init__(
        self,
        onnx_model_path: Optional[str] = DEFAULT_ONNX_MODEL_PATH,
        st_model_name: str = DEFAULT_ST_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        force_hash_fallback: bool = False,
    ) -> None:
        self.onnx_model_path = onnx_model_path
        self.st_model_name = st_model_name
        self.batch_size = batch_size
        self.embedding_dim = embedding_dim
        self._force_hash_fallback = force_hash_fallback

        self._mode: Optional[EmbedderMode] = None
        self._tokenizer = None     # HuggingFace tokenizer (ST or ONNX mode)
        self._st_model  = None     # sentence_transformers.SentenceTransformer
        self._ort_session = None   # onnxruntime.InferenceSession

    @property
    def mode(self) -> Optional[EmbedderMode]:
        return self._mode

    def load(self) -> EmbedderMode:
        """
        Attempt to load the best available embedding backend.
        Call once at application startup.

        Priority: ONNX_INT8 → SentenceTransformers → HASH_FALLBACK

        Pass ``force_hash_fallback=True`` at construction time to skip all
        ML backends and use the deterministic hash fallback.  Useful for
        unit tests and CI environments without GPU / model weights.
        """
        import os

        # Forced fallback — skip all ML backends (for CI / unit tests)
        if self._force_hash_fallback:
            self.embedding_dim = HASH_FALLBACK_DIM
            self._mode = EmbedderMode.HASH_FALLBACK
            logger.info("[P6/Embedder] Mode: HASH_FALLBACK (forced)")
            return self._mode

        # --- Try ONNX INT8 ---
        if self.onnx_model_path and os.path.exists(self.onnx_model_path):
            try:
                import onnxruntime as ort
                from transformers import AutoTokenizer

                sess_opts = ort.SessionOptions()
                sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self._ort_session = ort.InferenceSession(
                    self.onnx_model_path,
                    sess_options=sess_opts,
                    providers=["NNAPIExecutionProvider", "CPUExecutionProvider"],
                )
                self._tokenizer = AutoTokenizer.from_pretrained(self.st_model_name)
                self._mode = EmbedderMode.ONNX_INT8_LOCAL
                logger.info(f"[P6/Embedder] Mode: ONNX_INT8_LOCAL ({self.onnx_model_path})")
                return self._mode
            except Exception as exc:
                logger.warning(f"[P6/Embedder] ONNX load failed: {exc} — trying SentenceTransformers")

        # --- Try SentenceTransformers FP32 ---
        try:
            from sentence_transformers import SentenceTransformer

            self._st_model = SentenceTransformer(self.st_model_name)
            self.embedding_dim = self._st_model.get_sentence_embedding_dimension()
            self._mode = EmbedderMode.SENTENCE_TRANSFORMERS_FP32
            logger.info(
                f"[P6/Embedder] Mode: SENTENCE_TRANSFORMERS_FP32 | "
                f"model={self.st_model_name} | dim={self.embedding_dim}"
            )
            return self._mode
        except ImportError:
            logger.warning("[P6/Embedder] sentence-transformers not installed — falling back to HASH_FALLBACK")
        except Exception as exc:
            logger.warning(f"[P6/Embedder] SentenceTransformers load failed: {exc} — falling back to HASH_FALLBACK")

        # --- Hash Fallback ---
        self.embedding_dim = HASH_FALLBACK_DIM
        self._mode = EmbedderMode.HASH_FALLBACK
        logger.warning(
            "[P6/Embedder] Mode: HASH_FALLBACK — vectors are NOT semantically meaningful. "
            "Install sentence-transformers for production use."
        )
        return self._mode

    def embed_chunks(self, chunks: List[LegalChunk]) -> List[EmbeddingResult]:
        """
        Embed a list of LegalChunk objects.
        Processes in batches of self.batch_size.
        Returns one EmbeddingResult per chunk (preserves order).
        """
        if self._mode is None:
            raise RuntimeError("LegalEmbedder.load() must be called before embed_chunks().")

        results: List[EmbeddingResult] = []

        for batch_start in range(0, len(chunks), self.batch_size):
            batch = chunks[batch_start : batch_start + self.batch_size]
            texts = [c.embedding_input for c in batch]

            t0 = time.monotonic()
            vectors = self._embed_batch(texts)  # (len(batch), embedding_dim)
            elapsed_ms = (time.monotonic() - t0) * 1000
            per_chunk_ms = elapsed_ms / len(batch)

            for chunk, vec in zip(batch, vectors):
                results.append(EmbeddingResult(
                    chunk_id=chunk.chunk_id,
                    vector=vec.astype(np.float32),
                    embedding_dim=self.embedding_dim,
                    model_id=self._model_id_str(),
                    inference_time_ms=per_chunk_ms,
                    chunk_ref=chunk,
                ))

            logger.debug(
                f"[P6/Embedder] Batch {batch_start//self.batch_size + 1}: "
                f"{len(batch)} chunks in {elapsed_ms:.1f}ms "
                f"({per_chunk_ms:.1f}ms/chunk)"
            )

        logger.info(f"[P6/Embedder] Embedded {len(results)} chunks via {self._mode.value}")
        return results

    # ------------------------------------------------------------------
    # Internal: batch embedding dispatch
    # ------------------------------------------------------------------

    def _embed_batch(self, texts: List[str]) -> np.ndarray:
        """Returns (batch, embedding_dim) float32 array."""

        if self._mode == EmbedderMode.SENTENCE_TRANSFORMERS_FP32:
            vecs = self._st_model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            return vecs.astype(np.float32)

        elif self._mode == EmbedderMode.ONNX_INT8_LOCAL:
            return self._onnx_embed_batch(texts)

        else:  # HASH_FALLBACK
            return np.vstack([_hash_embed(t, self.embedding_dim) for t in texts])

    def _onnx_embed_batch(self, texts: List[str]) -> np.ndarray:
        """
        Tokenize texts, run ONNX session, apply mean pooling + L2 norm.
        """
        enc = self._tokenizer(
            texts,
            max_length=512,
            padding=True,
            truncation=True,
            return_tensors="np",
        )
        input_ids      = enc["input_ids"].astype(np.int64)
        attention_mask = enc["attention_mask"].astype(np.int64)

        outputs = self._ort_session.run(
            ["last_hidden_state"],
            {"input_ids": input_ids, "attention_mask": attention_mask},
        )
        token_embeddings = outputs[0].astype(np.float32)  # (B, seq, H)
        pooled = _mean_pool(token_embeddings, attention_mask.astype(np.float32))
        return _l2_normalize(pooled)

    def _model_id_str(self) -> str:
        if self._mode == EmbedderMode.ONNX_INT8_LOCAL:
            return f"ONNX_INT8:{self.onnx_model_path}"
        if self._mode == EmbedderMode.SENTENCE_TRANSFORMERS_FP32:
            return f"ST_FP32:{self.st_model_name}"
        return "HASH_FALLBACK"
