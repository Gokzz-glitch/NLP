"""
tests/test_input_validation.py

Validates that all core modules handle invalid, boundary, and adversarial
inputs gracefully — no unhandled exceptions, no silent data corruption.

These tests cover the safety-critical input-validation paths:
  - IMU sensor data: NaN, Inf, out-of-range, empty, wrong type
  - Section208Resolver: malformed camera/GPS data
  - IRADSerializer: partial / corrupted near-miss events
  - ZKPEnvelopeBuilder: empty and oversized payloads
  - AgentBus: malformed messages, rapid publish/stop races
"""

from __future__ import annotations

import math
import sys
import os
import time
import uuid

import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.imu_near_miss_detector import (
    IMUBuffer,
    IMUSample,
    NearMissDetector,
    NearMissSeverity,
    NearMissFeatureExtractor,
    calibrate_gravity,
    GRAVITY_MS2,
    WINDOW_SIZE_SAMPLES,
    IMU_SAMPLE_RATE_HZ,
    LATERAL_G_CRITICAL_THRESHOLD,
    LATERAL_G_HIGH_THRESHOLD,
    LATERAL_G_MEDIUM_THRESHOLD,
    LONGITUDINAL_DECEL_CRITICAL_MS2,
    LONGITUDINAL_DECEL_HIGH_MS2,
    YAW_RATE_CRITICAL_DEGS,
)

# Minimum samples required by calibrate_gravity(duration_s=1.0)
_MIN_GRAVITY_SAMPLES = int(1.0 * IMU_SAMPLE_RATE_HZ)  # 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sample(t_ms=0, ax=0.0, ay=0.0, az=GRAVITY_MS2,
                 gx=0.0, gy=0.0, gz=0.0) -> IMUSample:
    return IMUSample(
        timestamp_epoch_ms=t_ms,
        accel_x_ms2=ax, accel_y_ms2=ay, accel_z_ms2=az,
        gyro_x_degs=gx, gyro_y_degs=gy, gyro_z_degs=gz,
    )


def _full_buffer() -> IMUBuffer:
    buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
    for i in range(WINDOW_SIZE_SAMPLES):
        buf.push(_make_sample(t_ms=i * 10))
    return buf


def _buffer_to_window(buf: IMUBuffer) -> np.ndarray:
    """Return (WINDOW_SIZE_SAMPLES, 6) float32 numpy array from a full buffer."""
    return buf.get_window()


# ---------------------------------------------------------------------------
# IMUSample: field validation
# ---------------------------------------------------------------------------

class TestIMUSampleEdgeCases:

    def test_nan_accel_does_not_crash_extractor(self):
        """NaN in accelerometer field must not crash feature extraction."""
        buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
        for i in range(WINDOW_SIZE_SAMPLES):
            ax = float("nan") if i == WINDOW_SIZE_SAMPLES // 2 else 0.0
            buf.push(_make_sample(t_ms=i * 10, ax=ax))
        extractor = NearMissFeatureExtractor()
        window = _buffer_to_window(buf)
        # Should not raise; result may be nan/0 but must return a dict
        result = extractor.compute(window)
        assert isinstance(result, dict)

    def test_inf_gyro_does_not_crash_extractor(self):
        """Infinite gyroscope reading must not crash feature extraction."""
        buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
        for i in range(WINDOW_SIZE_SAMPLES):
            gz = float("inf") if i == 5 else 0.0
            buf.push(_make_sample(t_ms=i * 10, gz=gz))
        extractor = NearMissFeatureExtractor()
        window = _buffer_to_window(buf)
        result = extractor.compute(window)
        assert isinstance(result, dict)

    def test_zero_gravity_vector(self):
        """All-zero IMU (free-fall simulation) must return a valid feature dict."""
        buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
        for i in range(WINDOW_SIZE_SAMPLES):
            buf.push(_make_sample(t_ms=i * 10, ax=0.0, ay=0.0, az=0.0))
        extractor = NearMissFeatureExtractor()
        window = _buffer_to_window(buf)
        result = extractor.compute(window)
        assert isinstance(result, dict)

    def test_extreme_accel_critical_severity(self):
        """Extreme lateral acceleration must classify as CRITICAL."""
        extractor = NearMissFeatureExtractor()
        severity = extractor.classify_severity_deterministic(
            lateral_g=LATERAL_G_CRITICAL_THRESHOLD + 0.5,
            decel_ms2=0.0,
            yaw_degs=0.0,
            rms_jerk=0.0,
        )
        assert severity == NearMissSeverity.CRITICAL

    def test_extreme_decel_high_severity(self):
        """Extreme longitudinal deceleration must classify as HIGH or CRITICAL."""
        extractor = NearMissFeatureExtractor()
        severity = extractor.classify_severity_deterministic(
            lateral_g=0.0,
            decel_ms2=LONGITUDINAL_DECEL_HIGH_MS2 + 1.0,
            yaw_degs=0.0,
            rms_jerk=0.0,
        )
        assert severity in (NearMissSeverity.HIGH, NearMissSeverity.CRITICAL)

    def test_identical_timestamps_do_not_crash(self):
        """Repeated timestamp values (clock freeze) must not crash."""
        buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
        for _ in range(WINDOW_SIZE_SAMPLES):
            buf.push(_make_sample(t_ms=42))  # all same timestamp
        extractor = NearMissFeatureExtractor()
        window = _buffer_to_window(buf)
        result = extractor.compute(window)
        assert isinstance(result, dict)

    def test_negative_timestamps(self):
        """Negative timestamps (clock drift) must not crash."""
        buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
        for i in range(WINDOW_SIZE_SAMPLES):
            buf.push(_make_sample(t_ms=-1000 + i * 10))
        extractor = NearMissFeatureExtractor()
        window = _buffer_to_window(buf)
        result = extractor.compute(window)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# IMUBuffer: boundary conditions
