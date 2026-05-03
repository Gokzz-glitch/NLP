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
import random
from pathlib import Path
from typing import Dict, List

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

    def _rename_with_retry(self, src: Path, dst: Path, attempts: int = 5, base_delay: float = 0.05) -> bool:
        """Retry atomic rename with jittered exponential backoff for transient FS failures."""
        for i in range(attempts):
            try:
                src.rename(dst)
                return True
            except FileNotFoundError:
                return False
            except OSError:
                if i == attempts - 1:
                    return False
                sleep_s = base_delay * (2 ** i) + random.uniform(0.0, base_delay)
                time.sleep(sleep_s)
        return False

    def run_once(self, data_dir: str) -> Dict[str, int]:
        raw_dir = Path(data_dir)
        if not raw_dir.exists():
            logger.error(f"ERR_DATA_MISSING: {data_dir} not found.")
            return {"claimed": 0, "reclaimed_stale": 0, "processed": 0, "failed": 0, "claim_conflicts": 0}

        files = list(raw_dir.glob("*.pdf"))
        if not files:
            logger.info("No new PDFs in /raw_data.")
            return {"claimed": 0, "reclaimed_stale": 0, "processed": 0, "failed": 0, "claim_conflicts": 0}

        metrics = {"claimed": 0, "reclaimed_stale": 0, "processed": 0, "failed": 0, "claim_conflicts": 0}

        self.embedder.load()
        self.ingestor.connect()
        self.ingestor.ensure_schema()

        processed_dir = raw_dir / "processed"
        failed_dir = raw_dir / "failed"
        processing_dir = raw_dir / "processing"
        processed_dir.mkdir(exist_ok=True)
        failed_dir.mkdir(exist_ok=True)
        processing_dir.mkdir(exist_ok=True)

        try:
            for pdf_path in files:
                claim_path = processing_dir / pdf_path.name
                if claim_path.exists() and (time.time() - claim_path.stat().st_mtime) > 3600:
                    # Recover stale lock from a dead worker.
                    stale_target = raw_dir / pdf_path.name
                    if not stale_target.exists():
                        if self._rename_with_retry(claim_path, stale_target):
                            metrics["reclaimed_stale"] += 1
                if self._rename_with_retry(pdf_path, processing_dir / pdf_path.name):
                    claim_path = processing_dir / pdf_path.name
                    metrics["claimed"] += 1
                else:
                    metrics["claim_conflicts"] += 1
                    continue
                try:
                # 1. Extract
                    result = self.extractor.extract(claim_path)
                    if result.status == ExtractionStatus.FAILED:
                        self._rename_with_retry(claim_path, failed_dir / pdf_path.name)
                        metrics["failed"] += 1
                        continue
                
                # 2. Chunk
                    chunks = self.chunker.chunk(result)
                
                # 3. Embed
                    embeddings = self.embedder.embed_chunks(chunks)
                
                # 4. Ingest
                    self.ingestor.ingest(embeddings)
                    self._rename_with_retry(claim_path, processed_dir / pdf_path.name)
                    metrics["processed"] += 1

                except Exception as e:
                    logger.error(f"Pipeline failure on {pdf_path.name}: {e}")
                    self._rename_with_retry(claim_path, failed_dir / pdf_path.name)
                    metrics["failed"] += 1
        finally:
            self.ingestor.close()
        logger.info(f"ETL metrics: {metrics}")
        logger.info("ETL Pipeline Batch complete.")
        return metrics

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pipeline = ETLPipeline()
    pipeline.run_once("raw_data")
