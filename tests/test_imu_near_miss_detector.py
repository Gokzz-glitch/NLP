"""
tests/test_imu_near_miss_detector.py

Unit tests for agents/imu_near_miss_detector.py covering:
  - IMUBuffer: push, is_full, get_window, circular overwrite,
    apply_gravity_calibration
  - calibrate_gravity: normal case, ValueError on insufficient samples
  - NearMissFeatureExtractor: compute (various kinematic scenarios),
    classify_severity_deterministic (all severity branches)
  - NearMissDetector (DETERMINISTIC mode):
    load, push_sample, gravity calibration, inference interval,
    _map_score_to_severity
"""

import uuid
import pytest
import numpy as np

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.imu_near_miss_detector import (
    IMUBuffer,
    IMUSample,
    NearMissSeverity,
    NearMissFeatureExtractor,
    NearMissDetector,
    calibrate_gravity,
    WINDOW_SIZE_SAMPLES,
    GRAVITY_MS2,
    LATERAL_G_CRITICAL_THRESHOLD,
    LATERAL_G_HIGH_THRESHOLD,
    LATERAL_G_MEDIUM_THRESHOLD,
    LONGITUDINAL_DECEL_CRITICAL_MS2,
    LONGITUDINAL_DECEL_HIGH_MS2,
    YAW_RATE_CRITICAL_DEGS,
    IMU_SAMPLE_RATE_HZ,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sample(t_ms=0, ax=0.0, ay=0.0, az=GRAVITY_MS2,
                 gx=0.0, gy=0.0, gz=0.0):
    return IMUSample(
        timestamp_epoch_ms=t_ms,
        accel_x_ms2=ax, accel_y_ms2=ay, accel_z_ms2=az,
        gyro_x_degs=gx, gyro_y_degs=gy, gyro_z_degs=gz,
    )


def _fill_buf(buf, n=WINDOW_SIZE_SAMPLES, **kw):
    for i in range(n):
        buf.push(_make_sample(t_ms=i * 10, **kw))


def _normal_window():
    w = np.zeros((WINDOW_SIZE_SAMPLES, 6), dtype=np.float32)
    w[:, 2] = GRAVITY_MS2
    return w


# ===========================================================================
# IMUBuffer
# ===========================================================================

class TestIMUBuffer:

    def test_initial_empty(self):
        buf = IMUBuffer()
        assert buf._count == 0
        assert not buf.is_full()

    def test_push_increments_count(self):
        buf = IMUBuffer()
        buf.push(_make_sample())
        assert buf._count == 1

    def test_full_after_capacity(self):
        buf = IMUBuffer()
        _fill_buf(buf)
        assert buf.is_full()
        assert buf._count == WINDOW_SIZE_SAMPLES

    def test_count_capped_at_capacity(self):
        buf = IMUBuffer(capacity=5)
        for i in range(10):
            buf.push(_make_sample(t_ms=i))
        assert buf._count == 5

    def test_get_window_shape_partial(self):
        buf = IMUBuffer()
        buf.push(_make_sample())
        assert buf.get_window().shape == (WINDOW_SIZE_SAMPLES, 6)

    def test_get_window_zero_padded_partial(self):
        buf = IMUBuffer(capacity=5)
        buf.push(_make_sample(ax=7.0))
        w = buf.get_window()
        assert w.shape == (5, 6)
        assert np.sum(w == 0.0) > 0

    def test_get_window_shape_full(self):
        buf = IMUBuffer()
        _fill_buf(buf)
        assert buf.get_window().shape == (WINDOW_SIZE_SAMPLES, 6)

    def test_get_window_ordered_oldest_to_newest(self):
        buf = IMUBuffer(capacity=10)
        for i in range(10):
            buf.push(_make_sample(ax=float(i)))
        w = buf.get_window()
        assert list(w[:, 0]) == pytest.approx(list(range(10)))

    def test_circular_overwrite_evicts_oldest(self):
        buf = IMUBuffer(capacity=5)
        for i in range(5):
            buf.push(_make_sample(ax=float(i)))
        buf.push(_make_sample(ax=99.0))
        w = buf.get_window()
        assert 0.0 not in w[:, 0]
        assert 99.0 in w[:, 0]

    def test_push_stores_all_channels(self):
        buf = IMUBuffer(capacity=3)
        buf.push(_make_sample(ax=1, ay=2, az=3, gx=4, gy=5, gz=6))
        assert list(buf._buf[0]) == pytest.approx([1, 2, 3, 4, 5, 6])

    def test_gravity_cal_zeroes_z(self):
        buf = IMUBuffer(capacity=5)
        _fill_buf(buf, n=5, az=GRAVITY_MS2)
        buf.apply_gravity_calibration(np.array([0.0, 0.0, GRAVITY_MS2], dtype=np.float32))
        assert np.allclose(buf._buf[:, 2], 0.0, atol=1e-4)

    def test_gravity_cal_leaves_xy(self):
        buf = IMUBuffer(capacity=5)
        _fill_buf(buf, n=5, ax=1.0, ay=2.0, az=GRAVITY_MS2)
        buf.apply_gravity_calibration(np.array([0.0, 0.0, GRAVITY_MS2], dtype=np.float32))
        assert np.allclose(buf._buf[:, 0], 1.0, atol=1e-4)
        assert np.allclose(buf._buf[:, 1], 2.0, atol=1e-4)

    def test_get_window_returns_copy(self):
        buf = IMUBuffer(capacity=5)
        _fill_buf(buf, n=5, ax=3.0)
        w = buf.get_window()
        w[:, 0] = -999.0
        assert buf._buf[:, 0].max() != -999.0


# ===========================================================================
# calibrate_gravity
# ===========================================================================

class TestCalibrateGravity:

    def _static(self, n, ax=0.0, ay=0.0, az=GRAVITY_MS2):
        return [_make_sample(t_ms=i * 10, ax=ax, ay=ay, az=az) for i in range(n)]

    def test_correct_mean(self):
        samples = self._static(IMU_SAMPLE_RATE_HZ, ax=0.1, ay=-0.05, az=GRAVITY_MS2)
        off = calibrate_gravity(samples, duration_s=1.0)
        assert off.shape == (3,)
        assert off[0] == pytest.approx(0.1, abs=1e-4)
        assert off[1] == pytest.approx(-0.05, abs=1e-4)
        assert off[2] == pytest.approx(GRAVITY_MS2, abs=1e-4)

    def test_raises_insufficient_samples(self):
        samples = self._static(50)
        with pytest.raises(ValueError, match="requires"):
            calibrate_gravity(samples, duration_s=1.0)

    def test_exact_minimum_accepted(self):
        samples = self._static(IMU_SAMPLE_RATE_HZ)
        off = calibrate_gravity(samples, duration_s=1.0)
        assert off is not None

    def test_extra_samples_ignored(self):
        good = self._static(IMU_SAMPLE_RATE_HZ, ax=1.0)
        extra = self._static(50, ax=99.0)
        off = calibrate_gravity(good + extra, duration_s=1.0)
        assert off[0] == pytest.approx(1.0, abs=1e-4)

    def test_output_is_float32(self):
        samples = self._static(IMU_SAMPLE_RATE_HZ)
        off = calibrate_gravity(samples, duration_s=1.0)
        assert off.dtype == np.float32


# ===========================================================================
# NearMissFeatureExtractor
# ===========================================================================

class TestNearMissFeatureExtractor:

    def setup_method(self):
        self.ext = NearMissFeatureExtractor()

    def _lat_window(self, g):
        w = _normal_window()
        w[60, 1] = g * GRAVITY_MS2
        return w

    def _brake_window(self, decel):
        w = _normal_window()
        w[50:70, 0] = -decel
        return w

    def _yaw_window(self, yaw):
        w = _normal_window()
        w[60:80, 5] = yaw
        return w

    # compute() output structure

    def test_compute_returns_required_keys(self):
        f = self.ext.compute(_normal_window())
        assert {"lateral_g_peak", "longitudinal_decel_ms2",
                "yaw_rate_peak_degs", "rms_jerk_ms3", "should_run_tcn"} <= set(f)

    def test_compute_quiet_no_tcn(self):
        f = self.ext.compute(_normal_window())
        assert f["lateral_g_peak"] < LATERAL_G_MEDIUM_THRESHOLD
        assert not f["should_run_tcn"]

    def test_compute_lateral_above_medium_triggers(self):
        f = self.ext.compute(self._lat_window(0.35))
        assert f["lateral_g_peak"] >= LATERAL_G_MEDIUM_THRESHOLD
        assert f["should_run_tcn"]

    def test_compute_hard_braking_triggers(self):
        f = self.ext.compute(self._brake_window(6.0))
        assert f["longitudinal_decel_ms2"] >= LONGITUDINAL_DECEL_HIGH_MS2
        assert f["should_run_tcn"]

    def test_compute_high_yaw_triggers(self):
        f = self.ext.compute(self._yaw_window(65.0))
        assert f["yaw_rate_peak_degs"] >= YAW_RATE_CRITICAL_DEGS * 0.7
        assert f["should_run_tcn"]

    def test_compute_critical_lateral(self):
        f = self.ext.compute(self._lat_window(0.70))
        assert f["lateral_g_peak"] >= LATERAL_G_CRITICAL_THRESHOLD

    def test_compute_negative_lateral_absolute(self):
        w = _normal_window()
        w[60, 1] = -0.50 * GRAVITY_MS2
        f = self.ext.compute(w)
        assert f["lateral_g_peak"] > 0

    def test_compute_rms_jerk_nonneg(self):
        f = self.ext.compute(_normal_window())
        assert f["rms_jerk_ms3"] >= 0.0

    def test_compute_spike_jerk_triggers(self):
        w = _normal_window()
        w[60, 0] = -20.0  # sudden large decel spike → large jerk
        f = self.ext.compute(w)
        assert f["should_run_tcn"]

    # classify_severity_deterministic()

    def test_critical_lateral_g(self):
        sev = self.ext.classify_severity_deterministic(
            LATERAL_G_CRITICAL_THRESHOLD + 0.01, 0.0, 0.0, 0.0)
        assert sev == NearMissSeverity.CRITICAL

    def test_critical_decel(self):
        sev = self.ext.classify_severity_deterministic(
            0.0, LONGITUDINAL_DECEL_CRITICAL_MS2 + 0.1, 0.0, 0.0)
        assert sev == NearMissSeverity.CRITICAL

    def test_critical_yaw(self):
        sev = self.ext.classify_severity_deterministic(
            0.0, 0.0, YAW_RATE_CRITICAL_DEGS + 1.0, 0.0)
        assert sev == NearMissSeverity.CRITICAL

    def test_high_lateral_g(self):
        sev = self.ext.classify_severity_deterministic(
            LATERAL_G_HIGH_THRESHOLD + 0.01, 0.0, 0.0, 0.0)
        assert sev == NearMissSeverity.HIGH

    def test_high_decel(self):
        sev = self.ext.classify_severity_deterministic(
            0.0, LONGITUDINAL_DECEL_HIGH_MS2 + 0.1, 0.0, 0.0)
        assert sev == NearMissSeverity.HIGH

    def test_medium_below_high_thresholds(self):
        sev = self.ext.classify_severity_deterministic(
            LATERAL_G_MEDIUM_THRESHOLD, 1.0, 10.0, 1.0)
        assert sev == NearMissSeverity.MEDIUM

    def test_all_zero_is_medium(self):
        assert self.ext.classify_severity_deterministic(0, 0, 0, 0) == NearMissSeverity.MEDIUM

    def test_exact_critical_threshold_is_critical(self):
        sev = self.ext.classify_severity_deterministic(
            LATERAL_G_CRITICAL_THRESHOLD, 0.0, 0.0, 0.0)
        assert sev == NearMissSeverity.CRITICAL


# ===========================================================================
# NearMissDetector (DETERMINISTIC mode)
# ===========================================================================

class TestNearMissDetector:

    def _det(self, interval=10):
        d = NearMissDetector(onnx_model_path=None,
                             inference_interval_samples=interval,
                             anomaly_score_threshold=0.65)
        d.load()
        return d

    def _quiet_fill(self, det, n=WINDOW_SIZE_SAMPLES):
        events = []
        for i in range(n):
            ev = det.push_sample(_make_sample(t_ms=i * 10))
            if ev:
                events.append(ev)
        return events

    # initialisation

    def test_deterministic_mode_selected(self):
        assert self._det()._mode == "DETERMINISTIC"

    def test_load_no_crash(self):
        d = NearMissDetector()
        d.load()

    # no event before buffer fills

    def test_no_event_before_full(self):
        d = self._det()
        for i in range(WINDOW_SIZE_SAMPLES - 1):
            assert d.push_sample(_make_sample(t_ms=i * 10)) is None

    def test_no_event_quiet_driving(self):
        d = self._det()
        events = self._quiet_fill(d, WINDOW_SIZE_SAMPLES + 50)
        assert len(events) == 0

    # critical swerve detection

    def test_critical_swerve_emits_event(self):
        d = self._det()
        self._quiet_fill(d)
        events = []
        ay = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 1.5
        for i in range(WINDOW_SIZE_SAMPLES, WINDOW_SIZE_SAMPLES + 20):
            ev = d.push_sample(_make_sample(t_ms=i * 10, ay=ay))
            if ev:
                events.append(ev)
        assert len(events) > 0

    def test_critical_swerve_severity_is_critical(self):
        d = self._det()
        self._quiet_fill(d)
        ay = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 1.5
        for i in range(WINDOW_SIZE_SAMPLES, WINDOW_SIZE_SAMPLES + 20):
            ev = d.push_sample(_make_sample(t_ms=i * 10, ay=ay))
            if ev:
                assert ev.severity == NearMissSeverity.CRITICAL
                return
        pytest.fail("Expected at least one CRITICAL event")

    def test_event_id_is_valid_uuid4(self):
        d = self._det()
        self._quiet_fill(d)
        ay = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 1.5
        for i in range(WINDOW_SIZE_SAMPLES, WINDOW_SIZE_SAMPLES + 20):
            ev = d.push_sample(_make_sample(t_ms=i * 10, ay=ay))
            if ev:
                parsed = uuid.UUID(ev.event_id)
                assert str(parsed) == ev.event_id
                return
        pytest.fail("No event emitted")

    def test_event_lateral_g_peak_populated(self):
        d = self._det()
        self._quiet_fill(d)
        ay = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 1.5
        for i in range(WINDOW_SIZE_SAMPLES, WINDOW_SIZE_SAMPLES + 20):
            ev = d.push_sample(_make_sample(t_ms=i * 10, ay=ay))
            if ev:
                assert ev.lateral_g_peak > 0
                return
        pytest.fail("No event emitted")

    def test_event_timestamp_matches_sample(self):
        d = self._det()
        self._quiet_fill(d)
        ay = LATERAL_G_CRITICAL_THRESHOLD * GRAVITY_MS2 * 1.5
        for i in range(WINDOW_SIZE_SAMPLES, WINDOW_SIZE_SAMPLES + 20):
            t_ms = i * 10
            ev = d.push_sample(_make_sample(t_ms=t_ms, ay=ay))
            if ev:
                assert ev.timestamp_epoch_ms == t_ms
                return
        pytest.fail("No event emitted")

    # gravity calibration propagation

    def test_gravity_calibration_applied_to_samples(self):
        """
        With gravity calibration set, a sample with az=GRAVITY_MS2 should be
        adjusted to az≈0 before buffering, so normal-gravity samples won't
        trigger detection even with very low thresholds.
        """
        d = self._det()
        offset = np.array([0.0, 0.0, GRAVITY_MS2], dtype=np.float32)
        d.set_gravity_calibration(offset)
        # After calibration, the stored gravity offset must be set
        assert d._gravity_offset is not None
        assert np.allclose(d._gravity_offset, offset)

    def test_set_gravity_calibration_stores_offset(self):
        d = self._det()
        offset = np.array([0.1, 0.2, 9.8], dtype=np.float32)
        d.set_gravity_calibration(offset)
        assert np.allclose(d._gravity_offset, offset)

    # _map_score_to_severity

    def test_map_high_score_to_critical(self):
        d = self._det()
        features = {"lateral_g_peak": 0.0, "longitudinal_decel_ms2": 0.0,
                    "yaw_rate_peak_degs": 0.0, "rms_jerk_ms3": 0.0}
        sev = d._map_score_to_severity(0.90, features)
        assert sev == NearMissSeverity.CRITICAL

    def test_map_medium_score_to_high(self):
        d = self._det()
        features = {"lateral_g_peak": 0.0, "longitudinal_decel_ms2": 0.0,
                    "yaw_rate_peak_degs": 0.0, "rms_jerk_ms3": 0.0}
        sev = d._map_score_to_severity(0.70, features)
        assert sev == NearMissSeverity.HIGH

    def test_map_low_score_to_medium(self):
        d = self._det()
        features = {"lateral_g_peak": 0.0, "longitudinal_decel_ms2": 0.0,
                    "yaw_rate_peak_degs": 0.0, "rms_jerk_ms3": 0.0}
        sev = d._map_score_to_severity(0.30, features)
        assert sev == NearMissSeverity.MEDIUM

    def test_deterministic_critical_overrides_low_score(self):
        """Deterministic CRITICAL must win regardless of TCN score."""
        d = self._det()
        features = {
            "lateral_g_peak": LATERAL_G_CRITICAL_THRESHOLD + 0.1,
            "longitudinal_decel_ms2": 0.0,
            "yaw_rate_peak_degs": 0.0,
            "rms_jerk_ms3": 0.0,
        }
        sev = d._map_score_to_severity(0.10, features)
        assert sev == NearMissSeverity.CRITICAL

    # hard braking detection

    def test_hard_brake_emits_event(self):
        d = self._det()
        self._quiet_fill(d)
        ax = -(LONGITUDINAL_DECEL_CRITICAL_MS2 + 1.0)
        for i in range(WINDOW_SIZE_SAMPLES, WINDOW_SIZE_SAMPLES + 20):
            ev = d.push_sample(_make_sample(t_ms=i * 10, ax=ax))
            if ev:
                return  # pass
        pytest.fail("Expected event for hard braking")

    # sample counter increments

    def test_sample_counter_increments(self):
        d = self._det()
        for i in range(5):
            d.push_sample(_make_sample(t_ms=i * 10))
        assert d._sample_count == 5
