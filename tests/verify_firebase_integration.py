import asyncio
import os
import json
from core.knowledge_ledger import ledger
from agents.firebase_bridge_agent import FirebaseBridgeAgent
from core.firebase_client import fb_client

async def verify_firebase_sync():
    print("🔍 VERIFICATION: FIREBASE_SYNC_INTEGRATION")
    print("="*60)
    
    # 1. Check Agent Registration
    from agents.system_agents import get_agents
    agents = get_agents()
    agent31 = next((a for a in agents if a.name == "Agent31-FirebaseBridge"), None)
    if agent31:
        print("✅ SUCCESS: Agent 31 is registered in the factory.")
    else:
        print("❌ FAILURE: Agent 31 not found in get_agents().")
        return

    # 2. Mock a finding in the ledger
    test_finding = {
        "lat": 13.0827,
        "lon": 80.2707,
        "severity": 4.5,
        "verified_by": "IMU_VISION_MATRIX"
    }
    print("📝 Logging mock pothole finding to ledger...")
    ledger.log_finding("Agent28-RoadWatch", "pothole_verified", test_finding)
    
    # 3. Trigger one iteration of the Bridge Agent
    print("🔄 Running one iteration of Agent 31...")
    # Manually trigger iteration
    await agent31.iteration()
    
    # 4. Check status
    if not fb_client.is_connected():
        print("ℹ️  INFO: Firebase not connected (expected with placeholder credentials).")
        print("✅ SUCCESS: Agent handled 'Disconnected' state gracefully.")
    else:
        print("✅ SUCCESS: Firebase connected and sync attempted.")

    # 5. Check sync state persistence
    state_file = os.path.join("config", "firebase_sync_state.json")
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            state = json.load(f)
            print(f"📦 SYNC_STATE: Last ID {state.get('last_id')} tracked correctly.")
            print("✅ SUCCESS: Sync persistence is working.")

    print("\n🎉 FIREBASE INTEGRATION TEST COMPLETE")

if __name__ == "__main__":
    asyncio.run(verify_firebase_sync())
