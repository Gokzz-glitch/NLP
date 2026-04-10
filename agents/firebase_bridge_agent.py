import asyncio
import logging
import json
import os
from datetime import datetime
from typing import Dict, Any, List

from agents.base import BaseAgent
from core.knowledge_ledger import ledger
from core.firebase_client import fb_client

logger = logging.getLogger("edge_sentinel.firebase_bridge")

class FirebaseBridgeAgent(BaseAgent):
    """
    Agent 31: Firebase Bridge
    Responsible for synchronizing local findings (potholes, violations, telemetry) to the cloud.
    """
    
    SYNC_TYPES = ["pothole_verified", "violation_detected", "synergistic_insight", "colab_sync"]

    def __init__(self):
        super().__init__("Agent31-FirebaseBridge", sleep_interval=15)
        self.last_synced_id = self._load_last_id()
        logger.info(f"[{self.name}] Initialized. Last Synced ID: {self.last_synced_id}")

    def _load_last_id(self) -> int:
        """Load last synced ID from a local state file."""
        state_file = os.path.join("config", "firebase_sync_state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, "r") as f:
                    return json.load(f).get("last_id", 0)
            except:
                return 0
        return 0

    def _save_last_id(self, last_id: int):
        """Save last synced ID to a local state file."""
        os.makedirs("config", exist_ok=True)
        state_file = os.path.join("config", "firebase_sync_state.json")
        with open(state_file, "w") as f:
            json.dump({"last_id": last_id, "updated_at": datetime.now().isoformat()}, f)

    async def iteration(self):
        if not fb_client.is_connected():
            logger.warning(f"[{self.name}] Firebase not connected. Skipping sync.")
            return

        # Fetch new findings since last_synced_id
        # Note: KnowledgeLedger.get_findings sorts by timestamp DESC, 
        # but for syncing we need ASC order or filtering by ID.
        # I'll modify the ledger's get_findings to support ID filtering or just fetch latest and filter.
        
        findings = ledger.get_findings(limit=100) # Latest 100
        new_findings = [f for f in findings if f["id"] > self.last_synced_id]
        new_findings.sort(key=lambda x: x["id"]) # Process in chronological order

        if not new_findings:
            # Push system telemetry even if no new findings
            self._sync_system_telemetry()
            return

        for finding in new_findings:
            try:
                success = self._sync_finding(finding)
                if success:
                    self.last_synced_id = finding["id"]
                else:
                    # Rate limited or failed. Stop this cycle to retry from this point later.
                    logger.info(f"[{self.name}] Sync paused (Rate Limit/Error) at ID {finding['id']}")
                    break
            except Exception as e:
                logger.error(f"[{self.name}] Sync failed for ID {finding['id']}: {e}")
                break # Stop on error to maintain sequential integrity

        self._save_last_id(self.last_synced_id)
        logger.info(f"[{self.name}] Sync cycle complete. New watermark: {self.last_synced_id}")

    def _sync_finding(self, finding: Dict[str, Any]) -> bool:
        f_type = finding["finding_type"]
        content = finding["content"]
        f_id = f"finding_{finding['id']}"

        if f_type == "pothole_verified":
            return fb_client.upsert_pothole(f_id, {
                **content,
                "created_at": finding["timestamp"],
                "agent": finding["agent_name"]
            })
        elif f_type == "violation_detected":
            return fb_client.log_violation(f_id, {
                **content,
                "timestamp": finding["timestamp"]
            })
        elif f_type in ("synergistic_insight", "colab_sync"):
            # Store generic high-value research insights
            return fb_client.upsert_pothole(f_id, { # Reusing for generic insights for now
                "type": f_type,
                "content": content,
                "timestamp": finding["timestamp"]
            })
        return True # Type not supported for cloud sync, skip and continue

    def _sync_system_telemetry(self):
        """Periodically push hardware stats."""
        thermal_rows = ledger.get_findings(agent_name="Agent7-GPUThermal", limit=1)
        if thermal_rows:
            content = thermal_rows[0]["content"]
            fb_client.push_telemetry("SENTINEL_NODE_MAIN", {
                "gpu_temp": content.get("current_temp"),
                "gpu_util": content.get("gpu_util_pct"),
                "ram_usage": content.get("ram_usage_gb"),
                "last_heartbeat": datetime.now().isoformat()
            })

    async def generate_response(self, question: str) -> str:
        status = "ONLINE" if fb_client.is_connected() else "OFFLINE"
        return (
            f"I am Agent 31 — Firebase Bridge. Cloud sync status: {status}. "
            f"Successfully synchronized up to Ledger ID {self.last_synced_id}. "
            f"Monitoring potholes, violations, and real-time GPU telemetry for the cloud dashboard."
        )
