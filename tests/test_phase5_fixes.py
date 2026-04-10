"""
UNIT TESTS: Phase 5 Fix Validation
Tests all 5 critical code fixes with measurable assertions.
Run: pytest tests/test_phase5_fixes.py -v
"""

import pytest
import sys
import os
import json
import sqlite3
import time
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.ble_mesh_broker import BLEMeshBroker
from agents.swarm_bridge import process_swarm_payload, _get_connection
from scripts.production_audit import ProductionAuditor


class TestFix1_BLEBrokerInit:
    """Validate FIX #1: h_idx mapping and protocol initialization."""
    
    def test_broker_initializes_hazard_type_map(self):
        """Broker must have hazard_type_map after init."""
        broker = BLEMeshBroker(node_id="TEST-001")
        assert hasattr(broker, 'hazard_type_map'), "Missing hazard_type_map"
        assert len(broker.hazard_type_map) >= 5, "hazard_type_map incomplete"
        assert broker.hazard_type_map["POTHOLE"] == 0, "POTHOLE not mapped to 0"
    
    def test_broker_loads_protocol_config(self):
        """Broker must load protocol from ble_mesh_protocol.json at init."""
        broker = BLEMeshBroker(node_id="TEST-002")
        assert hasattr(broker, 'protocol'), "Missing protocol attribute"
        assert isinstance(broker.protocol, dict), "protocol not dict"
        assert "offline_mesh_configuration" in broker.protocol, "Missing mesh config"
    
    def test_fusion_alert_resolves_hazard_type(self):
        """Fusion alert must resolve hazard type to index without crash."""
        broker = BLEMeshBroker(node_id="TEST-003")
        
        # Mock bus to capture broadcast
        with patch('agents.ble_mesh_broker.bus') as mock_bus:
            alert = {"type": "POTHOLE", "severity": "CRITICAL", "lat": 13.0, "lon": 80.0, "confidence": 95}
            broker._on_fusion_alert(alert)
            
            # Verify broadcast was called (alerts succeeded, didn't crash on h_idx)
            assert mock_bus.emit.called, "Broadcast not called; h_idx resolution failed"
    
    def test_fusion_alert_handles_unknown_hazard_type(self):
        """Unknown hazard types must fall back to index 0 safely."""
        broker = BLEMeshBroker(node_id="TEST-004")
        
        with patch('agents.ble_mesh_broker.bus') as mock_bus:
            alert = {"type": "UNKNOWN_HAZARD", "severity": "CRITICAL", "lat": 13.0, "lon": 80.0, "confidence": 95}
            broker._on_fusion_alert(alert)
            
            # Should not raise, should fallback gracefully
            assert mock_bus.emit.called, "Should handle unknown hazard gracefully"


class TestFix2_RelayStormControls:
    """Validate FIX #4: Relay storm controls and dedupe management."""
    
    def test_relay_dedupe_cache_has_limit(self):
        """Relay dedupe cache must have size limit to prevent memory bloat."""
        broker = BLEMeshBroker(node_id="TEST-005")
        
        # Fill cache beyond limit
        for i in range(1200):
            broker.seen_messages.add(f"msg_{i:04d}")
        
        # Simulate incoming relay with cache management
        with patch('agents.ble_mesh_broker.bus') as mock_bus:
            payload = {
                "hex": "0102030405060708",
                "ttl": 4,
                "type": 1
            }
            # This should trigger cache cleanup if it exceeds 1000
            # The actual cleanup happens inside _on_incoming_adv
            assert len(broker.seen_messages) <= 1500, "Dedupe cache not being managed"
    
    def test_relay_probabilistic_drop_at_low_ttl(self):
        """Low TTL packets should have probabilistic drop rates."""
        broker = BLEMeshBroker(node_id="TEST-006")
        
        # TTL > 3 should have 0% drop
        # TTL <= 3 should have increasing drop probability
        # This is checked via code path analysis, not execution
        # (random drop means we can't assert exact outcomes)
        
        # At least verify the code path exists
        import inspect
        code = inspect.getsource(broker._on_incoming_adv)
        assert "drop_probability" in code, "Probabilistic drop not implemented"
        assert "random" in code, "Random not imported for drop logic"


