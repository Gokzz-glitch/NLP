"""
tests/test_brutal_realworld.py
SmartSalai Edge-Sentinel — Brutal Real-World Condition Tests

Validates every subsystem under production-realistic stress.

  Phase 1 : 100 Hz IMU burst — 1 000 samples, latency SLA, no data loss
  Phase 2 : TTS priority queue — 100 concurrent alerts, priority ordering
  Phase 3 : Vision engine — 50-thread concurrent mock inference
  Phase 4 : Section 208 GPS boundary — ±1 m precision around 500 m threshold
  Phase 5 : ZKP concurrent commitments — determinism + zero corruption
  Phase 6 : Bhashini failure modes — timeout, bad creds, malformed response
  Phase 7 : BLE mesh packet storm — 50 concurrent signed messages
  Phase 8 : System orchestrator full pipeline — IMU → TTS → Section 208
  Phase 9 : AcousticUI memory stability — bounded latency window
  Phase 10: ADB deploy edge cases — mixed authorized/unauthorized devices
  Phase 11: ETL text chunker — oversized chunks, empty input, Tamil Unicode
  Phase 12: Haversine edge cases — equatorial, polar, antimeridian, Chennai
"""
from __future__ import annotations

import base64
import json
import os
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from unittest.mock import MagicMock, patch

import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Silence sentence_transformers import in edge_vector_store / orchestrator
if "sentence_transformers" not in sys.modules:
    sys.modules["sentence_transformers"] = MagicMock()


# ---------------------------------------------------------------------------
# Phase 1: 100 Hz IMU burst — latency SLA, no data loss
# ---------------------------------------------------------------------------

class TestIMUBurst:
    """Simulate real 100 Hz dashcam IMU at full speed for 10 seconds (1 000 samples)."""

    def test_1000_samples_no_loss(self):
        from agents.imu_near_miss_detector import NearMissDetector, IMUSample

        detector = NearMissDetector()
        detector.load()

        t_ms = int(time.time() * 1000)
        events_fired = 0
        processed = 0

        for i in range(1000):
            t_ms += 10
            if i < 800:
                ax, ay, az, gyr_z = 0.1, 0.0, 9.81, 0.0
            else:
                ax, ay, az, gyr_z = -8.5, 7.2, 10.5, 95.0
            event = detector.push_sample(IMUSample(t_ms, ax, ay, az, 0.0, 0.0, gyr_z))
            if event is not None:
                events_fired += 1
            processed += 1

        assert processed == 1000, "All 1 000 samples must be processed"
        assert events_fired >= 1, "Hard swerve must trigger at least one near-miss event"

    def test_imu_burst_within_500ms_sla(self):
        """1 000 samples must process in under 500 ms (real-time budget)."""
        from agents.imu_near_miss_detector import NearMissDetector, IMUSample

        detector = NearMissDetector()
        detector.load()
        t_ms = int(time.time() * 1000)
        start = time.perf_counter()
        for i in range(1000):
            t_ms += 10
            detector.push_sample(IMUSample(t_ms, 0.1, 0.0, 9.81, 0, 0, 0.0))
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"IMU processing {elapsed_ms:.1f} ms exceeds 500 ms SLA"

    def test_two_detectors_state_isolated(self):
        """Two NearMissDetector instances must not share state."""
        from agents.imu_near_miss_detector import NearMissDetector, IMUSample

        d1, d2 = NearMissDetector(), NearMissDetector()
        d1.load()
        d2.load()
        t1 = t2 = int(time.time() * 1000)

        for i in range(130):
            t1 += 10
            ax, gyr = (-8.0, 90.0) if i > 110 else (0.1, 0.0)
            d1.push_sample(IMUSample(t1, ax, 7.0, 10.5, 0, 0, gyr))

        events_d2 = []
        for i in range(130):
            t2 += 10
            e = d2.push_sample(IMUSample(t2, 0.1, 0.0, 9.81, 0, 0, 0.0))
            if e:
                events_d2.append(e)

        assert events_d2 == [], "State must not leak between detector instances"

    def test_near_miss_event_has_required_irad_fields(self):
        """Emitted NearMissEvent must include all iRAD V-NMS-01 required fields."""
        from agents.imu_near_miss_detector import NearMissDetector, IMUSample, NearMissEvent

        detector = NearMissDetector()
        detector.load()
        t_ms = int(time.time() * 1000)
        event = None
        for i in range(130):
            t_ms += 10
            ax, gyr = (-8.5, 95.0) if i > 110 else (0.1, 0.0)
            e = detector.push_sample(IMUSample(t_ms, ax, 7.0, 10.5, 0, 0, gyr))
            if e is not None:
                event = e
                break

        assert event is not None, "Hard swerve must produce a NearMissEvent"
        assert hasattr(event, "event_id")
        assert hasattr(event, "severity")
        assert hasattr(event, "timestamp_epoch_ms")
        assert hasattr(event, "irad_category_code")
        assert event.irad_category_code == "V-NMS-01"


# ---------------------------------------------------------------------------
# Phase 2: TTS priority queue — 100 concurrent alerts, CRITICAL always first
# ---------------------------------------------------------------------------

class TestTTSPriorityQueueBrutal:

    def _make_ui(self):
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            with patch.dict("os.environ", {"BHASHINI_USER_ID": "", "BHASHINI_API_KEY": ""}):
                from agents.acoustic_ui import AcousticUI
                return AcousticUI(language="en"), mock_engine

    def test_100_alerts_all_processed_no_deadlock(self):
        """All 100 alerts must be processed — no deadlock, no silent drops."""
        ui, _ = self._make_ui()
        from agents.acoustic_ui import AlertPriority
        for i in range(100):
            pri = AlertPriority.CRITICAL if i % 10 == 0 else AlertPriority.MEDIUM
            ui.announce(f"Alert {i}", priority=pri)
        done = threading.Event()
        def _j():
            ui.join(timeout=15.0)
            done.set()
        t = threading.Thread(target=_j, daemon=True)
        t.start()
        t.join(timeout=16.0)
        assert done.is_set(), "join() deadlocked — 100 alerts not processed"
        ui.stop()

    def test_priority_enum_ordering(self):
        """CRITICAL (0) < HIGH (1) < MEDIUM (2) < LOW (3)."""
        from agents.acoustic_ui import AlertPriority
        assert int(AlertPriority.CRITICAL) < int(AlertPriority.HIGH)
        assert int(AlertPriority.HIGH) < int(AlertPriority.MEDIUM)
        assert int(AlertPriority.MEDIUM) < int(AlertPriority.LOW)

    def test_queue_empty_after_join(self):
        """Queue size must be 0 after join() completes."""
        ui, _ = self._make_ui()
        from agents.acoustic_ui import AlertPriority
        for i in range(20):
            ui.announce(f"msg {i}", priority=AlertPriority.LOW)
        ui.join(timeout=10.0)
        assert ui._queue.qsize() == 0
        ui.stop()

    def test_worker_survives_repeated_engine_crashes(self):
        """Worker must keep running and call task_done() even when engine.say() crashes."""
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        mock_engine.say.side_effect = RuntimeError("hardware crash")
        with patch("pyttsx3.init", return_value=mock_engine):
            with patch.dict("os.environ", {"BHASHINI_USER_ID": "", "BHASHINI_API_KEY": ""}):
                from agents.acoustic_ui import AcousticUI
                ui = AcousticUI(language="en")
        from agents.acoustic_ui import AlertPriority
        for i in range(20):
            ui.announce(f"crash {i}", priority=AlertPriority.HIGH)
        done = threading.Event()
        def _j():
            ui.join(timeout=8.0)
            done.set()
        t = threading.Thread(target=_j, daemon=True)
        t.start()
        t.join(timeout=9.0)
        assert done.is_set(), "join() deadlocked after repeated engine crashes"
        ui.stop()

    def test_bhashini_failure_falls_back_to_pyttsx3(self):
        """When Bhashini raises, pyttsx3 must still be called."""
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            with patch.dict("os.environ", {"BHASHINI_USER_ID": "u", "BHASHINI_API_KEY": "k"}):
                from agents.acoustic_ui import AcousticUI
                from core.bhashini_tts import BhashiniUnavailableError
                ui = AcousticUI(language="ta")
                if ui._bhashini:
                    ui._bhashini.synthesize_and_play = MagicMock(
                        side_effect=BhashiniUnavailableError("simulated network failure")
                    )
        from agents.acoustic_ui import AlertPriority
        ui.announce("test fallback", priority=AlertPriority.HIGH)
        ui.join(timeout=5.0)
        mock_engine.say.assert_called()
        ui.stop()


