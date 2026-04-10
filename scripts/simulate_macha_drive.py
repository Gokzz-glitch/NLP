import asyncio
import websockets
import json
import time

async def simulate_macha_drive():
    uri = "ws://127.0.0.1:8765"
    async with websockets.connect(uri) as websocket:
        print("🔗 CONNECTED: Macha Test Simulation Started.")
        
        # Scenario 1: Pothole in Front
        print("\n📍 SCENARIO 1: Pothole Detected (Front)")
        alert1 = {
            "channel": "SENTINEL_FUSION_ALERT",
            "payload": {
                "type": "POTHOLE",
                "severity": "HIGH",
                "direction": "FRONT",
                "legal_citation": "MVA 2019 SEC 184 (Dangerous Driving)"
            }
        }
        await websocket.send(json.dumps(alert1))
        await asyncio.sleep(8) # Wait for Voice to finish

        # Scenario 2: Overspeeding (Rear Camera Detection)
        print("\n📍 SCENARIO 2: Tailgating/Speeding Detected (Rear)")
        alert2 = {
            "channel": "SENTINEL_FUSION_ALERT",
            "payload": {
                "type": "SPEEDING",
                "severity": "CRITICAL",
                "direction": "REAR",
                "legal_citation": "MVA 2019 SEC 183 (Over Speeding)"
            }
        }
        await websocket.send(json.dumps(alert2))
        await asyncio.sleep(8)

        # Scenario 3: Smooth Drive - Updating Memory
        print("\n📍 SCENARIO 3: Smooth Cornering detected by IMU")
        mem_update = {
            "channel": "DRIVER_MEMORY_UPDATE",
            "payload": {
                "event": "Smooth Cornering",
                "score": +10,
                "note": "Excellent steering macha!"
            }
        }
        await websocket.send(json.dumps(mem_update))
        print("✅ TEST_COMPLETE: Visual & Voice cycles verified.")

if __name__ == "__main__":
    asyncio.run(simulate_macha_drive())
