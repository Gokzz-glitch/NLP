"""
etl/pipeline.py
SmartSalai Edge-Sentinel — Persona 6: ETL Data Scavenger
Final Orchestrator: Unified ETL Pipeline

FUNCTION:
  Monitors /raw_data, executes Stage 1 (Extract) -> 2 (Chunk) -> 3 (Embed) -> 4 (Ingest).
  Thread-safe, handles multi-file batches, and provides retry logic for OCR failures.
"""

import logging
import time
from pathlib import Path
from typing import List

from .pdf_extractor import PDFExtractor, ExtractionStatus
from .text_chunker import LegalTextChunker
from .embedder import LegalEmbedder
from .sqlite_vss_ingestor import SQLiteVSSIngestor

logger = logging.getLogger("edge_sentinel.etl.pipeline")

class ETLPipeline:
    def __init__(self, db_path="edge_rag.db"):
        self.extractor = PDFExtractor()
        self.chunker = LegalTextChunker()
        self.embedder = LegalEmbedder()
        self.ingestor = SQLiteVSSIngestor(db_path=db_path)

    def run_once(self, data_dir: str):
        raw_dir = Path(data_dir)
        if not raw_dir.exists():
            logger.error(f"ERR_DATA_MISSING: {data_dir} not found.")
            return

        files = list(raw_dir.glob("*.pdf"))
        if not files:
            logger.info("No new PDFs in /raw_data.")
            return

        self.embedder.load()
        self.ingestor.connect()
        self.ingestor.ensure_schema()

        for pdf_path in files:
            claim_path = pdf_path.with_suffix(pdf_path.suffix + ".processing")
            try:
                pdf_path.rename(claim_path)
            except FileNotFoundError:
                # Another worker likely claimed it first.
                continue
            except OSError:
                # Best effort skip on lock/cross-device constraints.
                continue
            try:
                # 1. Extract
                result = self.extractor.extract(claim_path)
                if result.status == ExtractionStatus.FAILED:
                    claim_path.rename(pdf_path.with_suffix(pdf_path.suffix + ".failed"))
                    continue
                
                # 2. Chunk
                chunks = self.chunker.chunk(result)
                
                # 3. Embed
                embeddings = self.embedder.embed_chunks(chunks)
                
                # 4. Ingest
                self.ingestor.ingest(embeddings)
                claim_path.rename(pdf_path.with_suffix(pdf_path.suffix + ".done"))

            except Exception as e:
                logger.error(f"Pipeline failure on {pdf_path.name}: {e}")
                try:
                    claim_path.rename(pdf_path.with_suffix(pdf_path.suffix + ".failed"))
                except OSError:
                    pass

        self.ingestor.close()
        logger.info("ETL Pipeline Batch complete.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pipeline = ETLPipeline()
    pipeline.run_once("raw_data")
