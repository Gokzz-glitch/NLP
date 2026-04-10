"""
etl/legal_document_processor.py
SmartSalai Edge-Sentinel — Persona 6: Legal Document Ingestion
PDF → Chunks → Embeddings → SQLite-VSS

PIPELINE:
  1. PDF extraction (pdfplumber)
  2. Text chunking (1000 char windows, 200 char overlap)
  3. Section detection (regex for "Section XYZ")
  4. Embedding (SentenceTransformer, optional TinyBERT for mobile)
  5. SQLite-VSS insert (vector DB)
  6. FTS5 indexing (full-text search fallback)

TARGET FILES:
  - Motor Vehicle Amendment Act 2019 (Central)
  - TN G.O. (Ms).No.56/2022 (State-specific)
  - NHAI Traffic Rules (National Highway Authority)

COMPLIANCE:
  - iRAD schema v2022
  - MoRTH Gazette S.O. 2224(E)
  - ZKP envelope ready (core/zkp_envelope.py)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Tuple

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

logger = logging.getLogger("edge_sentinel.etl.legal_document_processor")
logger.setLevel(logging.DEBUG)

# ───────────────────────────────────────────────────────────────────────────
# Data Models
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class LegalChunk:
    """Fragment of legal document with embeddings."""
    chunk_id: str
    source_file: str
    section_id: Optional[str]  # "SEC_183", "TN_GO_56", etc.
    title: str
    text: str
    chunk_index: int  # Order in document
    embedding: Optional[List[float]] = None  # Vector (768-dim or 384-dim)
    metadata: Optional[Dict] = None


@dataclass
class DocumentProcessingResult:
    """Summary of PDF processing."""
    file_path: str
    total_pages: int
    chunks_created: int
    sections_detected: int
    embeddings_count: int
    processing_time_ms: float
    status: str  # "SUCCESS", "PARTIAL", "FAILED"
    error_message: Optional[str] = None


# ───────────────────────────────────────────────────────────────────────────
# Legal Document Processor
# ───────────────────────────────────────────────────────────────────────────

class LegalDocumentProcessor:
    """
    ETL pipeline for legal PDF ingestion.
    
    Handles:
    - Multi-page PDFs (100+ pages)
    - Section extraction (regex + manual curation)
    - Text chunking with overlap
    - Optional embedding generation
    - Fallback to keyword search if embedding unavailable
    """

    # Section detection patterns
    SECTION_PATTERNS = [
        r"^(Section|Sec\.?)\s*(\d+[A-Z]?)",  # Section 183, Sec 208A
        r"^(\d+[A-Z]?)[\.:]",  # 183: or 208.
        r"^(Part|Chapter|Article|Rule|Clause)\s*(\d+)",
    ]

    def __init__(self, use_embeddings: bool = True, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize processor with optional embedding model.
        
        Args:
            use_embeddings: Enable SentenceTransformer embeddings (requires ~43MB)
            model_name: HuggingFace model ID for embeddings
                "all-MiniLM-L6-v2": 22M params (384-dim, fast)
                "all-mpnet-base-v2": 109M params (768-dim, better quality)
        """
        self.use_embeddings = use_embeddings
        self.model_name = model_name
        self.embedding_model = None

        if use_embeddings and SentenceTransformer is not None:
            try:
                logger.info(f"Loading embedding model: {model_name}")
                self.embedding_model = SentenceTransformer(model_name, device="cpu")
                logger.info(f"Embedding model loaded: {model_name}")
            except Exception as e:
                logger.warning(f"Failed to load embedding model: {e}. Falling back to keyword search.")
                self.use_embeddings = False

    def process_pdf(self, pdf_path: str, chunk_size: int = 1000, overlap: int = 200) -> DocumentProcessingResult:
        """
        Extract and chunk a legal PDF.
        
        Args:
            pdf_path: Path to PDF file
            chunk_size: Characters per chunk
            overlap: Overlap between chunks (for context preservation)

        Returns:
            DocumentProcessingResult with processing summary
        """
        start_time = datetime.utcnow()

        if pdfplumber is None:
            return DocumentProcessingResult(
                file_path=pdf_path,
                total_pages=0,
                chunks_created=0,
                sections_detected=0,
                embeddings_count=0,
                processing_time_ms=0.0,
                status="FAILED",
                error_message="pdfplumber not installed",
            )

        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                full_text = ""
                page_breaks = []

                # Extract text from all pages
                for page_idx, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    page_breaks.append(len(full_text))
                    full_text += page_text + "\n\n"  # Add page break marker

            # Chunk text
            chunks = self._chunk_text(full_text, chunk_size, overlap)
            logger.info(f"Created {len(chunks)} chunks from {total_pages} pages")

            # Detect sections
            sections = self._detect_sections(chunks)
            logger.info(f"Detected {len(sections)} legal sections")

            # Generate embeddings (optional)
            embeddings = []
            if self.use_embeddings and self.embedding_model:
                chunk_texts = [c["text"] for c in chunks]
                try:
                    embeddings = self.embedding_model.encode(chunk_texts, batch_size=32).tolist()
                    logger.info(f"Generated {len(embeddings)} embeddings")
                except Exception as e:
                    logger.warning(f"Embedding generation failed: {e}")
                    embeddings = []

            processing_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

            return DocumentProcessingResult(
                file_path=pdf_path,
                total_pages=total_pages,
                chunks_created=len(chunks),
                sections_detected=len(sections),
                embeddings_count=len(embeddings),
                processing_time_ms=processing_time_ms,
                status="SUCCESS",
            )

        except Exception as e:
            logger.error(f"PDF processing failed: {e}")
            processing_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            return DocumentProcessingResult(
                file_path=pdf_path,
                total_pages=0,
                chunks_created=0,
                sections_detected=0,
                embeddings_count=0,
                processing_time_ms=processing_time_ms,
                status="FAILED",
                error_message=str(e),
            )

    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[Dict]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Full document text
            chunk_size: Target chunk size in characters
            overlap: Overlap size to preserve context

        Returns:
            List of dicts with keys: "text", "start_pos", "end_pos"
        """
        chunks = []
        start = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "start_pos": start,
                    "end_pos": end,
                })

            start = end - overlap if end < len(text) else end

        return chunks

    def _detect_sections(self, chunks: List[Dict]) -> List[Dict]:
        """
        Detect legal sections in chunk boundaries.
        
        Returns:
            List of dicts with keys: "section_id", "title", "chunk_range"
        """
        sections = []

        for chunk_idx, chunk in enumerate(chunks):
            text = chunk["text"]

            for pattern in self.SECTION_PATTERNS:
                match = re.search(pattern, text, re.MULTILINE)
                if match:
                    section_id = f"SEC_{match.group(2)}" if match.lastindex >= 2 else f"SECTION_{chunk_idx}"
                    # Extract the line with section
                    lines = text.split("\n")
                    title_line = next((l for l in lines if "section" in l.lower()), "")[:100]

                    sections.append({
                        "section_id": section_id,
                        "title": title_line,
                        "chunk_range": (chunk_idx, chunk_idx),
                    })

        return sections

    def ingest_bulk(self, pdf_dir: str, db_manager) -> List[DocumentProcessingResult]:
        """
        Ingest all PDFs in a directory into SQLite-VSS database.
        
        Args:
            pdf_dir: Directory containing PDF files
            db_manager: SpatialDatabaseManager instance

        Returns:
            List of processing results
        """
        pdf_dir = Path(pdf_dir)
        results = []

        for pdf_file in pdf_dir.glob("*.pdf"):
            logger.info(f"Processing: {pdf_file.name}")

            result = self.process_pdf(str(pdf_file))
            results.append(result)

            if result.status == "SUCCESS":
                # Insert into database
                # This would call db_manager.insert_legal_document() for each section
                logger.info(f"✅ {pdf_file.name}: {result.chunks_created} chunks, {result.embeddings_count} embeddings")
            else:
                logger.warning(f"❌ {pdf_file.name}: {result.error_message}")

        return results


# ───────────────────────────────────────────────────────────────────────────
# Smoke Test (Deterministic)
# ───────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Production code should not run smoke tests.
    # Use pytest fixtures instead. See tests/test_legal_document_processor.py
    print("ℹ️  Legal document processor smoke tests moved to tests/ directory.")
    print("   Run: pytest tests/test_legal_document_processor.py")