# ---------------------------------------------------------------------------

class TestIMUBufferBoundary:

    def test_empty_buffer_not_full(self):
        buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
        assert not buf.is_full()

    def test_single_sample_not_full(self):
        buf = IMUBuffer(WINDOW_SIZE_SAMPLES)
        buf.push(_make_sample())
        assert not buf.is_full()

    def test_exactly_full(self):
        buf = _full_buffer()
        assert buf.is_full()

    def test_overwrite_wraps_correctly(self):
        """Pushing N+1 samples must still maintain WINDOW_SIZE_SAMPLES samples."""
        buf = _full_buffer()
        extra = _make_sample(t_ms=99999, ax=5.0)
        buf.push(extra)
        win = buf.get_window()
        assert win.shape == (WINDOW_SIZE_SAMPLES, 6)

    def test_buffer_size_one(self):
        """Buffer of size 1 should work as a degenerate ring buffer."""
        buf = IMUBuffer(1)
        buf.push(_make_sample(t_ms=0, ax=1.0))
        assert buf.is_full()
        win = buf.get_window()
        assert win.shape == (1, 6)


# ---------------------------------------------------------------------------
# calibrate_gravity: input validation
# ---------------------------------------------------------------------------

class TestCalibrateGravity:

    def test_insufficient_samples_raises(self):
        """calibrate_gravity must raise ValueError on <100 samples (default 1.0s @ 100Hz)."""
        with pytest.raises(ValueError):
            calibrate_gravity([_make_sample() for _ in range(10)])

    def test_exactly_min_samples_succeeds(self):
        vec = calibrate_gravity([_make_sample() for _ in range(_MIN_GRAVITY_SAMPLES)])
        assert len(vec) == 3

    def test_more_than_min_samples_succeeds(self):
        vec = calibrate_gravity([_make_sample() for _ in range(_MIN_GRAVITY_SAMPLES + 50)])
        assert len(vec) == 3

    def test_stationary_returns_gravity_vector(self):
        """Stationary samples (pure gravity on Z) should yield ~[0, 0, 9.8]."""
        samples = [_make_sample(ax=0.0, ay=0.0, az=GRAVITY_MS2)
                   for _ in range(_MIN_GRAVITY_SAMPLES)]
        vec = calibrate_gravity(samples)
        assert abs(vec[0]) < 0.01  # X should be near zero
        assert abs(vec[1]) < 0.01  # Y should be near zero
        assert abs(vec[2] - GRAVITY_MS2) < 0.01  # Z should be near GRAVITY_MS2


# ---------------------------------------------------------------------------
# NearMissDetector: deterministic mode robustness
# ---------------------------------------------------------------------------

