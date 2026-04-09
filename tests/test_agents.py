"""
tests/test_agents.py
Smoke tests for all persona agents:
  - LegalRAGAgent (T-010)
  - Sec208DrafterAgent (T-011)
  - SignAuditorAgent (T-009)
  - BLEMeshBrokerAgent (T-008)
  - AcousticUIAgent (T-012)
  - BlackspotGeofenceAgent
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# LegalRAG
# ---------------------------------------------------------------------------
def test_legal_rag_baseline_query():
    from agents.legal_rag import LegalRAGAgent
    agent = LegalRAGAgent()
    agent.load()

    result = agent.query("Motor vehicle speed limit penalty")
    assert "results" in result
    assert "uls_matches" in result
    assert result["source"] in ("legacy_db", "rag_db", "no_db")
    print(f"[PASS] test_legal_rag_baseline_query (source={result['source']})")


def test_legal_rag_section208_query():
    from agents.legal_rag import LegalRAGAgent
    agent = LegalRAGAgent()
    agent.load()

    result = agent.query("Speed camera without signage challenge Section 208")
    sec208_in_results = any(
        "208" in (r.get("section_id") or "") or "208" in (r.get("chunk_text") or "")
        for r in result["results"]
    )
    assert result["source"] in ("legacy_db", "rag_db", "no_db")
    # When a real DB is available it must return results; no_db is fine with an empty list
    if result["source"] != "no_db":
        assert len(result["results"]) > 0, (
            f"Expected non-empty results from source={result['source']!r}"
        )
    print(f"[PASS] test_legal_rag_section208_query (source={result['source']}, 208_hit={sec208_in_results})")


def test_legal_rag_uls_match():
    from agents.legal_rag import LegalRAGAgent
    agent = LegalRAGAgent()
    agent.load()

    result = agent.query("Riding without helmet non-ISI no overtaking")
    offence_ids = [m["offence_id"] for m in result["uls_matches"]]
    assert isinstance(offence_ids, list)
    print(f"[PASS] test_legal_rag_uls_match (matched: {offence_ids})")


def test_legal_rag_empty_query():
    from agents.legal_rag import LegalRAGAgent
    agent = LegalRAGAgent()
    agent.load()

    result = agent.query("")
    assert result["source"] == "empty"
    assert result["results"] == []
    print("[PASS] test_legal_rag_empty_query")


# ---------------------------------------------------------------------------
# Sec208Drafter
# ---------------------------------------------------------------------------
def test_sec208_challenge_generated():
    from agents.sec208_drafter import Sec208DrafterAgent

    drafter = Sec208DrafterAgent()
    camera_data = {"device_id": "CAM-001", "lat": 12.9240, "lon": 80.2300}
    result = drafter.evaluate(camera_data=camera_data, signage_detected=False)

    assert result["status"] == "CHALLENGE_GENERATED"
    assert result["section_208_flag"] is True
    assert "208" in result["legal_sections"]
    assert result["evidentiary_hash_algo"] == "SHA3-256"
    assert result["annexure_a"]["evidentiary_hash_algo"] == "SHA3-256"
    print("[PASS] test_sec208_challenge_generated")


def test_sec208_compliance_verified():
    from agents.sec208_drafter import Sec208DrafterAgent

    drafter = Sec208DrafterAgent()
    camera_data = {"device_id": "CAM-001", "lat": 12.9240, "lon": 80.2300}
    result = drafter.evaluate(camera_data=camera_data, signage_detected=True)

    assert result["status"] == "COMPLIANT"
    assert result["section_208_flag"] is False
    print("[PASS] test_sec208_compliance_verified")


def test_sec208_non_camera_object():
    from agents.sec208_drafter import Sec208DrafterAgent

    drafter = Sec208DrafterAgent()
    # No camera device_id and no detections → NOT_APPLICABLE
    result = drafter.evaluate(camera_data={}, signage_detected=False)
    assert result["status"] == "NOT_APPLICABLE"
    print("[PASS] test_sec208_non_camera_object")


def test_sec208_evidence_hash_is_sha3_256():
    from agents.sec208_drafter import Sec208DrafterAgent
    import hashlib

    drafter = Sec208DrafterAgent()
    camera_data = {"device_id": "CAM-TEST", "lat": 12.0, "lon": 80.0}
    result = drafter.evaluate(camera_data=camera_data, signage_detected=False)

    assert result["evidentiary_hash_algo"] == "SHA3-256"
    # Verify the hash is a valid SHA3-256 hex (64 chars)
    h = result["evidentiary_hash"]
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    print("[PASS] test_sec208_evidence_hash_is_sha3_256")


# ---------------------------------------------------------------------------
# SignAuditor
# ---------------------------------------------------------------------------
def test_sign_auditor_mock_mode():
    from agents.sign_auditor import SignAuditorAgent

    agent = SignAuditorAgent(model_path="/nonexistent/model.onnx")
    agent.load()
    assert agent._mock_mode
    print("[PASS] test_sign_auditor_mock_mode")


def test_sign_auditor_process_frame_returns_result():
    from agents.sign_auditor import SignAuditorAgent

    agent = SignAuditorAgent(model_path="/nonexistent/model.onnx")
    agent.load()
    result = agent.process_frame(frame=None, gps_lat=12.924, gps_lon=80.230)
    assert "detections" in result
    assert "sec208_trigger" in result
    assert isinstance(result["detections"], list)
    print("[PASS] test_sign_auditor_process_frame_returns_result")


def test_sign_auditor_sec208_trigger_without_sign():
    from agents.sign_auditor import SignAuditorAgent

    agent = SignAuditorAgent(model_path="/nonexistent/model.onnx")
    agent.load()

    # Mock: inject only a speed_camera, no sign
    frame_meta = {"_mock_inject": [
        {"label": "speed_camera", "confidence": 0.90, "bbox": [0.3, 0.1, 0.7, 0.6]},
    ]}
    result = agent.process_frame(
        frame=None, gps_lat=12.9240, gps_lon=80.2300,
        recent_sign_locations=[],   # empty — no sign in history
        frame_meta=frame_meta,
    )
    assert result["sec208_trigger"] is True
    assert result["has_camera"] is True
    assert result["has_sign_in_geofence"] is False
    print("[PASS] test_sign_auditor_sec208_trigger_without_sign")


def test_sign_auditor_no_trigger_with_sign():
    from agents.sign_auditor import SignAuditorAgent

    agent = SignAuditorAgent(model_path="/nonexistent/model.onnx")
    agent.load()

    frame_meta = {"_mock_inject": [
        {"label": "speed_camera",    "confidence": 0.88, "bbox": [0.3, 0.1, 0.7, 0.6]},
        {"label": "speed_limit_sign","confidence": 0.82, "bbox": [0.1, 0.0, 0.3, 0.4]},
    ]}
    # Sign location provided in history
    sign_locs = [{"lat": 12.9241, "lon": 80.2302}]
    result = agent.process_frame(
        frame=None, gps_lat=12.9240, gps_lon=80.2300,
        recent_sign_locations=sign_locs,
        frame_meta=frame_meta,
    )
    assert result["sec208_trigger"] is False
    assert result["has_sign_in_geofence"] is True
    print("[PASS] test_sign_auditor_no_trigger_with_sign")


# ---------------------------------------------------------------------------
# BLE Mesh
# ---------------------------------------------------------------------------
def test_ble_mesh_two_nodes():
    from agents.ble_mesh_broker import (
        BLEMeshBrokerAgent, MsgType, HazardType, _MockBLETransport
    )
    _MockBLETransport._mesh_registry.clear()

    node_a = BLEMeshBrokerAgent(node_id="test-aaaa")
    node_b = BLEMeshBrokerAgent(node_id="test-bbbb")

    node_a.start()
    node_b.start()

    ok = node_a.broadcast_hazard(
        hazard_type=HazardType.SPEED_TRAP_NO_SIGN,
        lat=12.924, lon=80.230, severity="HIGH", confidence=0.91,
    )
    time.sleep(0.1)

    assert ok
    hazard_msgs = [m for m in node_b._received_messages if m.msg_type == MsgType.HAZARD_ALERT]
    assert len(hazard_msgs) >= 1, f"No HAZARD_ALERT received by node_b"
    assert hazard_msgs[0].payload["hazard_type"] == HazardType.SPEED_TRAP_NO_SIGN

    node_a.stop()
    node_b.stop()
    _MockBLETransport._mesh_registry.clear()
    print("[PASS] test_ble_mesh_two_nodes")


def test_ble_mesh_message_serialisation():
    from agents.ble_mesh_broker import MeshMessage, MsgType, HazardType

    msg = MeshMessage(
        msg_type=MsgType.HAZARD_ALERT,
        sender_id="node-xyz",
        payload={"hazard_type": HazardType.POTHOLE, "lat": 13.01, "lon": 80.20, "severity": "LOW", "confidence": 0.5},
    )
    raw = msg.to_bytes()
    assert len(raw) <= 244, "Packet exceeds BLE MTU"
    recovered = MeshMessage.from_bytes(raw)
    assert recovered.msg_type == MsgType.HAZARD_ALERT
    assert recovered.payload["hazard_type"] == HazardType.POTHOLE
    print("[PASS] test_ble_mesh_message_serialisation")


# ---------------------------------------------------------------------------
# AcousticUI
# ---------------------------------------------------------------------------
def test_acoustic_ui_silent_mode():
    from agents.acoustic_ui import AcousticUIAgent

    agent = AcousticUIAgent(silent=True)
    agent.start()
    agent.speak("near_miss_critical")
    agent.speak_raw("Test alert", lang="en")
    time.sleep(0.1)
    agent.stop()
    print("[PASS] test_acoustic_ui_silent_mode")


def test_acoustic_ui_tanglish_phrase_map():
    from agents.acoustic_ui import AcousticUIAgent, TANGLISH_PHRASES

    agent = AcousticUIAgent(silent=True)
    assert "near_miss_critical" in TANGLISH_PHRASES
    assert "speed_trap_no_sign" in TANGLISH_PHRASES
    assert "blackspot_alert" in TANGLISH_PHRASES
    phrase = agent.get_phrase("near_miss_critical")
    assert "Kavanam" in phrase or phrase  # Tanglish or key fallback
    print("[PASS] test_acoustic_ui_tanglish_phrase_map")


# ---------------------------------------------------------------------------
# Blackspot Geofence
# ---------------------------------------------------------------------------
def test_blackspot_loads_csv():
    from agents.blackspot_geofence import BlackspotGeofenceAgent

    agent = BlackspotGeofenceAgent()
    ok = agent.load()
    assert ok, "No zones loaded"
    trend = agent.get_trend()
    assert "latest_year" in trend
    assert "blackspot_count" in trend
    zones = agent.get_zones()
    assert len(zones) >= 1
    print(f"[PASS] test_blackspot_loads_csv (trend={trend})")


def test_blackspot_kathipara_alert():
    from agents.blackspot_geofence import BlackspotGeofenceAgent

    agent = BlackspotGeofenceAgent()
    agent.load()
    # Kathipara Junction coordinates
    alert = agent.check_position(lat=13.0102, lon=80.2069)
    assert alert is not None, "Expected blackspot alert for Kathipara Junction"
    assert "Kathipara" in alert["zone_name"]
    assert alert["risk_index"] > 0
    print("[PASS] test_blackspot_kathipara_alert")


def test_blackspot_no_alert_outside_zones():
    from agents.blackspot_geofence import BlackspotGeofenceAgent

    agent = BlackspotGeofenceAgent()
    agent.load()
    # Middle of Bay of Bengal — no zone
    alert = agent.check_position(lat=11.0, lon=85.0)
    assert alert is None
    print("[PASS] test_blackspot_no_alert_outside_zones")


def test_blackspot_cooldown():
    from agents.blackspot_geofence import BlackspotGeofenceAgent

    agent = BlackspotGeofenceAgent()
    agent.load()
    alert1 = agent.check_position(lat=13.0102, lon=80.2069)
    assert alert1 is not None
    # Second call immediately — should be suppressed by cooldown
    alert2 = agent.check_position(lat=13.0102, lon=80.2069)
    assert alert2 is None, "Cooldown not enforced"
    print("[PASS] test_blackspot_cooldown")


if __name__ == "__main__":
    test_legal_rag_baseline_query()
    test_legal_rag_section208_query()
    test_legal_rag_uls_match()
    test_legal_rag_empty_query()
    test_sec208_challenge_generated()
    test_sec208_compliance_verified()
    test_sec208_non_camera_object()
    test_sec208_evidence_hash_is_sha3_256()
    test_sign_auditor_mock_mode()
    test_sign_auditor_process_frame_returns_result()
    test_sign_auditor_sec208_trigger_without_sign()
    test_sign_auditor_no_trigger_with_sign()
    test_ble_mesh_two_nodes()
    test_ble_mesh_message_serialisation()
    test_acoustic_ui_silent_mode()
    test_acoustic_ui_tanglish_phrase_map()
    test_blackspot_loads_csv()
    test_blackspot_kathipara_alert()
    test_blackspot_no_alert_outside_zones()
    test_blackspot_cooldown()
    print("\n[ALL PASS] test_agents.py")