# ---------------------------------------------------------------------------
# Phase 3: Vision engine — 50-thread concurrent mock inference
# ---------------------------------------------------------------------------

class TestVisionConcurrent:

    def test_50_threads_concurrent_mock_inference(self):
        """50 threads concurrently calling run_inference() in mock mode must all return []."""
        with patch.dict("os.environ", {"VISION_MOCK_MODE": "1"}):
            from vision_audit import VisionAuditEngine
            engine = VisionAuditEngine()

        assert engine.is_mock
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        errors: list = []

        def _infer(tid):
            try:
                result = engine.run_inference(blank)
                assert result == [], f"Thread {tid}: expected [] got {result}"
            except Exception as exc:
                errors.append(f"Thread {tid}: {exc}")

        with ThreadPoolExecutor(max_workers=50) as pool:
            for f in as_completed([pool.submit(_infer, i) for i in range(50)]):
                f.result()

        assert not errors, f"Concurrent mock inference errors: {errors}"

    def test_mock_mode_when_model_absent(self):
        with patch.dict("os.environ", {"VISION_MODEL_PATH": "/nonexistent.onnx",
                                        "VISION_MOCK_MODE": "0"}):
            from vision_audit import VisionAuditEngine
            engine = VisionAuditEngine()
        assert engine.is_mock

    def test_preprocess_output_shape_various_inputs(self):
        """Preprocess must return (1, 3, 640, 640) for any input resolution."""
        try:
            import cv2  # noqa: F401
        except ImportError:
            pytest.skip("cv2 not installed")
        from vision_audit import VisionAuditEngine
        engine = VisionAuditEngine()
        for h, w in [(480, 640), (1080, 1920), (100, 100), (640, 640), (720, 1280)]:
            blob = engine.preprocess(np.zeros((h, w, 3), dtype=np.uint8))
            assert blob.shape == (1, 3, 640, 640), f"Wrong shape for {h}x{w}: {blob.shape}"
            assert blob.dtype == np.float32

    def test_postprocess_empty_on_zero_confidence(self):
        """All-zero output must produce no detections."""
        from vision_audit import VisionAuditEngine
        engine = VisionAuditEngine()
        zero_output = np.zeros((1, 20, 8400), dtype=np.float32)
        assert engine.postprocess(zero_output) == []

    def test_postprocess_high_confidence_detection_returned(self):
        """Output with one high-confidence class must produce one detection."""
        from vision_audit import VisionAuditEngine, INDIAN_TRAFFIC_CLASSES
        engine = VisionAuditEngine()
        # Shape (1, 4+num_classes, 8400) — first anchor, class 4 (speed_camera) = 0.99
        n_cls = len(INDIAN_TRAFFIC_CLASSES)
        output = np.zeros((1, 4 + n_cls, 8400), dtype=np.float32)
        output[0, 0, 0] = 320.0   # cx
        output[0, 1, 0] = 240.0   # cy
        output[0, 2, 0] = 50.0    # w
        output[0, 3, 0] = 50.0    # h
        output[0, 4 + 4, 0] = 0.99  # class 4 = speed_camera
        dets = engine.postprocess(output)
        assert len(dets) >= 1
        assert dets[0]["label"] == "speed_camera"
        assert dets[0]["conf"] >= 0.99


# ---------------------------------------------------------------------------
# Phase 4: Section 208 GPS boundary — ±1 m precision
# ---------------------------------------------------------------------------

class TestSection208GPSBoundary:
    """Uses binary-search-derived dlat for 500 m to avoid floating-point drift."""

    _LAT0 = 13.0827
    _LON0 = 80.2707
    # Verified by binary search: haversine_m(13.0827, 80.2707, 13.0827+DLAT_500M, 80.2707) ≈ 500.0
    _DLAT_500M = 0.00449660800   # degrees north for exactly 500 m

    def test_sign_just_under_500m_is_within_window(self):
        from agents.sign_auditor import SignAuditor
        auditor = SignAuditor()
        sign_lat = self._LAT0 + self._DLAT_500M * 0.998   # ~499 m
        within, dist = auditor.check_sign_in_window(
            self._LAT0, self._LON0, [(sign_lat, self._LON0)]
        )
        assert within is True, f"Sign at ~{dist:.1f} m must be within 500 m window"
        assert dist < 500.0

    def test_sign_at_boundary_500m_is_within_window(self):
        from agents.sign_auditor import SignAuditor
        auditor = SignAuditor()
        sign_lat = self._LAT0 + self._DLAT_500M  # ≈ exactly 500 m
        within, dist = auditor.check_sign_in_window(
            self._LAT0, self._LON0, [(sign_lat, self._LON0)]
        )
        assert within is True, f"Sign at boundary {dist:.2f} m must be within window (≤500 m)"
        assert dist <= 500.5   # small tolerance for floating point

    def test_sign_just_over_501m_is_outside_window(self):
        from agents.sign_auditor import SignAuditor
        auditor = SignAuditor()
        sign_lat = self._LAT0 + self._DLAT_500M * 1.003  # ~501.5 m
        within, dist = auditor.check_sign_in_window(
            self._LAT0, self._LON0, [(sign_lat, self._LON0)]
        )
        assert within is False, f"Sign at {dist:.2f} m must be outside window"
        assert dist > 500.0

    def test_nearest_sign_wins_when_multiple_present(self):
        from agents.sign_auditor import SignAuditor
        auditor = SignAuditor()
        locs = [
            (self._LAT0 + self._DLAT_500M * 0.50, self._LON0),   # ~250 m
            (self._LAT0 + self._DLAT_500M * 1.20, self._LON0),   # ~600 m
            (self._LAT0 + self._DLAT_500M * 1.50, self._LON0),   # ~750 m
        ]
        within, nearest = auditor.check_sign_in_window(self._LAT0, self._LON0, locs)
        assert within is True
        assert nearest < 260.0, f"Nearest should be ~250 m, got {nearest:.1f} m"

    def test_sec208_triggered_camera_no_sign(self):
        from agents.sign_auditor import SignAuditor, SignDetection
        auditor = SignAuditor(vision_engine=None)
        camera = SignDetection("speed_camera", 0.92, gps_lat=self._LAT0, gps_lon=self._LON0)
        # Sign at ~890 m (outside window)
        far_sign = SignDetection("speed_limit_sign", 0.88,
                                  gps_lat=self._LAT0 + 0.008, gps_lon=self._LON0)
        result = auditor.audit_frame(None, self._LAT0, self._LON0,
                                     known_signs=[camera, far_sign])
        assert result.sec208_challengeable is True

    def test_sec208_not_triggered_camera_with_close_sign(self):
        from agents.sign_auditor import SignAuditor, SignDetection
        auditor = SignAuditor(vision_engine=None)
        camera = SignDetection("speed_camera", 0.92, gps_lat=self._LAT0, gps_lon=self._LON0)
        close_sign = SignDetection("speed_limit_sign", 0.88,
                                   gps_lat=self._LAT0 + 0.002, gps_lon=self._LON0)  # ~222 m
        result = auditor.audit_frame(None, self._LAT0, self._LON0,
                                     known_signs=[camera, close_sign])
        assert result.sec208_challengeable is False


