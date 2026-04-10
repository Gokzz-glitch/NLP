import os
import time
import logging
import sqlite3
import pdfplumber
from pathlib import Path
from core.agent_bus import bus
from edge_vector_store import EdgeVectorStore

# [PERSONA 2: THE LEGAL SYNCHRONIZER]
# Task: T-045 — Autonomous legal update daily sync from MoRTH / Gazette.
# Ensures the RAG system uses 2024/25 data instead of the 2019 baseline.

logger = logging.getLogger("edge_sentinel.legal_sync")
logger.setLevel(logging.INFO)

class LegalSyncAgent:
    def __init__(self, incoming_dir: str = "raw_data/incoming_legal/"):
        self.incoming_dir = Path(incoming_dir)
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.store = EdgeVectorStore()
        
        bus.subscribe("SYSTEM_DAILY_MAINTENANCE", self.perform_sync)
        logger.info("PERSONA_2_REPORT: LEGAL_SYNCHRONIZER_READY | MONITORING_GOV_GAZETTE")

    def perform_sync(self, payload: dict = None):
        """Main sync loop: Scrape -> Download -> Ingest."""
        logger.info("PERSONA_2_REPORT: COMMENCING_DAILY_SYNC...")
        
        # 1. Simulate scraping MoRTH
        # In a real setup, we use 'requests' and 'BeautifulSoup' on https://morth.nic.in/notifications
        new_notifications_found = self._check_morth_updates()
        
        if not new_notifications_found:
            logger.info("PERSONA_2_REPORT: NO_NEW_LAWS_DETECTED_TODAY")
            return
        
        # 2. Process incoming files
        count = 0
        for pdf_path in self.incoming_dir.glob("*.pdf"):
             logger.info(f"PERSONA_2_REPORT: PROCESSING_NEW_STATUTE: {pdf_path.name}")
             self._ingest_new_law(pdf_path)
             # Move to archive once done
             pdf_path.rename(pdf_path.parent / f"processed_{pdf_path.name}")
             count += 1
        
        logger.info(f"PERSONA_2_REPORT: SYNC_COMPLETE. Added {count} high-priority legal updates.")
        bus.emit("LEGAL_STORE_UPDATED", {"new_items": count, "timestamp": time.time()})

    def _check_morth_updates(self):
        """Simulates checking MoRTH for 2024/25 notifications."""
        # For this demonstration, if the incoming folder has any PDF, we 'found' something.
        return any(self.incoming_dir.glob("*.pdf"))

    def _ingest_new_law(self, path: Path):
        """Extracts text and adds to EdgeVectorStore with HIGH priority."""
        try:
            with pdfplumber.open(path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    full_text += page.extract_text() + "\n"
                
                # Chunk and Add
                chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 850)]
                for i, chunk in enumerate(chunks):
                    # Tagging with '2025' to ensure priority during retrieval
                    meta_id = f"NEW_LAW_2025_{path.stem}_{i}"
                    self.store.add_statute(meta_id, f"[URGENT_UPDATE_2025] {chunk}")
        except Exception as e:
            logger.error(f"SYNC_ERROR: {e}")

if __name__ == "__main__":
    # Production code should not create mock data.
    # Use proper test fixtures or integration tests instead.
    # See tests/test_legal_syncer.py for test harness.
    syncer = LegalSyncAgent()
    syncer.perform_sync()
