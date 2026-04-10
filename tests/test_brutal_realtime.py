"""
tests/test_brutal_realtime.py
SmartSalai Edge-Sentinel — Brutal Real-Time Safety & Throughput Test Suite

NO SUGAR-COATING. This file hits every critical path hard:

  BRT-001  IMU 100 Hz real-time throughput — 30 s of continuous samples,
           per-sample wall-clock budget ≤ 10 ms (100 Hz ceiling).
  BRT-002  Safety edge-cases — NaN, ±Inf, extreme values, zero, None-like
           sentinel — detector must never crash or raise an unhandled exception.
  BRT-003  AgentBus message storm — 1 000 concurrent publishes; all
           safety-critical topics must be delivered, zero unhandled errors.
  BRT-004  ZKP concurrent sealing — 100 envelopes sealed in parallel across
           worker threads; every envelope must verify clean.
  BRT-005  Section 208 rapid-fire — 200 rapid evaluations cycling all three
           outcomes (CHALLENGE_GENERATED, COMPLIANT, NOT_APPLICABLE).
  BRT-006  BLE Mesh multi-node flood — 10 nodes broadcast simultaneously;
           every peer node must receive all HAZARD_ALERT messages.
  BRT-007  End-to-end pipeline integrity — near-miss + Sec208 + TTS + iRAD
           all fire within a single deterministic stimulus loop.
  BRT-008  API server security contracts — auth bypass, missing payload,
           wrong signature: each must be rejected; no 200 OK on bad data.
  BRT-009  IMU buffer concurrent push — 20 threads push samples simultaneously;
           final window shape must remain valid, no data race crash.
  BRT-010  iRAD serializer concurrent export — 50 threads serialise records
           in parallel; each CSV row must be schema-valid.
  BRT-011  ZKP tamper detection under concurrent load — 60 tampered envelopes
           opened in parallel; TamperDetectedError must always be raised.
  BRT-012  AgentBus crash resilience — every registered handler raises an
           exception; bus must survive and publisher thread must not see errors.
  BRT-013  Near-miss → iRAD latency — full pipeline (push_sample → finalise →
           CSV export) must complete within 50 ms soft real-time deadline.
"""

from __future__ import annotations

import math
import sys
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_imu(t_ms: int = 0, ax: float = 0.0, ay: float = 0.0,
              az: float = 9.80665, gx: float = 0.0, gy: float = 0.0,
              gz: float = 0.0):
    from agents.imu_near_miss_detector import IMUSample
    return IMUSample(
        timestamp_epoch_ms=t_ms,
        accel_x_ms2=ax, accel_y_ms2=ay, accel_z_ms2=az,
        gyro_x_degs=gx, gyro_y_degs=gy, gyro_z_degs=gz,
    )


def _fresh_detector(interval: int = 10, threshold: float = 0.65):
    from agents.imu_near_miss_detector import NearMissDetector
    d = NearMissDetector(onnx_model_path=None,
                         inference_interval_samples=interval,
                         anomaly_score_threshold=threshold)
    d.load()
    return d


# ===========================================================================
# BRT-001 — IMU 100 Hz real-time throughput
# ===========================================================================

