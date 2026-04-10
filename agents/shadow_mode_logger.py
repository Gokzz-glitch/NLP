import logging
import json
import os
import time
from typing import Dict, Any
from core.agent_bus import bus

# [PERSONA 5: SHADOW MODE LOGGER — SAFETY AUDIT]
# Task: T-023 — Implement deterministic background audit trail.

logger = logging.getLogger("edge_sentinel.shadow_logger")
logger.setLevel(logging.INFO)

class ShadowModeLogger:
    """
    Deterministic background logger for autonomous safety audit.
    Logs all AgentBus traffic to a rolling JSONL file.
    Designed for ISO 14971 accountability — 'The Black Box'.
    """
    def __init__(self, log_dir: str = "logs/shadow_mode"):
        self.log_dir = log_dir
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        self.log_file = f"{self.log_dir}/audit_{int(time.time())}.jsonl"
        self._setup_bus()
        logger.info(f"PERSONA_5_REPORT: SHADOW_LOGGER_ONLINE | file={self.log_file}")

    def _setup_bus(self):
        """
        Subscribe to EVERYTHING (Wildcard emulation).
        Since the AgentBus doesn't support wildcards, we manually list critical channels.
        """
        channels = [
            "VISION_HAZARD_DETECTED",
            "NEAR_MISS_DETECTED",
            "SENTINEL_FUSION_ALERT",
            "REGULATORY_CONFLICT",
            "PHYSICAL_BLE_ADVERTISEMENT",
            "TTS_SYNTHESIS_REQUEST"
        ]
        for ch in channels:
            bus.subscribe(ch, lambda pl, channel=ch: self._log_event(channel, pl))

    def _log_event(self, channel: str, payload: Any):
        """
        Appends event to the JSONL audit trail.
        Uses append mode + flush for real-time safety.
        """
        entry = {
            "ts_ms": int(time.time() * 1000),
            "channel": channel,
            "payload": payload
        }
        
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
        except Exception as e:
            logger.error(f"AUDIT_LOG_ERROR: {e}")

if __name__ == "__main__":
    # Test
    logger_agent = ShadowModeLogger()
    bus.emit("SENTINEL_FUSION_ALERT", {"source": "test", "val": 1.0})
    print(f"AUDIT_CHECK: Logged event to {logger_agent.log_file}")