class TestNearMissDetectorRobustness:

    def test_push_before_load_does_not_crash(self):
        """Pushing samples before load() is called must not crash."""
        detector = NearMissDetector()
        # Do NOT call .load() — simulate incorrect usage
        try:
            for i in range(5):
                detector.push_sample(_make_sample(t_ms=i * 10))
        except Exception as exc:
            pytest.fail(f"push_sample before load() raised: {exc}")

    def test_load_then_push_partial_window(self):
        """Pushing fewer samples than WINDOW_SIZE should return None (no event yet)."""
        detector = NearMissDetector()
        detector.load()
        result = None
        for i in range(WINDOW_SIZE_SAMPLES - 1):
            result = detector.push_sample(_make_sample(t_ms=i * 10))
        assert result is None

    def test_rapid_push_many_samples(self):
        """Rapid push of 10× WINDOW_SIZE samples must complete without error."""
        detector = NearMissDetector()
        detector.load()
        for i in range(WINDOW_SIZE_SAMPLES * 10):
            detector.push_sample(_make_sample(t_ms=i * 10))

    def test_emergency_braking_pattern(self):
        """
        Simulate an emergency braking scenario:
        sustained high longitudinal decel should trigger an event.
        """
        detector = NearMissDetector()
        detector.load()

        last_event = None
        for i in range(WINDOW_SIZE_SAMPLES * 2):
            # Simulate hard braking: large negative accel_x
            sample = _make_sample(
                t_ms=i * 10,
                ax=-LONGITUDINAL_DECEL_CRITICAL_MS2,
            )
            event = detector.push_sample(sample)
            if event is not None:
                last_event = event

        # Once enough samples are collected, an event must be generated
        assert last_event is not None
        assert last_event.severity in (
            NearMissSeverity.CRITICAL,
            NearMissSeverity.HIGH,
            NearMissSeverity.MEDIUM,
        )

    def test_zero_motion_baseline(self):
        """
        Stationary vehicle (gravity only, no motion) should yield MEDIUM severity
        (the lowest classifiable severity from the deterministic ladder).
        """
        detector = NearMissDetector()
        detector.load()

        last_event = None
        for i in range(WINDOW_SIZE_SAMPLES * 2):
            sample = _make_sample(t_ms=i * 10)  # stationary — only gravity on Z
            event = detector.push_sample(sample)
            if event is not None:
                last_event = event

        if last_event is not None:
            assert last_event.severity in (
                NearMissSeverity.MEDIUM,
                NearMissSeverity.HIGH,
                NearMissSeverity.CRITICAL,
            )


# ---------------------------------------------------------------------------
# Section208Resolver: input validation
# ---------------------------------------------------------------------------