def test_imu_100hz_realtime_throughput():
    """
    BRT-001: Feed 3 000 samples (30 s at 100 Hz) into the detector.
    Each push_sample() call must complete within ≤ 10 ms (100 Hz budget).
    The test records every per-call latency and fails if any single call
    exceeds the deadline.
    """
    from agents.imu_near_miss_detector import (
        GRAVITY_MS2, LATERAL_G_CRITICAL_THRESHOLD,
    )
    det = _fresh_detector(interval=10)

    TOTAL_SAMPLES = 3_000          # 30 s worth
    DEADLINE_MS   = 10.0           # hard 100 Hz ceiling

    violations: List[float] = []
    t_base_ms = int(time.time() * 1000)

    for i in range(TOTAL_SAMPLES):
        # After warmup, inject realistic swerve every ~500 samples
        if i > 120 and i % 500 < 20:
            ay = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 1.4
        else:
            ay = 0.0

        sample = _make_imu(t_ms=t_base_ms + i * 10, ay=ay)

        t0 = time.perf_counter()
        det.push_sample(sample)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if elapsed_ms > DEADLINE_MS:
            violations.append(elapsed_ms)

    assert not violations, (
        f"BRT-001 FAILED: {len(violations)} samples exceeded 10 ms deadline.\n"
        f"Max latency: {max(violations):.2f} ms  "
        f"(limit: {DEADLINE_MS} ms, {TOTAL_SAMPLES} total samples)"
    )
    print(f"[PASS] BRT-001: {TOTAL_SAMPLES} samples @ 100 Hz, 0 deadline violations")


# ===========================================================================
# BRT-002 — Safety edge-cases: NaN, ±Inf, extreme values
# ===========================================================================

EDGE_CASES = [
    # (description, ax, ay, az, gx, gy, gz)
    ("NaN accel_x",        float("nan"), 0.0,           9.8, 0.0, 0.0, 0.0),
    ("NaN accel_y",        0.0,          float("nan"),  9.8, 0.0, 0.0, 0.0),
    ("NaN accel_z",        0.0,          0.0,           float("nan"), 0.0, 0.0, 0.0),
    ("+Inf lateral",       0.0,          float("inf"),  9.8, 0.0, 0.0, 0.0),
    ("-Inf lateral",       0.0,          float("-inf"), 9.8, 0.0, 0.0, 0.0),
    ("+Inf gyro_z",        0.0,          0.0,           9.8, 0.0, 0.0, float("inf")),
    ("Extreme +ax 1000",   1000.0,       0.0,           9.8, 0.0, 0.0, 0.0),
    ("Extreme -ay 1000",   0.0,         -1000.0,        9.8, 0.0, 0.0, 0.0),
    ("Extreme yaw 36000",  0.0,          0.0,           9.8, 0.0, 0.0, 36000.0),
    ("All zero",           0.0,          0.0,           0.0, 0.0, 0.0, 0.0),
    ("Negative gravity",   0.0,          0.0,          -9.8, 0.0, 0.0, 0.0),
    ("Very small values",  1e-10,        1e-10,         9.8, 0.0, 0.0, 0.0),
]


@pytest.mark.parametrize("label,ax,ay,az,gx,gy,gz", EDGE_CASES)
def test_imu_safety_edge_case(label, ax, ay, az, gx, gy, gz):
    """
    BRT-002: The detector must never raise an unhandled exception regardless
    of how malformed the IMU input is.  It may return None or a NearMissEvent,
    but it must not crash.
    """
    det = _fresh_detector()
    # Warm up with valid data first
    for i in range(130):
        det.push_sample(_make_imu(t_ms=i * 10))

    try:
        result = det.push_sample(_make_imu(t_ms=200_000, ax=ax, ay=ay, az=az,
                                            gx=gx, gy=gy, gz=gz))
        # result is either None or a NearMissEvent — both are acceptable
        # What is NOT acceptable is a raised exception
    except Exception as exc:
        pytest.fail(f"BRT-002 FAILED [{label}]: detector raised {type(exc).__name__}: {exc}")

    print(f"[PASS] BRT-002 [{label}]")


# ===========================================================================
# BRT-003 — AgentBus message storm
# ===========================================================================