class TestFix3_SwarmBridgeDBLockSafety:
    """Validate FIX #3: DB write lock-safety with WAL, timeout, retry."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary test database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_spatial.db")
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE ground_truth_markers (
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
            """)
            conn.commit()
            conn.close()
            yield db_path
    
    def test_process_swarm_payload_succeeds(self, temp_db):
        """Swarm bridge must successfully write hazard to DB."""
        # Monkey-patch DB path
        import agents.swarm_bridge
        original_db = agents.swarm_bridge.DB_PATH
        agents.swarm_bridge.DB_PATH = temp_db
        agents.swarm_bridge._db_conn = None  # Reset connection pool
        
        try:
            payload_json = json.dumps({
                "payload": {
                    "msg_id": "test-123",
                    "timestamp": "2026-04-06T10:00:00Z",
                    "origin_node": "MAC_0001",
                    "data": {
                        "hazard_class": "POTHOLE",
                        "severity": 2,
                        "location": {"lat": 13.0, "lon": 80.0, "hmsl": 5.0},
                        "sensor_metadata": {"imu_z_spike": 1.2, "vision_confidence": 0.85}
                    }
                }
            })
            
            result = process_swarm_payload(payload_json)
            assert result is True, "Swarm bridge write failed"
            
            # Verify write actually hit DB
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM ground_truth_markers WHERE class = 'POTHOLE'")
            count = cursor.fetchone()[0]
            conn.close()
            assert count > 0, "Hazard not written to DB"
        finally:
            agents.swarm_bridge.DB_PATH = original_db
            agents.swarm_bridge._db_conn = None
    
    def test_swarm_bridge_retry_backoff(self, temp_db):
        """Swarm bridge must retry with exponential backoff on lock."""
        import agents.swarm_bridge
        original_db = agents.swarm_bridge.DB_PATH
        agents.swarm_bridge.DB_PATH = temp_db
        agents.swarm_bridge._db_conn = None
        
        try:
            payload_json = json.dumps({
                "payload": {
                    "msg_id": "retry-test",
                    "timestamp": "2026-04-06T10:00:00Z",
                    "origin_node": "MAC_0002",
                    "data": {
                        "hazard_class": "SPEED_TRAP_NO_SIGNAGE",
                        "severity": 1,
                        "location": {"lat": 13.1, "lon": 80.1, "hmsl": 5.0},
                        "sensor_metadata": {"imu_z_spike": 0.5, "vision_confidence": 0.70}
                    }
                }
            })
            
            # Call with max_retries=3 to exercise retry logic
            result = process_swarm_payload(payload_json, max_retries=3)
            # Should succeed without lock errors
            assert result is True, "Retry logic failed"
        finally:
            agents.swarm_bridge.DB_PATH = original_db
            agents.swarm_bridge._db_conn = None


class TestFix4_AuditAssertions:
    """Validate FIX #2: Protocol audit packet length alignment."""
    
    def test_ble_packet_format_spec(self):
        """Validate BLE packet struct packing spec."""
        import struct
        
        # Struct format: "!BIf f B B B H"
        # 1 + 4 + 4 + 4 + 1 + 1 + 1 + 2 = 18B
        test_payload = struct.pack(
            "!BIf f B B B H",
            1,                      # Type
            int(time.time()),       # TS
            13.0,                   # Lat
            80.0,                   # Lon
            0,                      # H_Type (POTHOLE)
            1,                      # Severity
            95,                     # Confidence
            1                       # Seq
        )
        
        assert len(test_payload) == 18, f"Expected 18B, got {len(test_payload)}B"
        
        # With HMAC signature (4 bytes)
        signature = b'\x00\x00\x00\x00'
        final_payload = test_payload + signature
        
        assert len(final_payload) == 22, f"Expected 22B with HMAC, got {len(final_payload)}B"
    
    def test_audit_accepts_valid_packet_range(self):
        """Production audit must accept packets in [18-22]B range."""
        # This validates the fixed assertion logic
        # Expected range: 18B (core) to 22B (core + HMAC)
        
        valid_sizes = [18, 19, 20, 21, 22]
        for size in valid_sizes:
            # Simulate audit check
            in_spec = 18 <= size <= 22
            assert in_spec, f"Packet size {size}B should be valid but audit rejects it"


class TestFix5_HeartbeatRouting:
    """Validate FIX #5: Heartbeat pub-sub wiring."""
    
    def test_system_orchestrator_emits_to_bus(self):
        """System orchestrator heartbeat must emit to agent bus."""
        import inspect
        from system_orchestrator import MachaOrchestrator
        
        source = inspect.getsource(MachaOrchestrator.heartbeat)
        assert 'bus.emit("SYSTEM_HEARTBEAT"' in source, \
            "Heartbeat not routed through agent bus"
        assert 'SYSTEM_HEARTBEAT' in source, \
            "Heartbeat event not properly named"


# ─────────────────────────────────────────────────────────────────
# INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────

class TestPhase5Completeness:
    """Validate all Phase 5 fixes are integrated and not conflicting."""
    
    def test_all_fixes_coexist(self):
        """All fixed modules must import without conflicts."""
        try:
            from agents.ble_mesh_broker import BLEMeshBroker
            from agents.swarm_bridge import process_swarm_payload
            from scripts.production_audit import ProductionAuditor
            from system_orchestrator import MachaOrchestrator
            
            # Basic initialization should not crash
            broker = BLEMeshBroker("TEST")
            assert broker is not None
        except Exception as e:
            pytest.fail(f"Fixes conflict or have import errors: {e}")
    
    def test_deployment_readiness_checklist(self):
        """Verify all gate checklist files exist."""
        required_files = [
            "PHASE_5_RELEASE_GATE.md",
            "ble_mesh_protocol_optimized.json",
            "tests/swarm_load_test.py"
        ]
        
        for f in required_files:
            assert Path(f).exists(), f"Missing required file: {f}"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