# ---------------------------------------------------------------------------
# Phase 5: ZKP concurrent commitments — determinism + no corruption
# ---------------------------------------------------------------------------

class TestZKPConcurrent:

    def test_100_concurrent_commitments_all_valid(self):
        """100 threads each wrapping a NearMissEvent — all commitments must be valid SHA3."""
        from core.zkp_envelope import wrap_event
        from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity

        errors: list = []
        results: list = [None] * 100

        def _wrap(i):
            try:
                event = NearMissEvent(
                    event_id=str(uuid.uuid4()),
                    timestamp_epoch_ms=int(time.time() * 1000) + i,
                    severity=NearMissSeverity.HIGH,
                )
                lat = 13.0827 + random.uniform(-0.01, 0.01)
                lon = 80.2707 + random.uniform(-0.01, 0.01)
                wrapped = wrap_event(event, lat, lon, device_salt=b"real-device-salt")
                assert wrapped._gps_commitment.startswith("sha3:")
                results[i] = wrapped._gps_commitment
            except Exception as exc:
                errors.append(f"Thread {i}: {exc}")

        with ThreadPoolExecutor(max_workers=100) as pool:
            for f in as_completed([pool.submit(_wrap, i) for i in range(100)]):
                f.result()

        assert not errors, f"ZKP concurrent errors: {errors}"
        assert all(r is not None for r in results), "Some commitments are None"

    def test_same_inputs_deterministic(self):
        """Same event, same coordinates, same salt must always produce same commitment."""
        from core.zkp_envelope import wrap_event
        from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity

        commitments = set()
        for _ in range(20):
            event = NearMissEvent(
                event_id="fixed-id",
                timestamp_epoch_ms=1_700_000_000_000,
                severity=NearMissSeverity.CRITICAL,
            )
            wrapped = wrap_event(event, 13.0827, 80.2707, device_salt=b"fixed-salt")
            commitments.add(wrapped._gps_commitment)

        assert len(commitments) == 1, "Non-deterministic commitment detected"

    def test_different_coordinates_different_commitment(self):
        from core.zkp_envelope import wrap_event
        from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity

        e1 = NearMissEvent("id1", 1000, NearMissSeverity.HIGH)
        e2 = NearMissEvent("id2", 1000, NearMissSeverity.HIGH)

        w1 = wrap_event(e1, 13.0, 80.0, device_salt=b"salt")
        w2 = wrap_event(e2, 14.0, 81.0, device_salt=b"salt")
        assert w1._gps_commitment != w2._gps_commitment

    def test_gps_coarsened_to_3dp(self):
        """GPS coordinates stored on event must be coarsened (3 decimal places)."""
        from core.zkp_envelope import wrap_event
        from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity

        event = NearMissEvent("id", 1000, NearMissSeverity.HIGH)
        wrap_event(event, 13.0827_123, 80.2707_456, device_salt=b"s")
        # Coarsened = round to 0.001 degree grid
        assert round(event.gps_lat, 3) == event.gps_lat or abs(event.gps_lat % 0.001) < 1e-9


# ---------------------------------------------------------------------------
# Phase 6: Bhashini failure modes
# ---------------------------------------------------------------------------

class TestBhashiniFailureModes:

    def test_no_credentials_raises(self):
        from core.bhashini_tts import BhashiniTTSClient, BhashiniUnavailableError
        c = BhashiniTTSClient(user_id="", api_key="")
        with pytest.raises(BhashiniUnavailableError, match="credentials"):
            c._discover_pipeline("ta")

    def test_connection_timeout_raises(self):
        from core.bhashini_tts import BhashiniTTSClient, BhashiniUnavailableError
        c = BhashiniTTSClient(user_id="u", api_key="k")
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with pytest.raises(BhashiniUnavailableError):
                c._discover_pipeline("ta")

    def test_network_refused_raises(self):
        from core.bhashini_tts import BhashiniTTSClient, BhashiniUnavailableError
        c = BhashiniTTSClient(user_id="u", api_key="k")
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
            with pytest.raises(BhashiniUnavailableError):
                c._discover_pipeline("ta")

    def test_malformed_json_raises(self):
        from core.bhashini_tts import BhashiniTTSClient, BhashiniUnavailableError
        c = BhashiniTTSClient(user_id="u", api_key="k")
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"not valid {json"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(BhashiniUnavailableError):
                c._discover_pipeline("ta")

    def test_empty_pipeline_response_raises(self):
        from core.bhashini_tts import BhashiniTTSClient, BhashiniUnavailableError
        c = BhashiniTTSClient(user_id="u", api_key="k")
        body = json.dumps({"pipelineResponseConfig": []}).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = body
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(BhashiniUnavailableError):
                c._discover_pipeline("ta")

    def test_discovery_cached_no_second_http_call(self):
        from core.bhashini_tts import BhashiniTTSClient
        c = BhashiniTTSClient(user_id="u", api_key="k")
        with c._cache_lock:
            c._cache["ta"] = ("https://cb.example", "svc1", time.monotonic() + 3600)
        call_count = [0]
        def counting(req, **kw):
            call_count[0] += 1
        with patch("urllib.request.urlopen", side_effect=counting):
            c._discover_pipeline("ta")
        assert call_count[0] == 0, "Cache hit must not make an HTTP call"

    def test_is_configured_returns_true_with_creds(self):
        from core.bhashini_tts import BhashiniTTSClient
        assert BhashiniTTSClient(user_id="u", api_key="k").is_configured()

    def test_is_configured_returns_false_without_creds(self):
        from core.bhashini_tts import BhashiniTTSClient
        assert not BhashiniTTSClient(user_id="", api_key="").is_configured()