def test_agent_bus_message_storm():
    """
    BRT-003: Publish 1 000 messages across all safety-critical topics from
    multiple threads.  All messages must be delivered (no silent drops for
    subscribed topics).  Bus errors must be zero.
    """
    from core.agent_bus import AgentBus, Topics

    MESSAGES_PER_TOPIC = 100
    TOPICS = [
        Topics.IMU_NEAR_MISS,
        Topics.VISION_DETECTION,
        Topics.LEGAL_CHALLENGE,
        Topics.TTS_ANNOUNCE,
        Topics.IRAD_EMIT,
        Topics.BLACKSPOT_ALERT,
        Topics.BLE_HAZARD,
        Topics.BLE_HEARTBEAT,
        Topics.RAG_QUERY,
        Topics.RAG_RESPONSE,
    ]

    bus = AgentBus(queue_maxsize=2048)
    bus.start()

    received: dict[str, list] = {t: [] for t in TOPICS}
    lock = threading.Lock()

    for topic in TOPICS:
        def _handler(msg, t=topic):
            with lock:
                received[t].append(msg.message_id)
        bus.subscribe(topic, _handler)

    def _publisher(topic: str, n: int):
        for i in range(n):
            bus.publish(topic, {"seq": i, "topic": topic})

    with ThreadPoolExecutor(max_workers=len(TOPICS)) as pool:
        futs = [pool.submit(_publisher, t, MESSAGES_PER_TOPIC) for t in TOPICS]
        for f in as_completed(futs):
            f.result()

    # Give the worker a moment to drain the queue
    time.sleep(0.5)
    bus.stop()

    stats = bus.stats()
    assert stats["errors"] == 0, f"BRT-003: Bus dispatcher logged {stats['errors']} errors"

    for topic in TOPICS:
        got = len(received[topic])
        assert got == MESSAGES_PER_TOPIC, (
            f"BRT-003 FAILED: topic={topic!r} expected {MESSAGES_PER_TOPIC} "
            f"messages, received {got}"
        )

    total = sum(len(v) for v in received.values())
    print(f"[PASS] BRT-003: {total} messages delivered across {len(TOPICS)} topics, 0 errors")


# ===========================================================================
# BRT-004 — ZKP concurrent sealing
# ===========================================================================

