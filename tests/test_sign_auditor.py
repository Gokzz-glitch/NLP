"""
tests/test_sign_auditor.py

Unit tests for agents/sign_auditor.py covering:
  - haversine_m accuracy and edge cases
  - SignAuditor.check_sign_in_window (within / outside 500 m, empty list)
  - SignAuditor.audit_frame (no camera, camera + no sign, camera + sign)
  - MOCK_MODE when no vision engine
  - AuditResult type
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
from unittest.mock import MagicMock

from agents.sign_auditor import (
    haversine_m,
    SignAuditor,
    SignDetection,
    AuditResult,
)


# ---------------------------------------------------------------------------
# haversine_m
# ---------------------------------------------------------------------------

class TestHaversine:

    def test_same_point_is_zero(self):
        assert haversine_m(12.9, 80.2, 12.9, 80.2) == pytest.approx(0.0, abs=1e-3)

    def test_known_distance_chennai_tambaram(self):
        # Chennai Central ↔ Tambaram ≈ 20–25 km
        d = haversine_m(13.0827, 80.2707, 12.9249, 80.1000)
        assert 20_000 < d < 26_000

    def test_approx_500m_north(self):
        # ~0.0045° of latitude ≈ 500 m
        d = haversine_m(12.9, 80.2, 12.9045, 80.2)
        assert abs(d - 500) < 30

    def test_symmetry(self):
        d1 = haversine_m(12.9, 80.2, 12.95, 80.25)
        d2 = haversine_m(12.95, 80.25, 12.9, 80.2)
        assert abs(d1 - d2) < 1e-3

    def test_returns_float(self):
        assert isinstance(haversine_m(0.0, 0.0, 1.0, 1.0), float)

    def test_positive_result(self):
        assert haversine_m(12.9, 80.2, 13.0, 80.3) > 0


# ---------------------------------------------------------------------------
# SignAuditor.check_sign_in_window
# ---------------------------------------------------------------------------

class TestCheckSignInWindow:

    def setup_method(self):
        self.auditor = SignAuditor(vision_engine=None)

    def test_sign_within_500m_true(self):
        # Place sign ~200 m north
        sign_lat = 12.9 + (200 / 111_000)
        within, dist = self.auditor.check_sign_in_window(12.9, 80.2, [(sign_lat, 80.2)])
        assert within
        assert dist < 500

    def test_sign_at_600m_false(self):
        sign_lat = 12.9 + (600 / 111_000)
        within, dist = self.auditor.check_sign_in_window(12.9, 80.2, [(sign_lat, 80.2)])
        assert not within
        assert dist > 500

    def test_empty_list_false_none(self):
        within, dist = self.auditor.check_sign_in_window(12.9, 80.2, [])
        assert not within
        assert dist is None

    def test_multiple_signs_uses_nearest(self):
        near_lat = 12.9 + (100 / 111_000)
        far_lat  = 12.9 + (800 / 111_000)
        within, dist = self.auditor.check_sign_in_window(
            12.9, 80.2, [(far_lat, 80.2), (near_lat, 80.2)]
        )
        assert within
        assert dist < 200

    def test_returns_tuple_of_two(self):
        result = self.auditor.check_sign_in_window(12.9, 80.2, [])
        assert isinstance(result, tuple) and len(result) == 2

    def test_sign_exactly_at_500m_boundary(self):
        # 500 m north (approximate)
        sign_lat = 12.9 + (500 / 111_000)
        within, dist = self.auditor.check_sign_in_window(12.9, 80.2, [(sign_lat, 80.2)])
        # Should be within or at boundary (haversine is not exact at this resolution)
        assert dist == pytest.approx(500, abs=10)


# ---------------------------------------------------------------------------
# SignAuditor.audit_frame
# ---------------------------------------------------------------------------

class TestAuditFrame:

    def _auditor_with_labels(self, labels):
        mock_engine = MagicMock()
        mock_engine.is_mock = False
        mock_engine.run_inference.return_value = [
            {"label": lbl, "conf": 0.9, "bbox": [0, 0, 100, 100]}
            for lbl in labels
        ]
        return SignAuditor(vision_engine=mock_engine)

    def test_no_camera_not_challengeable(self):
        auditor = self._auditor_with_labels(["pothole"])
        result = auditor.audit_frame(np.zeros((100, 100, 3), dtype=np.uint8), 12.9, 80.2)
        assert not result.camera_detected
        assert not result.sec208_challengeable

    def test_camera_no_sign_is_challengeable(self):
        auditor = self._auditor_with_labels(["speed_camera"])
        result = auditor.audit_frame(np.zeros((100, 100, 3), dtype=np.uint8), 12.9, 80.2)
        assert result.camera_detected
        assert result.sec208_challengeable

    def test_camera_with_sign_within_500m_not_challengeable(self):
        mock_engine = MagicMock()
        mock_engine.is_mock = False
        mock_engine.run_inference.return_value = [
            {"label": "speed_camera", "conf": 0.9, "bbox": [0, 0, 100, 100]},
        ]
        auditor = SignAuditor(vision_engine=mock_engine)
        known_sign = SignDetection(
            label="speed_limit_sign",
            confidence=0.9,
            gps_lat=12.9,  # Same position → 0 m distance → within 500 m
            gps_lon=80.2,
        )
        result = auditor.audit_frame(
            np.zeros((100, 100, 3), dtype=np.uint8), 12.9, 80.2,
            known_signs=[known_sign],
        )
        assert result.camera_detected
        assert not result.sec208_challengeable

    def test_camera_sign_outside_500m_challengeable(self):
        mock_engine = MagicMock()
        mock_engine.is_mock = False
        mock_engine.run_inference.return_value = [
            {"label": "speed_camera", "conf": 0.9, "bbox": [0, 0, 100, 100]},
        ]
        auditor = SignAuditor(vision_engine=mock_engine)
        # Sign > 500 m away
        far_lat = 12.9 + (800 / 111_000)
        known_sign = SignDetection(
            label="speed_limit_sign",
            confidence=0.9,
            gps_lat=far_lat,
            gps_lon=80.2,
        )
        result = auditor.audit_frame(
            np.zeros((100, 100, 3), dtype=np.uint8), 12.9, 80.2,
            known_signs=[known_sign],
        )
        assert result.camera_detected
        assert result.sec208_challengeable

    def test_mock_mode_no_camera(self):
        auditor = SignAuditor(vision_engine=None)
        result = auditor.audit_frame(None, 12.9, 80.2)
        assert not result.camera_detected

    def test_returns_audit_result_type(self):
        auditor = self._auditor_with_labels([])
        result = auditor.audit_frame(np.zeros((100, 100, 3), dtype=np.uint8), 12.9, 80.2)
        assert isinstance(result, AuditResult)

    def test_known_signs_merged_into_detections(self):
        auditor = self._auditor_with_labels(["speed_camera"])
        extra = SignDetection(label="speed_limit_sign", confidence=0.8)
        result = auditor.audit_frame(
            np.zeros((100, 100, 3), dtype=np.uint8), 12.9, 80.2,
            known_signs=[extra],
        )
        labels = [d.label for d in result.detections]
        assert "speed_limit_sign" in labels