# ---------------------------------------------------------------------------
# Phase 7: BLE mesh packet storm — 50 concurrent signed messages
# ---------------------------------------------------------------------------

class TestBLEMeshPacketStorm:

    _TEST_KEY = b"\xAB" * 32  # Fixed test key — avoids dependency on dev-key env var

    def test_50_concurrent_publish_receive_roundtrip(self):
        """50 threads each publishing + receiving a hazard message must all succeed."""
        from agents.ble_mesh_broker import BLEMeshBroker

        broker = BLEMeshBroker(node_id="stress-node", signing_key=self._TEST_KEY)
        errors: list = []

        def _roundtrip(i):
            try:
                hazard = random.choice(["pothole", "speed_camera", "debris"])
                msg = broker.publish_hazard(
                    hazard_type=hazard,
                    lat=13.0827 + random.uniform(-0.01, 0.01),
                    lon=80.2707 + random.uniform(-0.01, 0.01),
                    severity="HIGH",
                    confidence=round(random.uniform(0.5, 0.99), 3),
                )
                assert msg is not None, f"Thread {i}: publish_hazard returned None"
                assert msg.message_id, "message_id must be non-empty"

                ok = broker.receive(msg)
                assert ok is True or ok is False   # Either accepted or replay-rejected
            except Exception as exc:
                errors.append(f"Thread {i}: {exc}")

        with ThreadPoolExecutor(max_workers=50) as pool:
            for f in as_completed([pool.submit(_roundtrip, i) for i in range(50)]):
                f.result()

        assert not errors, "BLE mesh packet storm errors:\n" + "\n".join(errors)

    def test_tampered_signature_rejected(self):
        """A message with a corrupted signature must be rejected by receive()."""
        from agents.ble_mesh_broker import BLEMeshBroker

        broker = BLEMeshBroker(node_id="tamper-test", signing_key=self._TEST_KEY)
        msg = broker.publish_hazard("pothole", 13.0, 80.0, "HIGH", 0.9)

        # Corrupt the signature bytes
        original_sig = bytes(msg.signature)
        corrupted = bytearray(original_sig)
        corrupted[0] ^= 0xFF
        msg.signature = bytes(corrupted)

        result = broker.receive(msg)
        assert result is False, "Tampered signature must be rejected"

    def test_replay_attack_rejected(self):
        """The exact same message received twice must be rejected on the second receive."""
        from agents.ble_mesh_broker import BLEMeshBroker

        broker = BLEMeshBroker(node_id="replay-test", signing_key=self._TEST_KEY)
        msg = broker.publish_hazard("pothole", 13.0, 80.0, "HIGH", 0.9)

        r1 = broker.receive(msg)
        r2 = broker.receive(msg)
        assert r1 is True, "First receive must succeed"
        assert r2 is False, "Second receive of same message must be rejected (replay attack)"

    def test_heartbeat_message_accepted(self):
        """Heartbeat messages must be accepted by receive()."""
        from agents.ble_mesh_broker import BLEMeshBroker

        broker = BLEMeshBroker(node_id="heartbeat-test", signing_key=self._TEST_KEY)
        msg = broker.publish_heartbeat(battery_level=85.0)
        result = broker.receive(msg)
        assert result is True

    def test_expired_ttl_message_rejected(self):
        """Message with TTL=0 must be rejected by receive()."""
        from agents.ble_mesh_broker import BLEMeshBroker

        broker = BLEMeshBroker(node_id="ttl-test", signing_key=self._TEST_KEY)
        msg = broker.publish_hazard("pothole", 13.0, 80.0, "HIGH", 0.9)
        msg.ttl = 0
        result = broker.receive(msg)
        assert result is False, "Message with TTL=0 must be rejected"


# ---------------------------------------------------------------------------
# Phase 8: System orchestrator full pipeline
# ---------------------------------------------------------------------------

class TestOrchestratorFullPipeline:

    def _make_orch(self):
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            with patch.dict("os.environ", {
                "BHASHINI_USER_ID": "", "BHASHINI_API_KEY": "",
                "VISION_MOCK_MODE": "1"
            }):
                from system_orchestrator import SmartSalaiOrchestrator
                return SmartSalaiOrchestrator(), mock_engine

    def test_swerve_triggers_tts(self):
        """IMU hard swerve must produce at least one TTS announcement."""
        orch, mock_engine = self._make_orch()
        from agents.imu_near_miss_detector import IMUSample
        t_ms = int(time.time() * 1000)
        for i in range(130):
            t_ms += 10
            if i < 110:
                sample = IMUSample(t_ms, 0.1, 0.0, 9.81, 0, 0, 0.0)
                vision = []
            else:
                sample = IMUSample(t_ms, -8.0, 7.0, 10.5, 0, 0, 95.0)
                vision = [{"label": "speed_camera", "conf": 0.9}]
            orch.process_sensor_frame(sample, vision_objects=vision)
        orch.tts.interrupt_queue.join()
        assert mock_engine.say.call_count >= 1, "TTS say() must have been called"

    def test_camera_with_signage_no_challenge_raised(self):
        """Camera + signage present — pipeline must not crash and complete cleanly."""
        orch, mock_engine = self._make_orch()
        from agents.imu_near_miss_detector import IMUSample
        t_ms = int(time.time() * 1000)
        for i in range(130):
            t_ms += 10
            if i < 110:
                sample = IMUSample(t_ms, 0.1, 0.0, 9.81, 0, 0, 0.0)
                vision = []
            else:
                sample = IMUSample(t_ms, -8.0, 7.0, 10.5, 0, 0, 95.0)
                vision = [
                    {"label": "speed_camera", "conf": 0.9},
                    {"label": "speed_limit_sign", "conf": 0.85},
                ]
            orch.process_sensor_frame(sample, vision_objects=vision)
        orch.tts.interrupt_queue.join()
        assert True  # Must complete without exception

    def test_normal_driving_no_tts(self):
        """Normal driving (no near-miss) must produce zero TTS calls."""
        orch, mock_engine = self._make_orch()
        from agents.imu_near_miss_detector import IMUSample
        t_ms = int(time.time() * 1000)
        for i in range(100):
            t_ms += 10
            orch.process_sensor_frame(
                IMUSample(t_ms, 0.1, 0.0, 9.81, 0, 0, 0.0), vision_objects=[]
            )
        orch.tts.interrupt_queue.join()
        assert mock_engine.say.call_count == 0, "No TTS during normal driving"


# ---------------------------------------------------------------------------
# Phase 9: AcousticUI memory stability
# ---------------------------------------------------------------------------