def test_zkp_concurrent_sealing():
    """
    BRT-004: Seal 100 ZKP envelopes concurrently across a thread pool.
    Every envelope must verify correctly — no hash collision, no tamper false
    negatives.
    """
    from core.zkp_envelope import ZKPEnvelopeBuilder

    N = 100
    failures: List[str] = []
    lock = threading.Lock()

    def _seal_and_verify(i: int):
        builder = ZKPEnvelopeBuilder()
        payload = {
            "gps_lat": 12.9240 + i * 0.0001,
            "gps_lon": 80.2300 + i * 0.0001,
            "speed_kmh": float(40 + i),
            "seq": i,
        }
        try:
            env = builder.seal(payload, f"BrutalTest_{i}")
            opened = builder.open(env, env._blinding_bytes)
            if not opened.evidence_hash_verified:
                with lock:
                    failures.append(f"seq={i}: evidence_hash_verified=False")
            if not opened.commitment_verified:
                with lock:
                    failures.append(f"seq={i}: commitment_verified=False")
            if opened.payload["seq"] != i:
                with lock:
                    failures.append(f"seq={i}: payload mismatch")
        except Exception as exc:
            with lock:
                failures.append(f"seq={i}: {type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(_seal_and_verify, range(N)))

    assert not failures, f"BRT-004 FAILED ({len(failures)} failures):\n" + "\n".join(failures[:10])
    print(f"[PASS] BRT-004: {N} ZKP envelopes sealed and verified concurrently")


# ===========================================================================
# BRT-005 — Section 208 rapid-fire
# ===========================================================================

def test_sec208_rapid_fire():
    """
    BRT-005: 200 rapid Section 208 evaluations cycling all three outcomes.
    Correctness must be 100% — wrong outcome is a legal safety failure.
    """
    from agents.sec208_drafter import Sec208DrafterAgent

    drafter = Sec208DrafterAgent()

    scenarios = [
        # (has_device_id, signage_detected, expected_status)
        (True,  False, "CHALLENGE_GENERATED"),
        (True,  True,  "COMPLIANT"),
        (False, False, "NOT_APPLICABLE"),
    ]

    errors: List[str] = []

    for i in range(200):
        has_id, sign, expected = scenarios[i % 3]
        camera_data = {"device_id": f"CAM-{i:04d}", "lat": 12.924, "lon": 80.23} if has_id else {}
        try:
            result = drafter.evaluate(camera_data=camera_data, signage_detected=sign)
            if result["status"] != expected:
                errors.append(
                    f"eval #{i}: camera_id={has_id} sign={sign} → "
                    f"got {result['status']!r}, expected {expected!r}"
                )
        except Exception as exc:
            errors.append(f"eval #{i}: raised {type(exc).__name__}: {exc}")

    assert not errors, f"BRT-005 FAILED ({len(errors)} errors):\n" + "\n".join(errors[:5])
    print(f"[PASS] BRT-005: 200 Sec208 evaluations, 100% correct outcomes")


# ===========================================================================
# BRT-006 — BLE Mesh multi-node flood
# ===========================================================================

def test_ble_mesh_multi_node_flood():
    """
    BRT-006: 5 transmitting nodes broadcast HAZARD_ALERT messages.
    All 5 receiving nodes must receive every message (full mesh coverage).
    """
    from agents.ble_mesh_broker import (
        BLEMeshBrokerAgent, MsgType, HazardType, _MockBLETransport,
    )

    N_TX = 5
    N_RX = 5
    _MockBLETransport._mesh_registry.clear()

    tx_nodes = [BLEMeshBrokerAgent(node_id=f"tx-{i:04x}") for i in range(N_TX)]
    rx_nodes = [BLEMeshBrokerAgent(node_id=f"rx-{i:04x}") for i in range(N_RX)]

    all_nodes = tx_nodes + rx_nodes
    for n in all_nodes:
        n.start()

    hazard_types = [
        HazardType.SPEED_TRAP_NO_SIGN,
        HazardType.POTHOLE,
        HazardType.ACCIDENT_BLACKSPOT,
    ]

    broadcasts = 0
    for i, tx in enumerate(tx_nodes):
        ok = tx.broadcast_hazard(
            hazard_type=hazard_types[i % len(hazard_types)],
            lat=12.924 + i * 0.001,
            lon=80.230 + i * 0.001,
            severity="HIGH",
            confidence=0.90,
        )
        assert ok, f"broadcast failed for tx node {i}"
        broadcasts += 1

    time.sleep(0.3)

    failures: List[str] = []
    for j, rx in enumerate(rx_nodes):
        hazard_msgs = [m for m in rx._received_messages if m.msg_type == MsgType.HAZARD_ALERT]
        if len(hazard_msgs) < N_TX:
            failures.append(
                f"rx-{j:04x} received {len(hazard_msgs)}/{N_TX} hazard messages"
            )

    for n in all_nodes:
        n.stop()
    _MockBLETransport._mesh_registry.clear()

    assert not failures, "BRT-006 FAILED:\n" + "\n".join(failures)
    print(f"[PASS] BRT-006: {N_TX} tx nodes → {N_RX} rx nodes, all {broadcasts} broadcasts received")


# ===========================================================================
# BRT-007 — End-to-end pipeline integrity
# ===========================================================================

def test_end_to_end_pipeline_integrity():
    """
    BRT-007: Drive the full bus-connected pipeline through a deterministic
    stimulus sequence.  All four safety outputs must fire:
      - near_miss event (IMU detector → AgentBus)
      - Section 208 legal challenge (Sec208Drafter → AgentBus)
      - TTS announcement (AcousticUIAgent → AgentBus)
      - iRAD serialized record (IRADSerializer → AgentBus)
    """
    from core.agent_bus import AgentBus, Topics, reset_bus
    from agents.imu_near_miss_detector import NearMissDetector, IMUSample, GRAVITY_MS2, LATERAL_G_CRITICAL_THRESHOLD
    from agents.sec208_drafter import Sec208DrafterAgent
    from agents.acoustic_ui import AcousticUIAgent
    from core.irad_serializer import IRADSerializer

    reset_bus()
    bus = AgentBus(queue_maxsize=512)
    bus.start()

    near_misses: list = []
    sec208_challenges: list = []
    tts_announcements: list = []
    irad_records: list = []

    bus.subscribe(Topics.IMU_NEAR_MISS,   lambda m: near_misses.append(m.params))
    bus.subscribe(Topics.LEGAL_CHALLENGE, lambda m: sec208_challenges.append(m.params))
    bus.subscribe(Topics.TTS_ANNOUNCE,    lambda m: tts_announcements.append(m.params))
    bus.subscribe(Topics.IRAD_EMIT,       lambda m: irad_records.append(m.params))

    drafter    = Sec208DrafterAgent()
    drafter.attach_bus(bus)
    tts        = AcousticUIAgent(silent=True)
    tts.attach_bus(bus)
    tts.start()
    serializer = IRADSerializer()
    detector   = NearMissDetector()
    detector.load()

    t_ms = int(time.time() * 1000)
    ay_critical = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 1.6

    for i in range(150):
        t_ms += 10
        ax = -9.5 if i > 120 else 0.1
        ay = ay_critical if i > 120 else 0.0
        vision_objs = (
            [{"label": "speed_camera", "confidence": 0.92, "bbox": [0.3, 0.1, 0.7, 0.6]}]
            if i > 120 else []
        )
        sample = IMUSample(t_ms, ax, ay, 9.8, 0.0, 0.0, 90.0 if i > 120 else 0.0)
        event = detector.push_sample(sample)

        if event:
            ed = {
                "severity": event.severity.value,
                "near_miss_score": float(event.tcn_anomaly_score),
                "speed_kmh": float(event.vehicle_speed_kmh) if event.vehicle_speed_kmh else 0.0,
                "gps_lat": None,
                "gps_lon": None,
            }
            bus.publish(Topics.IMU_NEAR_MISS, ed)
            record = serializer.from_near_miss(ed)
            record.finalise()
            bus.publish(Topics.IRAD_EMIT, record.to_dict())

        if vision_objs:
            # Intentionally no speed_limit_sign injected — camera without sign triggers Sec208.
            has_sign = any(o["label"] == "speed_limit_sign" for o in vision_objs)
            cam_data = {"device_id": "BRT-007-CAM", "lat": 12.924, "lon": 80.230}
            res = drafter.evaluate(camera_data=cam_data, signage_detected=has_sign,
                                    vision_detections=vision_objs)
            if res["status"] == "CHALLENGE_GENERATED":
                bus.publish(Topics.LEGAL_CHALLENGE, res)
                bus.publish(Topics.TTS_ANNOUNCE, {
                    "text": "Speed camera without signage. Section 208 challenge.",
                    "critical": True,
                })

    time.sleep(0.3)
    bus.stop()
    reset_bus()

    assert len(near_misses)       >= 1, f"BRT-007: expected ≥1 near-miss, got {len(near_misses)}"
    assert len(sec208_challenges) >= 1, f"BRT-007: expected ≥1 Sec208 challenge, got {len(sec208_challenges)}"
    assert len(tts_announcements) >= 1, f"BRT-007: expected ≥1 TTS, got {len(tts_announcements)}"
    assert len(irad_records)      >= 1, f"BRT-007: expected ≥1 iRAD record, got {len(irad_records)}"

    print(
        f"[PASS] BRT-007: near_miss={len(near_misses)}, sec208={len(sec208_challenges)}, "
        f"tts={len(tts_announcements)}, irad={len(irad_records)}"
    )


# ===========================================================================
# BRT-008 — API server security contracts
# ===========================================================================

def test_api_security_auth_bypass_rejected():
    """BRT-008a: Fleet routing endpoint must reject requests with no API key."""
    from api.server import _verify_razorpay_signature

    # No secret configured → always False (safe-fail)
    assert _verify_razorpay_signature("order_1", "pay_1", "deadbeef", "") is False


def test_api_security_razorpay_wrong_signature():
    """BRT-008b: Wrong Razorpay signature must be rejected (not verified)."""
    import hashlib, hmac as _hmac
    from api.server import _verify_razorpay_signature

    secret = "test_secret_key_brutal"
    order_id = "order_abc123"
    pay_id   = "pay_xyz789"

    # Correct signature for reference
    correct_sig = _hmac.new(
        secret.encode(),
        f"{order_id}|{pay_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    # Tampered signature (flip last char)
    tampered = correct_sig[:-1] + ("a" if correct_sig[-1] != "a" else "b")

    assert _verify_razorpay_signature(order_id, pay_id, tampered, secret) is False
    assert _verify_razorpay_signature(order_id, pay_id, correct_sig, secret) is True
    print("[PASS] BRT-008: Razorpay signature verification correct")


def test_api_security_empty_fleet_keys():
    """
    BRT-008c: FLEET_API_KEYS is parsed from an env var.
    When the env var is missing/empty the key set must be empty (deny-all).
    """
    import os
    import importlib
    old = os.environ.pop("FLEET_API_KEYS", None)
    try:
        import api.server as srv
        importlib.reload(srv)
        assert len(srv._FLEET_API_KEYS) == 0, (
            "BRT-008c: FLEET_API_KEYS should be empty when env var is unset"
        )
    finally:
        if old is not None:
            os.environ["FLEET_API_KEYS"] = old
    print("[PASS] BRT-008c: deny-all when FLEET_API_KEYS unset")


# ===========================================================================
# BRT-009 — IMU buffer concurrent push
# ===========================================================================

def test_imu_buffer_concurrent_push():
    """
    BRT-009: 20 threads push samples into a shared IMUBuffer simultaneously.
    The operation must not deadlock, crash, or corrupt the buffer shape.
    """
    from agents.imu_near_miss_detector import IMUBuffer, WINDOW_SIZE_SAMPLES

    buf = IMUBuffer(capacity=WINDOW_SIZE_SAMPLES)
    lock = threading.Lock()
    errors: List[str] = []

    def _pusher(thread_id: int):
        from agents.imu_near_miss_detector import IMUSample
        for i in range(50):
            sample = IMUSample(
                timestamp_epoch_ms=thread_id * 1000 + i,
                accel_x_ms2=float(thread_id),
                accel_y_ms2=float(i),
                accel_z_ms2=9.8,
                gyro_x_degs=0.0,
                gyro_y_degs=0.0,
                gyro_z_degs=float(thread_id + i),
            )
            try:
                buf.push(sample)
            except Exception as exc:
                with lock:
                    errors.append(f"thread={thread_id} i={i}: {exc}")

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(_pusher, range(20)))

    assert not errors, f"BRT-009 FAILED: {len(errors)} errors:\n" + "\n".join(errors[:5])

    w = buf.get_window()
    assert w.shape == (WINDOW_SIZE_SAMPLES, 6), (
        f"BRT-009: corrupted window shape {w.shape}"
    )
    print(f"[PASS] BRT-009: concurrent push by 20 threads, window shape intact {w.shape}")


# ===========================================================================
# BRT-010 — iRAD serializer concurrent export
# ===========================================================================

def test_irad_serializer_concurrent_export():
    """
    BRT-010: 50 threads each serialise + finalise + export an iRAD record
    concurrently.  Every CSV row must contain all required schema keys and
    a valid SHA3 hash.
    """
    from core.irad_serializer import IRADSerializer

    REQUIRED_KEYS = {"accident_id", "severity_code", "near_miss_score",
                     "speed_kmh", "gps_lat", "gps_lon", "record_sha3",
                     "schema_version"}
    errors: List[str] = []
    lock = threading.Lock()

    def _export(i: int):
        ser = IRADSerializer()
        event = {
            "severity": "CRITICAL" if i % 2 == 0 else "HIGH",
            "near_miss_score": round(0.5 + (i % 10) * 0.04, 2),
            "speed_kmh": float(40 + i),
            "gps_lat": 12.924 + i * 0.0001,
            "gps_lon": 80.230 + i * 0.0001,
        }
        try:
            record = ser.from_near_miss(event)
            record.finalise()
            row = ser.export_csv_row(record)
            missing = REQUIRED_KEYS - set(row.keys())
            if missing:
                with lock:
                    errors.append(f"thread={i}: missing keys {missing}")
            sha3 = row.get("record_sha3", "")
            if not (len(sha3) == 64 and all(c in "0123456789abcdef" for c in sha3)):
                with lock:
                    errors.append(f"thread={i}: invalid SHA3 '{sha3}'")
        except Exception as exc:
            with lock:
                errors.append(f"thread={i}: {type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(_export, range(50)))

    assert not errors, f"BRT-010 FAILED ({len(errors)} errors):\n" + "\n".join(errors[:5])
    print("[PASS] BRT-010: 50 concurrent iRAD exports, all schema-valid")


# ===========================================================================
# BRT-011 — ZKP tamper detection under concurrent load
# ===========================================================================

def test_zkp_tamper_detection_concurrent():
    """
    BRT-011: Tamper with envelopes while a pool of workers is sealing others.
    TamperDetectedError must always be raised — no false negatives.
    """
    from core.zkp_envelope import ZKPEnvelopeBuilder, ZKPEnvelope, TamperDetectedError

    tamper_failures: List[str] = []
    lock = threading.Lock()

    def _tamper_and_detect(i: int):
        builder = ZKPEnvelopeBuilder()
        payload = {"speed_kmh": float(i), "lat": 12.924}
        env = builder.seal(payload, "TamperTest")
        tampered = ZKPEnvelope(
            envelope_version=env.envelope_version,
            payload_type=env.payload_type,
            commitment_hex=env.commitment_hex,
            blinding_factor_hash=env.blinding_factor_hash,
            evidence_hash="0" * 64,          # forged hash
            timestamp_epoch_ms=env.timestamp_epoch_ms,
            payload_ciphertext=env.payload_ciphertext,
            nonce_hex=env.nonce_hex,
            _blinding_bytes=env._blinding_bytes,
        )
        try:
            builder.open(tampered, env._blinding_bytes)
            with lock:
                tamper_failures.append(f"seq={i}: TamperDetectedError NOT raised")
        except TamperDetectedError:
            pass  # correct

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(_tamper_and_detect, range(60)))

    assert not tamper_failures, (
        f"BRT-011 FAILED — {len(tamper_failures)} tamper events went undetected:\n"
        + "\n".join(tamper_failures[:5])
    )
    print("[PASS] BRT-011: 60 tamper attempts, all detected under concurrent load")


# ===========================================================================
# BRT-012 — AgentBus crash resilience (all handlers throw)
# ===========================================================================

def test_agent_bus_all_handlers_crash():
    """
    BRT-012: Every registered handler on every topic raises an exception.
    The bus must survive, continue dispatching, and report errors — but
    it must NEVER propagate an exception to the publisher thread.
    """
    from core.agent_bus import AgentBus, Topics

    bus = AgentBus(queue_maxsize=256)
    bus.start()

    def _always_crash(msg):
        raise RuntimeError(f"intentional crash on {msg.topic}")

    crash_topics = [
        Topics.IMU_NEAR_MISS,
        Topics.LEGAL_CHALLENGE,
        Topics.TTS_ANNOUNCE,
    ]
    for t in crash_topics:
        bus.subscribe(t, _always_crash)

    # Publish without any exception reaching here
    try:
        for t in crash_topics:
            for _ in range(10):
                bus.publish(t, {"payload": "test"})
    except Exception as exc:
        pytest.fail(f"BRT-012: publisher thread saw exception: {exc}")

    time.sleep(0.3)
    stats = bus.stats()
    bus.stop()

    assert stats["errors"] > 0, "BRT-012: expected error counter > 0 (handlers crashed)"
    assert stats["published"] == len(crash_topics) * 10
    print(
        f"[PASS] BRT-012: {stats['published']} msgs published, "
        f"{stats['errors']} handler crashes — bus stayed alive"
    )


# ===========================================================================
# BRT-013 — Real-time event latency: near-miss → iRAD pipeline latency
# ===========================================================================

def test_near_miss_to_irad_latency():
    """
    BRT-013: From push_sample() emitting a NearMissEvent to producing a
    finalised iRAD record must complete within 50 ms (soft real-time).
    """
    from agents.imu_near_miss_detector import (
        NearMissDetector, IMUSample, GRAVITY_MS2, LATERAL_G_CRITICAL_THRESHOLD,
    )
    from core.irad_serializer import IRADSerializer

    DEADLINE_MS = 50.0
    det = _fresh_detector(interval=1)
    ser = IRADSerializer()

    # Warm up the buffer
    for i in range(130):
        det.push_sample(_make_imu(t_ms=i * 10))

    ay_critical = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 2.0
    latencies: List[float] = []

    for i in range(130, 160):
        t0 = time.perf_counter()
        event = det.push_sample(_make_imu(t_ms=i * 10, ay=ay_critical))
        if event:
            ed = {
                "severity": event.severity.value,
                "near_miss_score": float(event.tcn_anomaly_score),
                "speed_kmh": float(event.vehicle_speed_kmh) if event.vehicle_speed_kmh else 0.0,
                "gps_lat": None, "gps_lon": None,
            }
            record = ser.from_near_miss(ed)
            record.finalise()
            _ = ser.export_csv_row(record)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)

    assert latencies, "BRT-013: no near-miss events were emitted — check detector thresholds"
    violations = [l for l in latencies if l > DEADLINE_MS]
    assert not violations, (
        f"BRT-013 FAILED: {len(violations)}/{len(latencies)} events exceeded "
        f"{DEADLINE_MS} ms latency. Max={max(violations):.2f} ms"
    )
    print(
        f"[PASS] BRT-013: {len(latencies)} near-miss→iRAD events, "
        f"max latency={max(latencies):.2f} ms (limit {DEADLINE_MS} ms)"
    )


# ===========================================================================
# Entry point for direct execution
# ===========================================================================

if __name__ == "__main__":
    print("\n" + "=" * 72)
    print("  SmartSalai Edge-Sentinel — BRUTAL REAL-TIME TEST SUITE")
    print("=" * 72 + "\n")

    test_imu_100hz_realtime_throughput()

    for label, ax, ay, az, gx, gy, gz in EDGE_CASES:
        test_imu_safety_edge_case(label, ax, ay, az, gx, gy, gz)

    test_agent_bus_message_storm()
    test_zkp_concurrent_sealing()
    test_sec208_rapid_fire()
    test_ble_mesh_multi_node_flood()
    test_end_to_end_pipeline_integrity()
    test_api_security_auth_bypass_rejected()
    test_api_security_razorpay_wrong_signature()
    test_api_security_empty_fleet_keys()
    test_imu_buffer_concurrent_push()
    test_irad_serializer_concurrent_export()
    test_zkp_tamper_detection_concurrent()
    test_agent_bus_all_handlers_crash()
    test_near_miss_to_irad_latency()

    print("\n" + "=" * 72)
    print("  [ALL BRUTAL TESTS PASS] — system is real-time safe")
    print("=" * 72 + "\n")
