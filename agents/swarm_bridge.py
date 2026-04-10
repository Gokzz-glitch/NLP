import sqlite3
import json
import time
from datetime import datetime
from threading import Lock
from typing import Optional

# [PERSONA 1: THE DECENTRALIZED ARCHITECT]
# Task: Bridge Swarm broadcast logic to internal Spatial_ground_truth.db write operation.
# [FIX #3: Lock-safe DB writes with WAL, timeout, connection reuse]

DB_PATH = 'spatial_ground_truth.db'
_db_conn: Optional[sqlite3.Connection] = None
_db_lock = Lock()

def _get_connection() -> sqlite3.Connection:
    """Get or create reusable DB connection with WAL and timeout [FIX #3]"""
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DB_PATH, timeout=5.0, check_same_thread=False)
        _db_conn.execute("PRAGMA journal_mode=WAL")        # Write-ahead logging
        _db_conn.execute("PRAGMA busy_timeout=2000")      # 2s timeout on lock waits
        _db_conn.execute("PRAGMA synchronous=NORMAL")     # Balance safety/speed
        _db_conn.execute("PRAGMA cache_size=5000")        # 5MB page cache
    return _db_conn

def process_swarm_payload(payload_json: str, max_retries: int = 3) -> bool:
    """
    Parses a BLE Swarm Hazard Payload and commits it to the local Spatial DB.
    [FIX #3: Thread-safe with retry backoff, WAL, and connection reuse]
    """
    try:
        data = json.loads(payload_json)
        
        # Extract fields based on BLE_HAZARD_PAYLOAD_SCHEMA
        msg_id = data.get("payload", {}).get("msg_id", "UNKNOWN")
        timestamp = data.get("payload", {}).get("timestamp", datetime.now().isoformat())
        node_id = data.get("payload", {}).get("origin_node", "UNKNOWN_NODE")
        
        hazard_data = data.get("payload", {}).get("data", {})
        hazard_class = hazard_data.get("hazard_class", "GENERAL")
        severity = hazard_data.get("severity", 0)
        
        location = hazard_data.get("location", {})
        lat = location.get("lat", 0.0)
        lon = location.get("lon", 0.0)
        
        metadata = hazard_data.get("sensor_metadata", {})
        imu_trigger = metadata.get("imu_z_spike", 0.0)
        vision_confidence = metadata.get("vision_confidence", 0.0)
        
        # Connect and Insert (with retry backoff)
        for attempt in range(max_retries):
            try:
                with _db_lock:
                    conn = _get_connection()
                    cursor = conn.cursor()
                    
                    cursor.execute('''
                        INSERT INTO ground_truth_markers 
                        (node_id, class, lat, lon, severity, confidence, imu_trigger_magnitude, raw_metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (node_id, hazard_class, lat, lon, severity, vision_confidence, imu_trigger, payload_json))
                    
                    conn.commit()
                    print(f"PERSONA_1_REPORT: COMMITTED_SWARM_HAZARD: {hazard_class} at ({lat}, {lon})")
                    return True
            except sqlite3.OperationalError as e:
                if attempt < max_retries - 1:
                    backoff_sec = 0.1 * (2 ** attempt)  # Exponential backoff: 0.1, 0.2, 0.4s
                    print(f"SWARM_BRIDGE_RETRY: {e} (attempt {attempt+1}/{max_retries}, backoff {backoff_sec}s)")
                    time.sleep(backoff_sec)
                else:
                    raise
    except Exception as e:
        print(f"ERR_PERSONA_1: [Swarm Bridge Failure: {str(e)}]")
        return False
    
    return False

if __name__ == "__main__":
    # Test Payload Simulation
    sample_payload = {
        "protocol": "SMART_SALAI_V2X_OFFLINE",
        "version": "1.1-GODFATHER",
        "payload": {
            "msg_id": "test-uuid-123",
            "timestamp": "2026-03-31T15:32:45Z",
            "origin_node": "MAC_HASH_ABC",
            "data": {
                "hazard_class": "POTHOLE",
                "severity": 2,
                "location": {
                    "lat": 13.0827,
                    "lon": 80.2707,
                    "hmsl": 5.0
                },
                "sensor_metadata": {
                    "imu_z_spike": 1.2,
                    "vision_confidence": 0.85
                }
            },
            "signature": "simulated_sig"
        }
    }
    process_swarm_payload(json.dumps(sample_payload))