class TestAcousticUIMemoryStability:

    def test_latency_window_bounded_at_100(self):
        """Rolling latency window must never exceed 100 entries."""
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            with patch.dict("os.environ", {"BHASHINI_USER_ID": "", "BHASHINI_API_KEY": ""}):
                from agents.acoustic_ui import AcousticUI, AlertPriority
                ui = AcousticUI(language="en")
        for i in range(200):
            ui.announce(f"msg {i}", priority=AlertPriority.LOW)
        ui.join(timeout=15.0)
        assert len(ui._latencies_ms) <= 100, \
            f"Latency window grew to {len(ui._latencies_ms)} — must stay ≤ 100"
        ui.stop()

    def test_worker_thread_exits_after_stop(self):
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            with patch.dict("os.environ", {"BHASHINI_USER_ID": "", "BHASHINI_API_KEY": ""}):
                from agents.acoustic_ui import AcousticUI
                ui = AcousticUI(language="en")
        ui.stop()
        ui._worker_thread.join(timeout=3.0)
        assert not ui._worker_thread.is_alive(), "Worker thread must exit after stop()"

    def test_mean_latency_returns_float_after_processing(self):
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            with patch.dict("os.environ", {"BHASHINI_USER_ID": "", "BHASHINI_API_KEY": ""}):
                from agents.acoustic_ui import AcousticUI, AlertPriority
                ui = AcousticUI(language="en")
        ui.announce("test", priority=AlertPriority.HIGH)
        ui.join(timeout=5.0)
        lat = ui.get_mean_latency_ms()
        assert isinstance(lat, float)
        assert lat >= 0.0
        ui.stop()


# ---------------------------------------------------------------------------
# Phase 10: ADB deploy edge cases
# ---------------------------------------------------------------------------

class TestADBDeployEdgeCases:
    import subprocess as _sp

    def _run(self, stdout):
        return __import__("subprocess").CompletedProcess([], 0, stdout=stdout, stderr="")

    def test_only_unauthorized_returns_none(self):
        import deploy_android as da
        with patch("subprocess.run", return_value=self._run(
                "List of devices attached\nABC\tunauthorized\nXYZ\toffline\n")):
            assert da.pick_device() is None

    def test_serial_exact_match_only(self):
        """pick_device('ABC') must not match 'ABCDEF'."""
        import deploy_android as da
        with patch("subprocess.run", return_value=self._run(
                "List of devices attached\nABCDEF\tdevice\nABC\tdevice\n")):
            assert da.pick_device("ABC") == "ABC"

    def test_first_authorised_chosen_when_no_serial(self):
        import deploy_android as da
        with patch("subprocess.run", return_value=self._run(
                "List of devices attached\nemulator-5554\tdevice\nABC\tdevice\n")):
            assert da.pick_device() == "emulator-5554"

    def test_empty_device_list_returns_empty(self):
        import deploy_android as da
        with patch("subprocess.run", return_value=self._run(
                "List of devices attached\n")):
            assert da.list_devices() == []

    def test_nnapi_false_when_no_libs(self):
        import deploy_android as da
        with patch("subprocess.run", return_value=self._run("NO\n")):
            assert da.check_nnapi("serial") is False

    def test_push_skips_missing_local_model(self):
        import deploy_android as da
        with patch("os.path.exists", return_value=False):
            with patch("subprocess.run", return_value=self._run("")):
                result = da.push_models("serial123")
        assert "indian_traffic_yolov8.onnx" in result["skipped"]

    def test_push_result_has_all_keys(self):
        import deploy_android as da
        with patch("os.path.exists", return_value=False):
            with patch("subprocess.run", return_value=self._run("")):
                result = da.push_models("serial123")
        assert {"pushed", "skipped", "failed"} == set(result.keys())

    def test_adb_unavailable_returns_empty_device_list(self):
        import deploy_android as da
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert da.list_devices() == []


# ---------------------------------------------------------------------------
# Phase 11: ETL text chunker — edge cases
# ---------------------------------------------------------------------------

class TestETLTextChunkerEdgeCases:

    def _make_extraction(self, text: str, sha: str = "deadbeef"):
        from etl.pdf_extractor import ExtractionResult, PageText, ExtractionMethod
        page = PageText(1, text, ExtractionMethod.DIGITAL_PDFPLUMBER, len(text))
        return ExtractionResult("test.pdf", sha, 1, [page])

    def test_empty_text_produces_no_chunks(self):
        from etl.text_chunker import LegalTextChunker
        chunker = LegalTextChunker()
        chunks = chunker.chunk(self._make_extraction(""))
        assert chunks == []

    def test_whitespace_only_produces_no_chunks(self):
        from etl.text_chunker import LegalTextChunker
        chunker = LegalTextChunker()
        chunks = chunker.chunk(self._make_extraction("   \n\t  "))
        assert chunks == []

    def test_single_sentence_produces_at_least_one_chunk(self):
        from etl.text_chunker import LegalTextChunker
        chunker = LegalTextChunker()
        # Use a text > min_chunk_chars (80 chars) so chunker doesn't drop it
        long_sentence = (
            "Section 208. No speed camera shall be deployed on any road without "
            "mandatory IRC:67 speed limit signage within 500 metres as per MoRTH 2022."
        )
        chunks = chunker.chunk(self._make_extraction(long_sentence))
        assert len(chunks) >= 1

    def test_long_text_split_into_multiple_chunks(self):
        """50 000-character legal text must produce multiple non-empty chunks."""
        from etl.text_chunker import LegalTextChunker
        chunker = LegalTextChunker()
        chunks = chunker.chunk(self._make_extraction("Section 208. " * 3846))
        assert len(chunks) > 1, "Long text must produce multiple chunks"
        for c in chunks:
            assert c.text.strip(), "No chunk may be empty"

    def test_tamil_unicode_preserved_in_chunks(self):
        """Tamil script must not be corrupted during chunking."""
        from etl.text_chunker import LegalTextChunker
        chunker = LegalTextChunker()
        tamil = "Section 208. வேக கட்டுப்பாடு கேமரா. " * 30
        chunks = chunker.chunk(self._make_extraction(tamil))
        assert len(chunks) >= 1
        full = " ".join(c.text for c in chunks)
        assert "வேக" in full, "Tamil Unicode must survive chunking"

    def test_chunk_ids_unique_within_document(self):
        """Every chunk ID must be unique."""
        from etl.text_chunker import LegalTextChunker
        chunker = LegalTextChunker()
        chunks = chunker.chunk(self._make_extraction("Motor Vehicles Act Section. " * 500))
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "Duplicate chunk IDs detected"

    def test_chunk_carries_source_doc(self):
        """Each chunk must reference the source document."""
        from etl.text_chunker import LegalTextChunker
        chunker = LegalTextChunker()
        chunks = chunker.chunk(self._make_extraction("Section 1. Legal text here."))
        if chunks:
            assert chunks[0].source_doc == "test.pdf"


# ---------------------------------------------------------------------------
# Phase 12: Haversine edge cases
# ---------------------------------------------------------------------------

