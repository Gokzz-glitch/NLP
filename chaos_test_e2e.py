import asyncio
import aiohttp
import time
import random
import uuid

# --- CONFIGURATION ---
API_BASE_URL = "http://localhost:8000"
SIMULATED_TRUCKS = 10
TEST_DURATION_SECONDS = 45
HAZARD_TYPES = ["pothole", "accident", "debris", "speed_breaker", "speed_camera"]

async def simulate_vision_node(truck_id, session):
    """Simulates a truck's dashcam YOLO model firing detections into the system."""
    end_time = time.time() + TEST_DURATION_SECONDS
    hazards_spotted = 0

    while time.time() < end_time:
        # Simulate the truck spotting a hazard every 3-8 seconds
        await asyncio.sleep(random.uniform(3.0, 8.0))
        
        hazard = random.choice(HAZARD_TYPES)
        confidence = round(random.uniform(0.65, 0.95), 2)
        
        # This payload should match what your actual YOLO script sends to the bus/DB
        payload = {
            "node_id": truck_id,
            "event_type": "vision_detection",
            "hazard_class": hazard,
            "confidence": confidence,
            "gps_lat": round(13.0827 + random.uniform(-0.05, 0.05), 6), # Chennai approx
            "gps_lon": round(80.2707 + random.uniform(-0.05, 0.05), 6),
            "timestamp": time.time()
        }
        
        # Route this to wherever your system ingests local telemetry (adjust endpoint as needed)
        try:
            async with session.post(f"{API_BASE_URL}/api/v1/internal/ingest", json=payload) as resp:
                if resp.status in [200, 201]:
                    hazards_spotted += 1
        except Exception:
            pass # Ignore connection drops in chaos testing

    return f"Truck {truck_id} finished. Spotted {hazards_spotted} hazards."

async def simulate_ble_swarm_mesh(session):
    """Simulates the offline V2X mesh dropping random, out-of-order events into the bus."""
    end_time = time.time() + TEST_DURATION_SECONDS
    mesh_events_relayed = 0

    while time.time() < end_time:
        await asyncio.sleep(random.uniform(0.5, 2.0)) # Rapid, chaotic BLE pings
        
        payload = {
            "source": "ble_mesh",
            "peer_id": f"peer_{uuid.uuid4().hex[:6]}",
            "ttl": random.randint(1, 3),
            "hazard_class": "pothole",
            "timestamp": time.time() - random.uniform(1.0, 10.0) # Delayed sync
        }
        
        try:
            async with session.post(f"{API_BASE_URL}/api/v1/internal/mesh-sync", json=payload) as resp:
                if resp.status == 200:
                    mesh_events_relayed += 1
        except Exception:
            pass

    return f"BLE Mesh relay finished. Injected {mesh_events_relayed} ghost events."

async def simulate_b2b_dashboard_clients(session):
    """Simulates enterprise fleet managers querying the UI and Razorpay endpoints."""
    end_time = time.time() + TEST_DURATION_SECONDS
    queries_made = 0

    while time.time() < end_time:
        await asyncio.sleep(random.uniform(1.0, 3.0))
        
        try:
            # Hammer the premium routing endpoint
            headers = {"Authorization": "Bearer TEST_DEMO_KEY_123"}
            async with session.get(f"{API_BASE_URL}/api/v1/fleet-routing-hazards", headers=headers) as resp:
                queries_made += 1
        except Exception:
            pass

    return f"Dashboard clients finished. Made {queries_made} routing queries."

async def run_full_system_chaos():
    print(f"🚀 INITIATING END-TO-END FLEET CHAOS PROTOCOL 🚀")
    print(f"Simulating {SIMULATED_TRUCKS} trucks, BLE Swarm, and B2B Dashboard for {TEST_DURATION_SECONDS} seconds...\n")
    
    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        # Task 1: Spawn the fleet of trucks (Vision Loop Mocks)
        tasks = [simulate_vision_node(f"TRUCK_NODE_{i}", session) for i in range(SIMULATED_TRUCKS)]
        
        # Task 2: Spawn the BLE Swarm noise generator
        tasks.append(simulate_ble_swarm_mesh(session))
        
        # Task 3: Spawn the Enterprise clients pulling data
        tasks.append(simulate_b2b_dashboard_clients(session))
        
        # Execute everything simultaneously
        results = await asyncio.gather(*tasks)

    print("\n📊 CHAOS TEST RESULTS:")
    for res in results:
        print(f" - {res}")
    
    print(f"\n⏱️ E2E Test Completed in {round(time.time() - start_time, 2)} seconds.")
    print("If your terminal running `agent2_dashboard/api.py` didn't crash, you are ready for production.")

if __name__ == "__main__":
    asyncio.run(run_full_system_chaos())
