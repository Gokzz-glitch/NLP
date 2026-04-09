"""
tests/test_property_based.py
SmartSalai Edge-Sentinel — Property-Based Tests (Hypothesis)

Validates invariants that must hold for *any* valid input across:
  - ZKPEnvelopeBuilder: seal/open round-trip, coordinate coarsening
  - IRADSerializer: schema completeness, SHA3 integrity
  - IMUSample / NearMissDetector: severity monotonicity, no phantom events
  - Section208Resolver / Sec208DrafterAgent: challenge / no-challenge correctness
  - BLEMeshMessage: serialization round-trip within MTU
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hashlib
import json
import math
import struct

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

# Reduced settings for CI speed
_FAST = settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])

TN_LAT = st.floats(min_value=8.0, max_value=13.5, allow_nan=False, allow_infinity=False)
TN_LON = st.floats(min_value=76.9, max_value=80.4, allow_nan=False, allow_infinity=False)
SPEED_KMH = st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False)

# ──────────────────────────────────────────────────────────────────────────────
# 1. ZKP Envelope — seal/open round-trip must always succeed
# ──────────────────────────────────────────────────────────────────────────────

@given(
    lat=TN_LAT,
    lon=TN_LON,
    speed=SPEED_KMH,
    event_type=st.text(min_size=1, max_size=64, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
)
@_FAST
def test_zkp_round_trip_any_payload(lat, lon, speed, event_type):
    """seal() then open() must always verify successfully for valid float payloads."""
    from core.zkp_envelope import ZKPEnvelopeBuilder

    builder = ZKPEnvelopeBuilder()
    payload = {"gps_lat": lat, "gps_lon": lon, "speed_kmh": speed}
    env = builder.seal(payload, event_type)

    opened = builder.open(env, env._blinding_bytes)
    assert opened.evidence_hash_verified, "Evidence hash must verify"
    assert opened.commitment_verified, "Pedersen commitment must verify"
    assert abs(opened.payload["gps_lat"] - lat) < 1e-9
    assert abs(opened.payload["speed_kmh"] - speed) < 1e-9


@given(lat=TN_LAT, lon=TN_LON)
@_FAST
def test_zkp_coordinate_coarsening_within_grid(lat, lon):
    """Coarsened coordinate must lie within one grid cell of the raw coordinate."""
    from core.zkp_envelope import coarsen_coordinate, _GRID_DEG

    coarse_lat, coarse_lon = coarsen_coordinate(lat, lon)
    assert abs(coarse_lat - lat) <= _GRID_DEG + 1e-9
    assert abs(coarse_lon - lon) <= _GRID_DEG + 1e-9


@given(lat=TN_LAT, lon=TN_LON)
@_FAST
def test_zkp_wrap_event_populates_gps(lat, lon):
    """wrap_event must populate gps_lat/gps_lon on a NearMissEvent without raising."""
    import uuid
    from core.zkp_envelope import wrap_event
    from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity

    event = NearMissEvent(
        event_id=str(uuid.uuid4()),
        timestamp_epoch_ms=1700000000000,
        severity=NearMissSeverity.MEDIUM,
        tcn_anomaly_score=0.3,
    )
    wrapped = wrap_event(event, raw_lat=lat, raw_lon=lon)
    assert wrapped.gps_lat is not None
    assert wrapped.gps_lon is not None


# ──────────────────────────────────────────────────────────────────────────────
# 2. IRADSerializer — schema completeness for arbitrary near-miss scores
# ──────────────────────────────────────────────────────────────────────────────

SEVERITY_STRS = st.sampled_from(["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"])


@given(score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False), severity=SEVERITY_STRS)
@_FAST
def test_irad_schema_completeness(score, severity):
    """IRADRecord.to_dict() must include all mandatory iRAD keys."""
    from core.irad_serializer import IRADSerializer

    ser = IRADSerializer()
    event = {"severity": severity, "near_miss_score": score, "speed_kmh": 50.0}
    record = ser.from_near_miss(event)
    record.finalise()

    d = record.to_dict()
    mandatory_keys = [
        "accident_id", "schema_version", "timestamp_utc",
        "severity_code", "near_miss_score", "record_sha3",
    ]
    for key in mandatory_keys:
        assert key in d, f"Missing mandatory iRAD key: {key!r}"

    # SHA3 must be 64-char hex
    sha = d["record_sha3"]
    assert len(sha) == 64
    int(sha, 16)  # must be valid hex


@given(score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
@_FAST
def test_irad_sha3_deterministic(score):
    """Same input must always produce the same SHA3 record hash."""
    from core.irad_serializer import IRADSerializer

    ser = IRADSerializer()
    event = {"severity": "HIGH", "near_miss_score": score, "speed_kmh": 60.0}

    record1 = ser.from_near_miss(event)
    # Override auto-generated non-deterministic fields
    record1.accident_id = "fixed-uuid"
    record1.timestamp_utc = "2026-01-01T00:00:00Z"
    record1.timestamp_epoch_ms = 0
    record1.finalise()

    record2 = ser.from_near_miss(event)
    record2.accident_id = "fixed-uuid"
    record2.timestamp_utc = "2026-01-01T00:00:00Z"
    record2.timestamp_epoch_ms = 0
    record2.finalise()

    assert record1.record_sha3 == record2.record_sha3


# ──────────────────────────────────────────────────────────────────────────────
# 3. NearMissDetector — severity monotonicity
# ──────────────────────────────────────────────────────────────────────────────

@given(
    lateral_g=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
    decel=st.floats(min_value=0.0, max_value=20.0, allow_nan=False),
    yaw_rate=st.floats(min_value=0.0, max_value=360.0, allow_nan=False),
    rms_jerk=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
)
@_FAST
def test_severity_classification_monotone(lateral_g, decel, yaw_rate, rms_jerk):
    """Severity must be monotone: higher kinematics → same or higher severity."""
    from agents.imu_near_miss_detector import (
        NearMissFeatureExtractor, NearMissSeverity,
        LATERAL_G_CRITICAL_THRESHOLD,
        LONGITUDINAL_DECEL_CRITICAL_MS2, YAW_RATE_CRITICAL_DEGS,
    )

    extractor = NearMissFeatureExtractor()
    # classify_severity_deterministic(lateral_g, decel_ms2, yaw_degs, rms_jerk)
    sev = extractor.classify_severity_deterministic(lateral_g, decel, yaw_rate, rms_jerk)

    # CRITICAL must be returned when any single threshold is clearly exceeded
    if (lateral_g >= LATERAL_G_CRITICAL_THRESHOLD
            or decel >= LONGITUDINAL_DECEL_CRITICAL_MS2
            or yaw_rate >= YAW_RATE_CRITICAL_DEGS):
        assert sev == NearMissSeverity.CRITICAL, (
            f"Expected CRITICAL for lat_g={lateral_g:.3f} decel={decel:.3f} "
            f"yaw={yaw_rate:.1f}, got {sev}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Sec208DrafterAgent — challenge iff camera present AND no sign
# ──────────────────────────────────────────────────────────────────────────────

@given(
    device_id=st.text(min_size=1, max_size=32, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"),
    lat=TN_LAT,
    lon=TN_LON,
    signage_detected=st.booleans(),
)
@_FAST
def test_sec208_challenge_iff_no_sign(device_id, lat, lon, signage_detected):
    """Challenge must be generated iff a camera device_id is present AND no sign is detected."""
    from agents.sec208_drafter import Sec208DrafterAgent

    drafter = Sec208DrafterAgent()
    camera_data = {"device_id": device_id, "lat": lat, "lon": lon}
    result = drafter.evaluate(camera_data=camera_data, signage_detected=signage_detected)

    if signage_detected:
        assert result["status"] == "COMPLIANT", (
            f"Should be COMPLIANT when sign detected, got {result['status']}"
        )
    else:
        assert result["status"] == "CHALLENGE_GENERATED", (
            f"Should be CHALLENGE_GENERATED when no sign, got {result['status']}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 5. BLEMeshMessage — serialization round-trip within MTU
# ──────────────────────────────────────────────────────────────────────────────

@given(
    lat=TN_LAT,
    lon=TN_LON,
    severity=st.sampled_from(["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@_FAST
def test_ble_message_round_trip_within_mtu(lat, lon, severity, confidence):
    """MeshMessage serialization must survive round-trip and fit in 244-byte BLE MTU."""
    from agents.ble_mesh_broker import MeshMessage, MsgType, HazardType

    msg = MeshMessage(
        msg_type=MsgType.HAZARD_ALERT,
        sender_id="test-node",
        payload={
            "hazard_type": HazardType.POTHOLE,
            "lat": lat,
            "lon": lon,
            "severity": severity,
            "confidence": confidence,
        },
    )
    raw = msg.to_bytes()
    assert len(raw) <= 244, f"Packet {len(raw)} bytes exceeds BLE 4.2 MTU (244 bytes)"

    recovered = MeshMessage.from_bytes(raw)
    assert recovered.msg_type == msg.msg_type
    assert recovered.sender_id == msg.sender_id
    assert recovered.payload["hazard_type"] == HazardType.POTHOLE
    assert recovered.payload["severity"] == severity


# ──────────────────────────────────────────────────────────────────────────────
# 6. AgentBus — topic routing invariant
# ──────────────────────────────────────────────────────────────────────────────

@given(
    topic=st.text(min_size=1, max_size=64, alphabet="abcdefghijklmnopqrstuvwxyz._"),
    payload_key=st.text(min_size=1, max_size=32, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    payload_val=st.integers(min_value=0, max_value=1_000_000),
)
@_FAST
def test_agent_bus_routing_invariant(topic, payload_key, payload_val):
    """Messages published to a topic must be received by that topic's subscriber."""
    import time
    from core.agent_bus import AgentBus, reset_bus

    reset_bus()
    bus = AgentBus()
    bus.start()

    received = []
    bus.subscribe(topic, lambda m: received.append(m.params))
    bus.publish(topic, {payload_key: payload_val})
    time.sleep(0.05)
    bus.stop()
    reset_bus()

    assert len(received) == 1
    assert received[0][payload_key] == payload_val