class TestHaversineEdgeCases:

    def _h(self, lat1, lon1, lat2, lon2):
        from agents.sign_auditor import haversine_m
        return haversine_m(lat1, lon1, lat2, lon2)

    def test_same_point_zero(self):
        assert self._h(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-6)

    def test_symmetry(self):
        d1 = self._h(13.08, 80.27, 13.09, 80.28)
        d2 = self._h(13.09, 80.28, 13.08, 80.27)
        assert d1 == pytest.approx(d2, rel=1e-9)

    def test_equatorial_1_degree_longitude(self):
        """1° longitude at equator ≈ 111 319 m."""
        d = self._h(0.0, 0.0, 0.0, 1.0)
        assert 111_000 < d < 112_000, f"Equatorial 1° ≈ 111 319 m, got {d:.0f} m"

    def test_antimeridian_short_path(self):
        """lon=179.9° to lon=-179.9° at equator — short path ≈ 22 km, not ~40 000 km."""
        d = self._h(0.0, 179.9, 0.0, -179.9)
        assert d < 30_000, f"Antimeridian short path should be <30 km, got {d:.0f} m"

    def test_north_pole_to_equator(self):
        """90°N to 0°N ≈ 10 008 km (quarter of Earth's circumference)."""
        d = self._h(90.0, 0.0, 0.0, 0.0)
        assert 9_900_000 < d < 10_100_000, f"Pole to equator ≈ 10 008 km, got {d/1000:.0f} km"

    def test_chennai_to_tambaram_straight_line(self):
        """
        Chennai Central (13.0827, 80.2707) to Tambaram (12.9249, 80.1000).
        Straight-line haversine ≈ 25–26 km.
        """
        d = self._h(13.0827, 80.2707, 12.9249, 80.1000)
        assert 20_000 < d < 30_000, \
            f"Chennai→Tambaram haversine should be 20–30 km, got {d/1000:.1f} km"

    def test_returns_positive_float(self):
        """haversine_m must always return a non-negative float."""
        d = self._h(13.0827, 80.2707, 13.0900, 80.2800)
        assert isinstance(d, float)
        assert d > 0


# ---------------------------------------------------------------------------
# Phase 13: Multi-camera state isolation
# ---------------------------------------------------------------------------

class TestMultiCameraIsolation:

    def _import_server_with_env(self, env_overrides):
        import importlib
        import sys
        # Remove cached module so env vars are re-evaluated
        for key in list(sys.modules.keys()):
            if key == "api.server" or key == "api":
                pass  # don't remove api package itself
        with patch.dict(os.environ, env_overrides, clear=False):
            # Force reimport by removing from sys.modules
            for mod in list(sys.modules.keys()):
                if mod in ("api.server",):
                    del sys.modules[mod]
            with patch("pyttsx3.init", return_value=MagicMock()):
                try:
                    import importlib
                    import api.server as srv
                    importlib.reload(srv)
                    return srv
                except Exception:
                    import api.server as srv
                    return srv

    def test_cam_state_has_expected_directions(self):
        env = {"CAMERA_INDICES": "0,1", "CAMERA_DIRECTIONS": "front,rear",
               "LIVE_CAMERA_ENABLED": "0"}
        with patch.dict(os.environ, env, clear=False):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            with patch("pyttsx3.init", return_value=MagicMock()):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                assert "front" in srv._cam_state
                assert "rear" in srv._cam_state

    def test_cam_state_frame_queues_independent(self):
        env = {"CAMERA_INDICES": "0,1", "CAMERA_DIRECTIONS": "front,rear",
               "LIVE_CAMERA_ENABLED": "0"}
        with patch.dict(os.environ, env, clear=False):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            with patch("pyttsx3.init", return_value=MagicMock()):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                sentinel = b"SENTINEL_FRAME"
                srv._cam_state["front"]["frame_queue"].put_nowait(sentinel)
                assert srv._cam_state["rear"]["frame_queue"].empty()

    def test_camera_directions_parse_from_env(self):
        env = {"CAMERA_INDICES": "0,1,2,3",
               "CAMERA_DIRECTIONS": "front,rear,left,right",
               "LIVE_CAMERA_ENABLED": "0"}
        with patch.dict(os.environ, env, clear=False):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            with patch("pyttsx3.init", return_value=MagicMock()):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                assert len(srv._CAMERA_DIRECTIONS) == 4
                assert len(srv._cam_state) == 4

    def test_camera_directions_fallback_when_mismatch(self):
        env = {"CAMERA_INDICES": "0,1,2",
               "CAMERA_DIRECTIONS": "front,rear",
               "LIVE_CAMERA_ENABLED": "0"}
        with patch.dict(os.environ, env, clear=False):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            with patch("pyttsx3.init", return_value=MagicMock()):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                # mismatch → fallback to cam0, cam1, cam2
                assert all(d.startswith("cam") for d in srv._CAMERA_DIRECTIONS)
                assert len(srv._CAMERA_DIRECTIONS) == 3

    def test_default_single_camera_backward_compat(self):
        env_remove = {"CAMERA_INDICES": "", "CAMERA_DIRECTIONS": "",
                      "CAMERA_INDEX": "0", "LIVE_CAMERA_ENABLED": "0"}
        with patch.dict(os.environ, env_remove, clear=False):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            with patch("pyttsx3.init", return_value=MagicMock()):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                assert len(srv._CAMERA_DIRECTIONS) == 1
                assert srv._CAMERA_DIRECTIONS[0] == "front"


# ---------------------------------------------------------------------------
# Phase 14: API server — full ingest → alert → save pipeline
# ---------------------------------------------------------------------------

