from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

import time
import logging
from core.agent_bus import bus
from agents.sentinel_fusion import SentinelFusionAgent
from agents.imu_near_miss_detector import IMUSample, NearMissDetector, GRAVITY_MS2

# [PERSONA 3: INTEGRATION TEST]
# Task: Verify Vision-IMU Fusion (T-016).

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def test_p3_integration():
    print("\n--- STARTING PERSONA 3 INTEGRATION TEST ---")
    
    # 1. Initialize Fusion Agent
    fusion = SentinelFusionAgent(strike_window_ms=1000)
    
    # 2. Simulate Vision identifying a Pothole (at t=0)
    print("\n[STEP 1] VISION_ENGINE: 'Pothole detected with 85% confidence.'")
    bus.emit("VISION_HAZARD_DETECTED", {
        "potholes": [{"type": "POTHOLE", "confidence": 0.85, "box": [100, 100, 200, 200]}]
    })
    
    # 3. Simulate IMU spike 200ms later (Confirmed Strike)
    time.sleep(0.2)
    print("\n[STEP 2] IMU_SENSOR: 'Z-axis kinetic spike detected (15.5 m/s³ jerk).'")
    
    detector = NearMissDetector(onnx_model_path=None) # Deterministic mode
    detector.load()
    
    # Force a Near-Miss Event manually for the test
    # (Since push_sample requires 120 samples to trigger)
    from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity
    mock_event = NearMissEvent(
        event_id="test-fusion-id",
        timestamp_epoch_ms=int(time.time() * 1000),
        severity=NearMissSeverity.CRITICAL,
        rms_jerk_ms3=15.5 # Serious strike
    )
    
    print("\n[STEP 3] FUSION_AGENT: Correlating events...")
    bus.emit("NEAR_MISS_DETECTED", mock_event)
    
    print("\n--- TEST COMPLETE ---")

if __name__ == "__main__":
    test_p3_integration()
