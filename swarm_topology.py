import sqlite3
import json

# [PERSONA 1: THE DECENTRALIZED ARCHITECT]
# SCHEMA_NODE_01: BLE_SWARM_HAZARD_PAYLOAD
# Metadata-dense JSON payload for mesh broadcast.

BLE_HAZARD_PAYLOAD_SCHEMA = {
    "protocol": "SMART_SALAI_V2X_OFFLINE",
    "version": "1.1-GODFATHER",
    "payload": {
        "msg_id": "UUID4_STRING",
        "timestamp": "ISO_8601_EPOCH",
        "origin_node": "DEVICE_MAC_HASH",
        "data": {
            "hazard_class": ["POTHOLE", "SPEED_LIMIT", "ACCIDENT", "LANE_VIOLATION"],
            "severity": [0, 1, 2, 3], # 3 = CRITICAL
            "location": {
                "lat": "FLOAT_64",
                "lon": "FLOAT_64",
                "hmsl": "FLOAT_32" # Height Mean Sea Level
            },
            "sensor_metadata": {
                "imu_z_spike": "FLOAT_G",
                "vision_confidence": "FLOAT_0_1"
            }
        },
        "signature": "ED25519_AUTH_HASH"
    }
}

# SCHEMA_NODE_02: SPATIAL_GROUND_TRUTH_DB
# Persistent local storage for decentralized mapping.

def initialize_spatial_db(db_path='spatial_ground_truth.db'):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Table for swarm-sourced road hazards and legal signage
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ground_truth_markers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT,
            class TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            severity INTEGER DEFAULT 0,
            confidence REAL,
            imu_trigger_magnitude REAL,
            is_verified_locally INTEGER DEFAULT 0,
            raw_metadata_json TEXT
        )
    ''')
    
    # Spatial Indexing (Proxy via simple Lat/Long bounds queries for Edge-efficiency)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_spatial ON ground_truth_markers(lat, lon)')
    
    conn.commit()
    conn.close()
    print("PERSONA_1_REPORT: SPATIAL_DB_INITIALIZED. SWARM_SCHEMAS_LOCKED.")

if __name__ == "__main__":
    initialize_spatial_db()