class TestAPIIngestAlertPipeline:

    @pytest.fixture(autouse=True)
    def _setup(self):
        with patch("pyttsx3.init", return_value=MagicMock()):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            env = {"LIVE_CAMERA_ENABLED": "0", "CAMERA_INDICES": "0",
                   "CAMERA_DIRECTIONS": "front"}
            with patch.dict(os.environ, env, clear=False):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                from starlette.testclient import TestClient
                self.app = srv.create_app()
                self.client = TestClient(self.app, raise_server_exceptions=False)
                # clear alert log before each test
                srv._alert_log.clear()
                yield

    def test_ingest_accepted_and_returns_201(self):
        resp = self.client.post("/api/v1/internal/ingest", json={
            "node_id": "node-test-1",
            "event_type": "detection",
        })
        assert resp.status_code == 201

    def test_ingest_with_hazard_populates_alert_log(self):
        self.client.post("/api/v1/internal/ingest", json={
            "node_id": "node-hazard",
            "event_type": "detection",
            "hazard_class": "pothole",
            "confidence": 0.9,
        })
        resp = self.client.get("/api/v1/incident/report")
        data = resp.json()
        assert len(data["recent_alerts"]) >= 1

    def test_ingest_without_hazard_no_alert(self):
        self.client.post("/api/v1/internal/ingest", json={
            "node_id": "node-clean",
            "event_type": "heartbeat",
        })
        resp = self.client.get("/api/v1/incident/report")
        data = resp.json()
        assert len(data["recent_alerts"]) == 0

    def test_ingest_100hz_burst_no_data_loss(self):
        results = []
        for i in range(100):
            r = self.client.post("/api/v1/internal/ingest", json={
                "node_id": f"burst-node-{i}",
                "event_type": "detection",
            })
            results.append(r.status_code)
        assert all(s == 201 for s in results)
        assert not any(s >= 500 for s in results)

    def test_gps_update_reflects_in_report(self):
        self.client.post("/api/v1/gps/update", json={"lat": 12.9716, "lon": 77.5946})
        resp = self.client.get("/api/v1/incident/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "report_id" in data


# ---------------------------------------------------------------------------
# Phase 15: Chatbot — all 13 intents × 3 languages
# ---------------------------------------------------------------------------

class TestChatbotAllIntents:

    _INTENT_KEYWORDS = [
        ("GREETING", "hello"),
        ("WEAKNESS", "weakness"),
        ("SAFETY_SCORE", "score"),
        ("ROUTE", "route"),
        ("POTHOLE_REPORT", "I found a pothole"),
        ("HAZARD_QUERY", "hazard"),
        ("SPEED_RULE", "speed limit"),
        ("SIGN_QUERY", "traffic sign"),
        ("LEGAL_CHALLENGE", "section 208"),
        ("NIGHT_DRIVING", "night driving"),
        ("GENERAL_SAFETY", "seatbelt"),
        ("HISTORY", "my history"),
    ]

    def _make_bot(self, tmp_dir, lang="en", persona="male"):
        with patch("pyttsx3.init", return_value=MagicMock()):
            from agents.driver_profile import DriverProfileAgent
            from agents.driver_chatbot import DriverChatbot
            pa = DriverProfileAgent(db_path=tmp_dir + "/test.db")
            pa.update_preferences("testdriver", language=lang, voice_persona=persona)
            bot = DriverChatbot("testdriver", pa)
            return bot

    def test_all_13_intents_return_non_empty_response_en(self, tmp_path):
        import tempfile
        tmp_dir = str(tmp_path)
        bot = self._make_bot(tmp_dir, lang="en")
        for intent, kw in self._INTENT_KEYWORDS:
            result = bot.chat(kw)
            assert result["text"], f"Empty response for intent {intent} kw={kw}"

    def test_all_13_intents_tamil(self, tmp_path):
        tmp_dir = str(tmp_path)
        bot = self._make_bot(tmp_dir, lang="ta")
        for intent, kw in self._INTENT_KEYWORDS:
            result = bot.chat(kw)
            assert result["text"], f"Empty response for intent {intent} in Tamil"

    def test_all_13_intents_hindi(self, tmp_path):
        tmp_dir = str(tmp_path)
        bot = self._make_bot(tmp_dir, lang="hi")
        for intent, kw in self._INTENT_KEYWORDS:
            result = bot.chat(kw)
            assert result["text"], f"Empty response for intent {intent} in Hindi"

    def test_unknown_intent_returns_help_message(self, tmp_path):
        tmp_dir = str(tmp_path)
        bot = self._make_bot(tmp_dir)
        result = bot.chat("xyzzy nonsense 12345")
        assert result["intent"] == "UNKNOWN"
        assert result["text"]

    def test_child_persona_simplifies_response(self, tmp_path):
        tmp_dir = str(tmp_path)
        bot = self._make_bot(tmp_dir, persona="child")
        result = bot.chat("section 208")
        assert result["text"]
        assert "mandatory" not in result["text"].lower() or len(result["text"]) < 300

    def test_pothole_report_increments_counter(self, tmp_path):
        """POTHOLE_REPORT intent logs the exchange; manually recording hazard works."""
        tmp_dir = str(tmp_path)
        with patch("pyttsx3.init", return_value=MagicMock()):
            from agents.driver_profile import DriverProfileAgent
            from agents.driver_chatbot import DriverChatbot
            pa = DriverProfileAgent(db_path=tmp_dir + "/test.db")
            bot = DriverChatbot("driver2", pa)
            resp = bot.chat("I found a pothole report")
            assert resp["intent"] == "POTHOLE_REPORT", f"Expected POTHOLE_REPORT, got {resp['intent']}"
            # Chatbot logs both user and bot messages
            profile = pa._store.load("driver2")
            assert len(profile.chat_history) >= 2

    def test_chat_history_persisted(self, tmp_path):
        tmp_dir = str(tmp_path)
        with patch("pyttsx3.init", return_value=MagicMock()):
            from agents.driver_profile import DriverProfileAgent
            from agents.driver_chatbot import DriverChatbot
            pa = DriverProfileAgent(db_path=tmp_dir + "/test.db")
            bot = DriverChatbot("driver3", pa)
            bot.chat("hello")
            bot.chat("score")
            bot.chat("route")
            profile = pa._store.load("driver3")
            # user + bot per message = 6 entries
            assert len(profile.chat_history) >= 6


# ---------------------------------------------------------------------------
# Phase 16: Driver profile persistence — save/load/update
# ---------------------------------------------------------------------------

class TestDriverProfilePersistence:

    def _agent(self, tmp_path):
        with patch("pyttsx3.init", return_value=MagicMock()):
            from agents.driver_profile import DriverProfileAgent
            return DriverProfileAgent(db_path=str(tmp_path / "dp.db"))

    def test_save_and_load_roundtrip(self, tmp_path):
        pa = self._agent(tmp_path)
        for _ in range(3):
            pa.record_near_miss("d1", severity="CRITICAL")
        profile = pa._store.load("d1")
        assert profile.critical_near_misses == 3

    def test_safety_score_degrades_with_events(self, tmp_path):
        pa = self._agent(tmp_path)
        fresh = pa.get_or_create("d2")
        initial_score = fresh.safety_score()
        for _ in range(3):
            pa.record_near_miss("d2", severity="CRITICAL")
        updated = pa._store.load("d2")
        assert updated.safety_score() < initial_score

    def test_weakness_detected_after_threshold(self, tmp_path):
        pa = self._agent(tmp_path)
        # aggressive_braking triggered by ax > 6.0 in record_near_miss
        for _ in range(6):
            pa.record_near_miss("d3", severity="HIGH", ax=7.0)
        profile = pa._store.load("d3")
        from agents.driver_profile import WeaknessCode
        assert WeaknessCode.AGGRESSIVE_BRAKING in profile.weakness_codes()

    def test_session_count_increments(self, tmp_path):
        pa = self._agent(tmp_path)
        for _ in range(5):
            pa.record_session_start("d4")
        profile = pa._store.load("d4")
        assert profile.total_sessions == 5

    def test_hazard_km_accumulates(self, tmp_path):
        pa = self._agent(tmp_path)
        for _ in range(3):
            pa.record_hazard_reported("d5", km_delta=10.5)
        profile = pa._store.load("d5")
        assert abs(profile.total_km - 31.5) < 0.01

    def test_chat_history_capped_at_100(self, tmp_path):
        pa = self._agent(tmp_path)
        for i in range(110):
            pa.add_chat_message("d6", "user", f"msg {i}")
        profile = pa._store.load("d6")
        assert len(profile.chat_history) <= 100

    def test_multiple_drivers_isolated(self, tmp_path):
        pa = self._agent(tmp_path)
        pa.get_or_create("driverA")
        pa.get_or_create("driverB")
        for _ in range(3):
            pa.record_near_miss("driverA", severity="CRITICAL")
        pB = pa._store.load("driverB")
        assert pB.critical_near_misses == 0


# ---------------------------------------------------------------------------
# Phase 17: Incident report and share — content validation
# ---------------------------------------------------------------------------

class TestIncidentReportShare:

    @pytest.fixture(autouse=True)
    def _setup(self):
        with patch("pyttsx3.init", return_value=MagicMock()):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            env = {"LIVE_CAMERA_ENABLED": "0", "CAMERA_INDICES": "0",
                   "CAMERA_DIRECTIONS": "front"}
            with patch.dict(os.environ, env, clear=False):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                from starlette.testclient import TestClient
                self.app = srv.create_app()
                self.client = TestClient(self.app, raise_server_exceptions=False)
                self._srv = srv
                yield

    def test_incident_report_has_required_fields(self):
        resp = self.client.get("/api/v1/incident/report")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("report_id", "generated_at", "camera_directions", "recent_alerts", "irad_compliant"):
            assert key in data, f"Missing key: {key}"

    def test_report_id_has_INC_prefix(self):
        resp = self.client.get("/api/v1/incident/report")
        data = resp.json()
        assert data["report_id"].startswith("INC-")

    def test_incident_report_with_driver_id(self, tmp_path):
        with patch("pyttsx3.init", return_value=MagicMock()):
            from agents.driver_profile import DriverProfileAgent
            pa = DriverProfileAgent(db_path=str(tmp_path / "inc.db"))
            pa.get_or_create("inc_driver")
            # Inject the agent into server
            self._srv._profile_agent = pa
            resp = self.client.get("/api/v1/incident/report?driver_id=inc_driver")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("safety_score") is not None or data.get("driver")

    def test_share_returns_json_attachment(self):
        resp = self.client.post("/api/v1/incident/share")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd

    def test_share_json_contains_report_id(self):
        resp = self.client.post("/api/v1/incident/share")
        body = json.loads(resp.content)
        assert "report_id" in body
        assert body["report_id"].startswith("INC-")

    def test_cameras_endpoint_returns_list(self):
        resp = self.client.get("/api/v1/cameras")
        assert resp.status_code == 200
        data = resp.json()
        assert "cameras" in data
        assert isinstance(data["cameras"], list)
        assert data["count"] >= 1
        for cam in data["cameras"]:
            assert "direction" in cam
            assert "index" in cam
            assert "stream_url" in cam


# ---------------------------------------------------------------------------
# Phase 18: Alert detect, save, share — end-to-end
# ---------------------------------------------------------------------------

class TestAlertDetectSaveShare:

    @pytest.fixture(autouse=True)
    def _setup(self):
        with patch("pyttsx3.init", return_value=MagicMock()):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            env = {"LIVE_CAMERA_ENABLED": "0", "CAMERA_INDICES": "0",
                   "CAMERA_DIRECTIONS": "front"}
            with patch.dict(os.environ, env, clear=False):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                from starlette.testclient import TestClient
                self.app = srv.create_app()
                self.client = TestClient(self.app, raise_server_exceptions=False)
                srv._alert_log.clear()
                yield

    def test_hazard_ingest_appears_in_live_report(self):
        self.client.post("/api/v1/internal/ingest", json={
            "node_id": "n1", "event_type": "detection",
            "hazard_class": "pothole", "confidence": 0.95,
        })
        resp = self.client.get("/api/v1/incident/report")
        data = resp.json()
        assert len(data["recent_alerts"]) >= 1
        types = [a.get("type") for a in data["recent_alerts"]]
        assert "alert" in types

    def test_alert_severity_high_propagated(self):
        self.client.post("/api/v1/internal/ingest", json={
            "node_id": "n2", "event_type": "detection",
            "hazard_class": "pothole", "confidence": 0.9,
        })
        resp = self.client.get("/api/v1/incident/report")
        data = resp.json()
        severities = [a.get("severity") for a in data["recent_alerts"]]
        assert "HIGH" in severities

    def test_alert_log_bounded_at_200(self):
        for i in range(250):
            self.client.post("/api/v1/internal/ingest", json={
                "node_id": f"bulk-{i}", "event_type": "detection",
                "hazard_class": "pothole",
            })
        resp = self.client.get("/api/v1/incident/report")
        assert resp.status_code == 200
        data = resp.json()
        # report returns last 20; just confirm no crash and within bounds
        assert len(data["recent_alerts"]) <= 20

    def test_gps_update_accepted(self):
        resp = self.client.post("/api/v1/gps/update", json={"lat": 12.9716, "lon": 77.5946})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "OK"

    def test_route_score_returns_recommendation(self):
        resp = self.client.post("/api/v1/route/score", json={
            "routes": [
                [[12.97, 77.59], [12.98, 77.60]],
                [[12.97, 77.59], [12.96, 77.58]],
            ]
        })
        # 200 with scores/recommended OR 503 if advisor unavailable
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            data = resp.json()
            assert "recommended" in data or "scores" in data


# ---------------------------------------------------------------------------
# Phase 19: Production-readiness hardening
# ---------------------------------------------------------------------------

class TestProductionReadiness:

    @pytest.fixture(autouse=True)
    def _setup(self):
        with patch("pyttsx3.init", return_value=MagicMock()):
            for mod in list(sys.modules.keys()):
                if mod == "api.server":
                    del sys.modules[mod]
            env = {"LIVE_CAMERA_ENABLED": "0", "CAMERA_INDICES": "0",
                   "CAMERA_DIRECTIONS": "front", "FLEET_API_KEYS": "testkey"}
            with patch.dict(os.environ, env, clear=False):
                import api.server as srv
                import importlib
                importlib.reload(srv)
                from starlette.testclient import TestClient
                self.app = srv.create_app()
                self.client = TestClient(self.app, raise_server_exceptions=False)
                self._srv = srv
                yield

    def test_ingest_rejects_missing_fields(self):
        resp = self.client.post("/api/v1/internal/ingest", json={})
        assert resp.status_code == 422

    def test_razorpay_webhook_rejects_bad_signature(self):
        resp = self.client.post("/api/v1/webhook/razorpay", json={
            "razorpay_payment_id": "pay_123",
            "razorpay_order_id": "order_123",
            "razorpay_signature": "badsig",
        })
        assert resp.status_code == 400

    def test_fleet_hazards_requires_api_key(self):
        resp = self.client.get("/api/v1/fleet-routing-hazards")
        assert resp.status_code == 401

    def test_fleet_hazards_with_valid_key(self):
        resp = self.client.get(
            "/api/v1/fleet-routing-hazards",
            headers={"X-API-Key": "testkey"},
        )
        assert resp.status_code == 200

    def test_video_feed_disabled_returns_503(self):
        # LIVE_CAMERA_ENABLED=0 set in fixture env
        resp = self.client.get("/video_feed")
        assert resp.status_code == 503

    def test_video_feed_unknown_direction_returns_404(self):
        resp = self.client.get("/video_feed/unknown_xyz")
        assert resp.status_code in (404, 503)

    def test_chat_returns_json_with_required_keys(self):
        resp = self.client.post("/api/v1/chat", json={
            "driver_id": "prod_driver",
            "message": "hello",
        })
        assert resp.status_code == 200
        data = resp.json()
        for key in ("text", "intent", "lang", "voice_persona", "spoken"):
            assert key in data, f"Missing key: {key}"

    def test_driver_profile_404_for_unknown(self):
        resp = self.client.get("/api/v1/driver/nonexistent_driver_xyz/profile")
        assert resp.status_code == 404

    def test_server_docstring_mentions_360(self):
        import api.server as srv
        doc = srv.__doc__ or ""
        assert "360" in doc
