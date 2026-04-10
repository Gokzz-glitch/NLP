import logging
import uuid
import time
from typing import Dict, List, Optional
from core.agent_bus import bus
from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity

# [PERSONA 3: KINETIC ENGINEER — FUSION LOGIC]
# Task: Implement agents/sentinel_fusion.py (T-012, T-014, T-015).

logger = logging.getLogger("edge_sentinel.sentinel_fusion")
logger.setLevel(logging.INFO)

class SentinelFusionAgent:
    """
    Fuses decentralized vision-based hazards with high-frequency IMU kinetic triggers.
    Logic:
      - CONFIRMED_STRIKE: Vision Pothole + IMU Z-axis spike within 500ms.
      - REGULATORY_CONFLICT: Vision sign mismatch with trajectory (T-014).
    """
    def __init__(self, strike_window_ms: int = 500):
        self.strike_window_ms = strike_window_ms
        self.last_vision_hazards: List[Dict] = []
        self._setup_bus()
        logger.info(f"PERSONA_3_REPORT: FUSION_AGENT_ONLINE | window={self.strike_window_ms}ms")

    def _setup_bus(self):
        """Subscribe to specific agent streams."""
        bus.subscribe("VISION_HAZARD_DETECTED", self._on_vision_hazard)
        bus.subscribe("NEAR_MISS_DETECTED", self._on_near_miss)

    def _on_vision_hazard(self, hazards: Dict):
        """
        Receives raw detections from VisionAuditEngine.
        Store for correlation with future IMU events.
        """
        now = int(time.time() * 1000)
        origin_ts = hazards.get("origin_timestamp_ms", now)
        self.last_vision_hazards = [
            {
                "type": h["type"],
                "ts": now,
                "conf": h["confidence"],
                "origin_timestamp_ms": h.get("origin_timestamp_ms", origin_ts),
            }
            for h in hazards.get("potholes", [])
        ]
        
        # Immediate Regulatory Check (T-014)
        for sign in hazards.get("traffic", []):
            if sign["class_id"] == 1: # Assuming index 1 is 'SPEED_LIMIT'
                self._check_regulatory_conflict(sign)

    def _on_near_miss(self, event: NearMissEvent):
        """
        Receives NearMissEvent from IMU detector.
        Check for correlation with recent Vision hazards.
        """
        now = event.timestamp_epoch_ms
        
        # Fusion T-015: Confirmed Pothole Strike
        recent_potholes = [
            p for p in self.last_vision_hazards 
            if (now - p["ts"]) < self.strike_window_ms
        ]
        
        if recent_potholes and event.rms_jerk_ms3 > 10.0: # Arbitrary spike threshold for strike
            self._emit_confirmed_strike(event, recent_potholes[0])
        elif event.severity == NearMissSeverity.CRITICAL:
            logger.warning(f"SENTINEL_ALERT: UNEXPLAINED_NEAR_MISS | severity={event.severity.value}")

    def _check_regulatory_conflict(self, sign_event: Dict):
        # Placeholder for complex regulatory logic (P2 bridge)
        # If speed limit detected but trajectory is too fast
        pass

    def _emit_confirmed_strike(self, imu_event, vision_pothole):
        now_ms = int(time.time() * 1000)
        origin_ts = vision_pothole.get("origin_timestamp_ms", imu_event.timestamp_epoch_ms)
        fast_event = {
            "type": "POTHOLE_AHEAD",
            "severity": "CRITICAL",
            "source": "SENTINEL_FUSION_FASTLANE",
            "fusion_hint": "VISION_IMU_CONSENSUS",
            "_event_ts_ms": now_ms,
            "origin_timestamp_ms": origin_ts,
        }
        bus.emit("FAST_CRITICAL_ALERT", fast_event)

        confirmed_event = {
            "fusion_id": str(uuid.uuid4()),
            "type": "CONFIRMED_POTHOLE_STRIKE",
            "imu_event_id": imu_event.event_id,
            "severity": "CRITICAL",
            "v2x_broadcast_required": True,
            "timestamp_epoch_ms": imu_event.timestamp_epoch_ms,
            "_event_ts_ms": now_ms,
            "origin_timestamp_ms": origin_ts,
        }
        logger.warning(f"SENTINEL_FUSION_ALERT: {confirmed_event['type']} | IMU/Vision consensus reached.")
        bus.emit("SENTINEL_FUSION_ALERT", confirmed_event)

if __name__ == "__main__":
    # Production code should not emit synthetic events.
    # Use tests/test_sentinel_fusion.py for integration testing.
    print("ℹ️  Sentinel Fusion Agent test code moved to tests/ directory.")
    print("   Run: pytest tests/test_sentinel_fusion.py")
