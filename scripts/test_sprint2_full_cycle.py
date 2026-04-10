from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

import time
import logging
import json
from core.agent_bus import bus
from core.irad_serializer import IRADSerializer
from agents.acoustic_ui import AcousticUIAgent
from agents.ble_mesh_broker import BLEMeshBroker
from agents.shadow_mode_logger import ShadowModeLogger

# [SPRINT 2: FULL CYCLE VERIFICATION]
# Task: T-025 — End-to-end verification (Detection → iRAD → Voice → BLE → Audit).

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def test_sprint2_full_cycle():
    print("\n--- STARTING SPRINT 2 FULL CYCLE VERIFICATION ---")
    
    # 1. Initialize Persona 1, 4, 5
    print("\n[STEP 0] INITIALIZING PERSONAS...")
    ui = AcousticUIAgent()
    broker = BLEMeshBroker(node_id="S2-TEST-NODE")
    audit = ShadowModeLogger(log_dir="logs/sprint2_test")
    
    # 2. Simulate a Persona 3 'SENTINEL_FUSION_ALERT'
    # This is the trigger that kicks off the integration chain.
    fusion_alert = {
        "fusion_id": "test-s2-f8b",
        "type": "CONFIRMED_POTHOLE_STRIKE",
        "severity": "CRITICAL",
        "lat": 12.98,
        "lon": 80.24,
        "rms_jerk": 18.2,
        "confidence": 92
    }
    
    print("\n[STEP 1] EMITTING FUSION_ALERT (Persona 3)...")
    bus.emit("SENTINEL_FUSION_ALERT", fusion_alert)
    
    # 3. Serialize to iRAD (Core)
    print("\n[STEP 2] SERIALIZING TO iRAD (Core)...")
    serializer = IRADSerializer()
    irad_payload = serializer.serialize_fusion_alert(fusion_alert)
    print(f"INFO: iRAD Schema Valid: {irad_payload['telemetry']['type']}")
    
    # Wait for async-simulate callbacks
    time.sleep(1)
    
    print("\n[STEP 3] CHECKING AUDIT TRAIL...")
    with open(audit.log_file, "r") as f:
        events = [json.loads(line) for line in f]
    
    logged_channels = [e["channel"] for e in events]
    print(f"INFO: Channels captured: {logged_channels}")
    
    # Verify critical links
    assert "SENTINEL_FUSION_ALERT" in logged_channels
    assert "TTS_SYNTHESIS_REQUEST" in logged_channels # P4 worked
    assert "PHYSICAL_BLE_ADVERTISEMENT" in logged_channels # P1 worked
    
    print("\n--- SPRINT 2 VERIFICATION SUCCESS ---")

if __name__ == "__main__":
    test_sprint2_full_cycle()
