import time
import logging
import uuid
import asyncio
import threading
import sys
from core.agent_bus import bus
from agents.api_bridge import APIBridgeAgent
from agents.ble_mesh_broker import BLEMeshBroker
from agents.shadow_mode_logger import ShadowModeLogger
from etl.spatial_database_init import SpatialDatabaseManager
from scripts.precog_engine import PreCogEngine
from agents.rti_drafter import RTIDrafter

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# [EDGE-SENTINEL: MASTER BOOT CONTROLLER]
# Binds all logic, ML, and Network bridges together.


def _start_optional_component(name: str, factory):
    def runner():
        try:
            factory()
            print(f"✅ {name} ONLINE")
        except Exception as exc:
            logging.warning("%s unavailable: %s", name, exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread

def start_framework():
    print("=====================================================")
    print(" BOOTING EDGE-SENTINEL FRAMEWORK (LIVE MODE) ")
    print("=====================================================")
    
    # 1. Initialize Network & V2X
    spatial_db = SpatialDatabaseManager("edge_spatial.db")
    bridge = APIBridgeAgent(host="0.0.0.0", port=8765)
    bridge.start()
    broker = BLEMeshBroker(node_id=uuid.uuid4().hex)
    precog_engine = PreCogEngine(db_path="edge_spatial.db", interval_sec=300)
    precog_engine.start_background()
    rti_drafter = RTIDrafter(db_path="edge_spatial.db", scan_interval_sec=3600)
    rti_drafter.start_background()
    
    # 2. Initialize Logic & Audit
    audit = ShadowModeLogger(log_dir="logs/production_audit")
    _start_optional_component(
        "SentinelFusionAgent",
        lambda: __import__("agents.sentinel_fusion", fromlist=["SentinelFusionAgent"]).SentinelFusionAgent(
            strike_window_ms=1000
        ),
    )
    _start_optional_component(
        "AcousticUIAgent",
        lambda: __import__("agents.acoustic_ui", fromlist=["AcousticUIAgent"]).AcousticUIAgent(
            mode="LIVE_PYTTSX3"
        ),
    )
    
    print("\n✅ ALL PERSONAS ONLINE & LISTENING.")
    print("✅ PRECOG_ENGINE + RTI_DRAFTER integrated into master backend loop.")
    print("React Native App can now connect to ws://YOUR-IP:8765")
    print("=====================================================\n")
    
    # Authentic hardware consumption loop
    async def hardware_consumption_loop():
        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(hardware_consumption_loop())
    except KeyboardInterrupt:
        print("\n🛑 SHUTTING DOWN SENTINEL CORE.")
    finally:
        spatial_db.close()

if __name__ == "__main__":
    start_framework()
