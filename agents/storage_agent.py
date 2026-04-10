"""
Agent 15 — Storage Sentinel
Monitors Google Drive disk space and prunes old training 'runs' and 'logs'.
Ensures the system never fills up the local storage.
"""

import os
import shutil
import logging
import psutil
from pathlib import Path
from datetime import datetime, timedelta
from core.knowledge_ledger import ledger
from agents.system_agents import BaseAgent

logger = logging.getLogger(__name__)

class StorageSentinelAgent(BaseAgent):
    """Agent 15: Disk management and pruning."""

    def __init__(self):
        super().__init__("Agent15-StorageSentinel", sleep_interval=300) # Check every 5 mins
        self.root_dir = Path("g:/My Drive/NLP")
        self.runs_dir = self.root_dir / "runs" / "detect"
        self.logs_dir = self.root_dir / "logs"
        self.min_free_gb = 2.0  # Alert below 2GB
        self.prune_threshold_gb = 5.0 # Prune if runs/ > 5GB
        self.max_history_entries = 50

    def get_disk_info(self):
        try:
            usage = psutil.disk_usage(self.root_dir)
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            percent = usage.percent
            return free_gb, total_gb, percent
        except Exception as e:
            logger.error(f"[StorageSentinel] Disk check failed: {e}")
            return 0, 0, 0

    def get_runs_size_gb(self):
        total_size = 0
        if not self.runs_dir.exists():
            return 0
        for path in self.runs_dir.rglob('*'):
            if path.is_file():
                total_size += path.stat().st_size
        return total_size / (1024**3)

    def prune_old_runs(self):
        """Keep only the 2 most recent training sessions."""
        if not self.runs_dir.exists():
            return
        
        # List all directories in runs/detect
        sessions = [d for d in self.runs_dir.iterdir() if d.is_dir()]
        # Sort by modification time (descending)
        sessions.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        if len(sessions) > 2:
            to_delete = sessions[2:]
            for folder in to_delete:
                try:
                    shutil.rmtree(folder)
                    logger.info(f"[StorageSentinel] Pruned old run: {folder.name}")
                    ledger.log_finding(self.name, "storage_event", {
                        "action": "pruned_folder",
                        "folder": folder.name,
                        "reason": "Automatic retention policy (Keep Latest 2)"
                    })
                except Exception as e:
                    logger.error(f"[StorageSentinel] Failed to delete {folder}: {e}")

    def prune_heartbeats(self):
        """Standard 60-min TTL for noise [CWE-400]"""
        # Pruning redundant agent heartbeats from the ledger to prevent DB lock/bloat
        ledger.delete_findings(finding_type="agent_heartbeat", older_than_mins=60)
        ledger.delete_findings(finding_type="heartbeat", older_than_mins=60)

    async def iteration(self):
        free_gb, total_gb, percent = self.get_disk_info()
        runs_size_gb = self.get_runs_size_gb()
        
        status = "HEALTHY"
        if free_gb < self.min_free_gb:
            status = "CRITICAL (Low Space)"
            self.prune_old_runs()
        elif runs_size_gb > self.prune_threshold_gb:
            status = "WARNING (Heavy Usage)"
            self.prune_old_runs()

        # [MAINTENANCE FIX #112]: Prune noise logs every cycle
        self.prune_heartbeats()

        ledger.log_finding(self.name, "heartbeat", {
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "usage_percent": percent,
            "runs_size_gb": round(runs_size_gb, 2),
            "status": status
        })
        
        logger.info(f"[StorageSentinel] Disk Status: {status} | Free: {free_gb:.2f}GB | Runs: {runs_size_gb:.2f}GB")

    async def generate_response(self, question: str) -> str:
        free_gb, _, percent = self.get_disk_info()
        runs_size = self.get_runs_size_gb()
        return (
            f"I am Agent 15 — Storage Sentinel. "
            f"Drive Status: {percent}% full ({free_gb:.2f}GB free). "
            f"Currently managing {runs_size:.2f}GB of training data. "
            f"Retention Policy: Automatically keeping only the 2 latest training versions for safety."
        )

if __name__ == "__main__":
    import asyncio
    agent = StorageSentinelAgent()
    asyncio.run(agent.run())