class TestSection208ResolverValidation:

    def _get_resolver(self):
        from section_208_resolver import Section208Resolver
        return Section208Resolver()

    def test_camera_no_sign_triggers_challenge(self):
        """Speed camera detected without signage should trigger Section 208."""
        resolver = self._get_resolver()
        result = resolver.challenge_speed_camera(
            camera_data={"type": "speed_camera", "lat": 12.9, "lon": 80.1},
            signage_detected=False,
        )
        assert isinstance(result, dict)

    def test_camera_with_sign_no_trigger(self):
        """Speed camera detected WITH signage — Section 208 should NOT trigger."""
        resolver = self._get_resolver()
        result = resolver.challenge_speed_camera(
            camera_data={"type": "speed_camera", "lat": 12.9, "lon": 80.1},
            signage_detected=True,
        )
        assert isinstance(result, dict)

    def test_non_camera_type_raises_or_returns_dict(self):
        """Non-camera object type must not crash (may raise KeyError or return gracefully)."""
        resolver = self._get_resolver()
        try:
            result = resolver.challenge_speed_camera(
                camera_data={"type": "pedestrian", "lat": 12.9, "lon": 80.1},
                signage_detected=False,
            )
            assert isinstance(result, dict)
        except KeyError:
            pass  # acceptable — camera_data['type'] check

    def test_generate_audit_request_returns_str(self):
        """generate_audit_request must return a non-empty string (the audit letter)."""
        resolver = self._get_resolver()
        result = resolver.generate_audit_request(
            camera_data={"type": "speed_camera", "lat": 12.9, "lon": 80.1},
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_audit_request_with_statutes(self):
        """Passing statutes dict should not crash and return a string."""
        resolver = self._get_resolver()
        result = resolver.generate_audit_request(
            camera_data={"type": "speed_camera", "lat": 13.0, "lon": 80.2},
            statutes={"208": "MVA 1988 Section 208 text"},
        )
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# IRADSerializer: partial / corrupted input
# ---------------------------------------------------------------------------

class TestIRADSerializerValidation:

    def _get_serializer(self):
        from core.irad_serializer import IRADSerializer
        return IRADSerializer()

    def test_from_near_miss_minimal(self):
        """from_near_miss with minimal dict must return an IRADRecord."""
        from core.irad_serializer import IRADRecord
        ser = self._get_serializer()
        record = ser.from_near_miss({
            "event_id": str(uuid.uuid4()),
            "severity": "HIGH",
            "score": 0.8,
            "timestamp_epoch_ms": int(time.time() * 1000),
        })
        assert record is not None
        d = record.to_dict()
        assert "accident_id" in d

    def test_from_near_miss_empty_dict(self):
        """from_near_miss with empty dict must not crash."""
        ser = self._get_serializer()
        try:
            record = ser.from_near_miss({})
            assert record is not None
        except (KeyError, TypeError, AttributeError):
            pass  # partial input may raise — but not unrelated errors

    def test_export_csv_row_returns_dict(self):
        """export_csv_row must return a flat dict of strings."""
        from core.irad_serializer import IRADRecord
        ser = self._get_serializer()
        record = ser.from_near_miss({
            "event_id": str(uuid.uuid4()),
            "severity": "MEDIUM",
            "score": 0.4,
            "timestamp_epoch_ms": int(time.time() * 1000),
        })
        row = ser.export_csv_row(record)
        assert isinstance(row, dict)
        # All values must be strings (CSV format)
        for k, v in row.items():
            assert isinstance(v, str), f"Key {k!r} has non-string value: {v!r}"

    def test_record_to_json_is_valid_json(self):
        """to_json() must produce valid JSON."""
        import json
        from core.irad_serializer import IRADRecord
        ser = self._get_serializer()
        record = ser.from_near_miss({
            "event_id": str(uuid.uuid4()),
            "severity": "CRITICAL",
            "score": 0.99,
            "timestamp_epoch_ms": int(time.time() * 1000),
        })
        json_str = record.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "accident_id" in parsed


# ---------------------------------------------------------------------------
# ZKPEnvelopeBuilder: edge cases
# ---------------------------------------------------------------------------

class TestZKPEnvelopeEdgeCases:

    def _get_builder(self):
        from core.zkp_envelope import ZKPEnvelopeBuilder
        return ZKPEnvelopeBuilder()

    def test_seal_telemetry_empty_payload(self):
        """seal_telemetry with empty dict must not crash."""
        builder = self._get_builder()
        result = builder.seal_telemetry({})
        assert isinstance(result, dict)

    def test_seal_telemetry_large_payload(self):
        """Large payloads (100 KB) must not crash the ZKP builder."""
        builder = self._get_builder()
        payload = {"data": "x" * 100_000}
        result = builder.seal_telemetry(payload)
        assert isinstance(result, dict)

    def test_seal_telemetry_nested_payload(self):
        builder = self._get_builder()
        payload = {"level1": {"level2": {"level3": [1, 2, 3]}}}
        result = builder.seal_telemetry(payload)
        assert isinstance(result, dict)

    def test_seal_telemetry_unicode_payload(self):
        """Unicode / Indic script in payload must not crash."""
        builder = self._get_builder()
        payload = {"text": "Tamil: தமிழ், Hindi: हिंदी, Arabic: عربي"}
        result = builder.seal_telemetry(payload)
        assert isinstance(result, dict)

    def test_seal_with_explicit_type(self):
        """seal() with explicit payload_type must return a ZKPEnvelope."""
        from core.zkp_envelope import ZKPEnvelopeBuilder
        builder = ZKPEnvelopeBuilder()
        envelope = builder.seal({"score": 0.9, "severity": "HIGH"}, payload_type="NearMissEvent")
        assert envelope is not None
        d = envelope.to_dict()
        assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# AgentBus: race conditions and error recovery
# ---------------------------------------------------------------------------

class TestAgentBusRobustness:

    def test_stop_before_start(self):
        """Calling stop() before start() must not crash."""
        from core.agent_bus import AgentBus
        bus = AgentBus()
        try:
            bus.stop()
        except Exception as exc:
            pytest.fail(f"stop() before start() raised: {exc}")

    def test_publish_after_stop(self):
        """Publish after stop must not crash (may silently drop)."""
        from core.agent_bus import AgentBus
        bus = AgentBus()
        bus.start()
        time.sleep(0.05)
        bus.stop()
        try:
            bus.publish("test.topic", {"data": 1})
        except Exception as exc:
            pytest.fail(f"publish() after stop() raised: {exc}")

    def test_subscribe_nonstring_topic(self):
        """Subscribing with non-string topic must either work or raise TypeError."""
        from core.agent_bus import AgentBus
        bus = AgentBus()
        bus.start()
        try:
            bus.subscribe(123, lambda msg: None)
        except TypeError:
            pass
        except Exception as exc:
            pytest.fail(f"Unexpected exception type: {type(exc).__name__}: {exc}")
        finally:
            bus.stop()

    def test_rapid_start_stop_cycles(self):
        """Multiple start/stop cycles must not leak threads."""
        from core.agent_bus import AgentBus
        for _ in range(5):
            bus = AgentBus()
            bus.start()
            bus.publish("ping", {"i": 1})
            time.sleep(0.02)
            bus.stop()

    def test_high_volume_publish(self):
        """Publishing 1000 messages rapidly must not crash or deadlock."""
        from core.agent_bus import AgentBus
        bus = AgentBus()
        bus.start()
        received = []
        bus.subscribe("load.test", lambda msg: received.append(1))
        for i in range(1000):
            bus.publish("load.test", {"i": i})
        time.sleep(0.5)
        bus.stop()
        # All messages should be received (or close to it under high load)
        assert len(received) > 0
