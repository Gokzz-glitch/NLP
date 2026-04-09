"""
tests/test_core.py
Smoke tests for core infrastructure:
  - AgentBus (T-013)
  - ZKPEnvelopeBuilder (T-014)
  - IRADSerializer (T-015)
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_agent_bus_publish_subscribe():
    from core.agent_bus import AgentBus

    bus = AgentBus()
    bus.start()

    received = []
    bus.subscribe("imu.near_miss", lambda msg: received.append(msg))
    bus.publish("imu.near_miss", {"severity": "CRITICAL", "score": 0.95})
    time.sleep(0.1)
    bus.stop()

    assert len(received) == 1
    assert received[0].params["severity"] == "CRITICAL"
    print("[PASS] test_agent_bus_publish_subscribe")


def test_agent_bus_no_handler():
    from core.agent_bus import AgentBus

    bus = AgentBus()
    bus.start()
    # Should not raise
    bus.publish("unknown.topic", {"data": 1})
    time.sleep(0.05)
    bus.stop()
    print("[PASS] test_agent_bus_no_handler")


def test_agent_bus_wildcard_subscriber():
    from core.agent_bus import AgentBus

    bus = AgentBus()
    bus.start()

    all_msgs = []
    bus.subscribe("*", lambda msg: all_msgs.append(msg.topic))
    bus.publish("vision.detection", {"label": "speed_camera"})
    bus.publish("tts.announce", {"text": "alert"})
    time.sleep(0.15)
    bus.stop()

    assert "vision.detection" in all_msgs
    assert "tts.announce" in all_msgs
    print("[PASS] test_agent_bus_wildcard_subscriber")


def test_agent_bus_handler_error_doesnt_crash():
    from core.agent_bus import AgentBus

    bus = AgentBus()
    bus.start()

    def bad_handler(msg):
        raise RuntimeError("intentional error")

    bus.subscribe("tts.announce", bad_handler)
    bus.publish("tts.announce", {"text": "hi"})
    time.sleep(0.1)
    bus.stop()
    # Should complete without exception
    print("[PASS] test_agent_bus_handler_error_doesnt_crash")


def test_zkp_seal_and_open():
    from core.zkp_envelope import ZKPEnvelopeBuilder

    builder = ZKPEnvelopeBuilder()
    payload = {"gps_lat": 12.9240, "gps_lon": 80.2300, "speed_kmh": 72.5}
    env = builder.seal(payload, "NearMissEvent")

    assert env.envelope_version == "ZKP-1.0"
    assert env.evidence_hash
    assert env.commitment_hex
    assert env._blinding_bytes

    opened = builder.open(env, env._blinding_bytes)
    assert opened.evidence_hash_verified, "Evidence hash verification failed"
    assert opened.commitment_verified, "Commitment verification failed"
    assert opened.payload["gps_lat"] == payload["gps_lat"]
    assert opened.payload["speed_kmh"] == payload["speed_kmh"]
    print("[PASS] test_zkp_seal_and_open")


def test_zkp_no_gps_payload():
    from core.zkp_envelope import ZKPEnvelopeBuilder

    builder = ZKPEnvelopeBuilder()
    payload = {"section": "208", "challenge_id": "abc-123"}
    env = builder.seal(payload, "LegalChallengeEvent")
    opened = builder.open(env, env._blinding_bytes)
    assert opened.evidence_hash_verified
    assert opened.payload["section"] == "208"
    print("[PASS] test_zkp_no_gps_payload")


def test_zkp_tamper_detection():
    from core.zkp_envelope import ZKPEnvelopeBuilder, ZKPEnvelope, TamperDetectedError

    builder = ZKPEnvelopeBuilder()
    payload = {"gps_lat": 12.924, "speed_kmh": 60.0}
    env = builder.seal(payload, "NearMiss")

    # Tamper: replace evidence_hash with zeroes
    tampered = ZKPEnvelope(
        envelope_version=env.envelope_version,
        payload_type=env.payload_type,
        commitment_hex=env.commitment_hex,
        blinding_factor_hash=env.blinding_factor_hash,
        evidence_hash="0000000000000000000000000000000000000000000000000000000000000000",
        timestamp_epoch_ms=env.timestamp_epoch_ms,
        payload_ciphertext=env.payload_ciphertext,
        nonce_hex=env.nonce_hex,
        _blinding_bytes=env._blinding_bytes,
    )
    try:
        builder.open(tampered, env._blinding_bytes)
        assert False, "Expected TamperDetectedError was not raised"
    except TamperDetectedError:
        pass  # correct — tamper detected
    print("[PASS] test_zkp_tamper_detection")


def test_irad_from_near_miss():
    from core.irad_serializer import IRADSerializer
    from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity

    ser = IRADSerializer()
    event = {
        "severity": "CRITICAL",
        "near_miss_score": 0.95,
        "speed_kmh": 72.0,
        "gps_lat": 12.9240,
        "gps_lon": 80.2300,
        "irad_category_code": "NM_TWOWHEELER",
    }
    record = ser.from_near_miss(event)
    assert record.severity_code == 2
    assert record.near_miss_score == 0.95
    assert record.gps_lat == 12.9240

    record.finalise()
    assert record.record_sha3, "SHA3 not computed"

    d = record.to_dict()
    assert d["schema_version"] == "MORTH-iRAD-2022-v1"
    assert d["severity_code"] == 2
    print("[PASS] test_irad_from_near_miss")


def test_irad_csv_export():
    from core.irad_serializer import IRADSerializer

    ser = IRADSerializer()
    event = {"severity": "HIGH", "near_miss_score": 0.7, "speed_kmh": 55.0}
    record = ser.from_near_miss(event)
    record.finalise()
    row = ser.export_csv_row(record)
    assert "accident_id" in row
    assert "severity_code" in row
    assert row["severity_code"] == "3"
    print("[PASS] test_irad_csv_export")


if __name__ == "__main__":
    test_agent_bus_publish_subscribe()
    test_agent_bus_no_handler()
    test_agent_bus_wildcard_subscriber()
    test_agent_bus_handler_error_doesnt_crash()
    test_zkp_seal_and_open()
    test_zkp_no_gps_payload()
    test_zkp_tamper_detection()
    test_irad_from_near_miss()
    test_irad_csv_export()
    print("\n[ALL PASS] test_core.py")
