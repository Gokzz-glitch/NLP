import time
import random
import logging
from core.agent_bus import bus
from agents.api_bridge import APIBridgeAgent
from agents.acoustic_ui import AcousticUIAgent

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def run_simulation():
    """Generate 100 synthetic hazard events for testing UI and voice responses."""
    print("=====================================================")
    print(" 🌪️ INITIATING 100-SITUATION STRESS TEST ")
    print("=====================================================")
    print("Open your React Native App (Expo Go) to see the live UI updates!")
    
    # Init UI and Networking
    bridge = APIBridgeAgent(host="0.0.0.0", port=8765)
    bridge.start()
    
    ui = AcousticUIAgent(mode="LIVE_PYTTSX3")
    
    print("\n⏳ Starting in 10 seconds to give you time to open the app...\n")
    time.sleep(10)

    hazard_types = ["POTHOLE", "SPEED_LIMIT", "ACCIDENT_PRONE", "LANE_VIOLATION"]
    severities = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    for i in range(1, 101):
        hazard = random.choice(hazard_types)
        severity = random.choice(severities)
        
        # Bias towards CRITICAL so it triggers the TTS Voice more often
        if random.random() > 0.6:
            severity = "CRITICAL"

        print(f"\n--- [SITUATION {i}/100] ---")
        confidence = round(random.uniform(70.0, 99.9), 1)
        
        if hazard == "POTHOLE" and severity == "CRITICAL":
            # Simulate a Fusion Event (Vision + Hard IMU Spike)
            payload = {
                "type": "CONFIRMED_POTHOLE_STRIKE",
                "severity": severity,
                "confidence": confidence,
                "lat": round(13.0 + random.uniform(-0.1, 0.1), 4),
                "lon": round(80.2 + random.uniform(-0.1, 0.1), 4),
                "rms_jerk": round(random.uniform(12.0, 25.0), 1)  # Hard jerk
            }
        else:
            # Generic Vision Hazard
            payload = {
                "type": hazard,
                "severity": severity,
                "confidence": confidence
            }
            
        # Push to the bus -> Websocket pushes to React Native, UI flashes
        # AcousticUI catches it -> Laptop speaks the Tanglish phrase
        bus.emit("SENTINEL_FUSION_ALERT", payload)

        # Wait so the app and voice engine have time to play the sound
        # NOTE: This delay is ARTIFICIAL and FOR TESTING ONLY
        time.sleep(random.uniform(3.0, 5.0))

    print("\n✅ 100-SITUATION SIMULATION COMPLETE.")

# ⚠️ WARNING: This script is for TESTING/DEMO ONLY, not for production.
# It generates synthetic hazard events with artificial delays.
# Do NOT run in production with real vehicle data.
#
# Usage: python scripts/simulate_100_situations.py
#        (Only in isolated test environments)

if __name__ == "__main__":
    print("\n⚠️  SIMULATION MODE: Generating 100 synthetic hazard events...")
    print("    This script is for TESTING ONLY. Do not use with real vehicle data.\n")
    run_simulation()
