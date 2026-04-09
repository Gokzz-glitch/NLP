"""
tests/test_section_208_haversine.py

Tests for the haversine / IST timestamp / SHA3 evidence hash additions to
section_208_resolver.py (enhancements from audit):
  - _haversine_m accuracy and edge cases
  - _ist_timestamp format and IST offset
  - _sha3_evidence_hash: 64-char hex, determinism, sensitivity
  - generate_audit_request now contains TIMESTAMP (IST) and EVIDENCE HASH fields
  - challenge_speed_camera with sign_lat/sign_lon GPS distance check
  - sign_distance_m returned only when GPS coordinates are provided
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import json
import pytest
from datetime import datetime

from section_208_resolver import (
    Section208Resolver,
    _haversine_m,
    _ist_timestamp,
    _sha3_evidence_hash,
    _SIGN_WINDOW_M,
)


# ---------------------------------------------------------------------------
# _haversine_m
# ---------------------------------------------------------------------------

class TestHaversineM:

    def test_same_point_zero(self):
        assert _haversine_m(12.9, 80.2, 12.9, 80.2) == pytest.approx(0.0, abs=1e-3)

    def test_approx_500m_north(self):
        # ~0.0045° of latitude ≈ 500 m
        d = _haversine_m(12.9, 80.2, 12.9045, 80.2)
        assert abs(d - 500) < 30

    def test_sign_window_constant_is_500(self):
        assert _SIGN_WINDOW_M == 500.0

    def test_symmetry(self):
        d1 = _haversine_m(12.9, 80.2, 12.95, 80.25)
        d2 = _haversine_m(12.95, 80.25, 12.9, 80.2)
        assert abs(d1 - d2) < 1e-3

    def test_positive_for_distinct_coords(self):
        assert _haversine_m(12.9, 80.2, 13.0, 80.3) > 0

    def test_returns_float(self):
        assert isinstance(_haversine_m(0.0, 0.0, 1.0, 1.0), float)

    def test_chennai_to_tambaram_approx(self):
        d = _haversine_m(13.0827, 80.2707, 12.9249, 80.1000)
        assert 20_000 < d < 26_000


# ---------------------------------------------------------------------------
# _ist_timestamp
# ---------------------------------------------------------------------------

class TestISTTimestamp:

    def test_contains_ist_offset(self):
        ts = _ist_timestamp()
        assert "+05:30" in ts

    def test_parseable_format(self):
        ts = _ist_timestamp()
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S+05:30")

    def test_returns_string(self):
        assert isinstance(_ist_timestamp(), str)


# ---------------------------------------------------------------------------
# _sha3_evidence_hash
# ---------------------------------------------------------------------------

class TestSHA3EvidenceHash:

    def test_length_64(self):
        h = _sha3_evidence_hash({"lat": 12.9, "lon": 80.2})
        assert len(h) == 64

    def test_valid_hex(self):
        h = _sha3_evidence_hash({"lat": 12.9, "lon": 80.2})
        int(h, 16)  # Must not raise ValueError

    def test_deterministic(self):
        d = {"lat": 12.9, "lon": 80.2, "type": "speed_camera"}
        assert _sha3_evidence_hash(d) == _sha3_evidence_hash(d)

    def test_different_coords_different_hash(self):
        h1 = _sha3_evidence_hash({"lat": 12.9, "lon": 80.2})
        h2 = _sha3_evidence_hash({"lat": 12.9, "lon": 80.3})
        assert h1 != h2


# ---------------------------------------------------------------------------
# generate_audit_request — new IST + hash fields
# ---------------------------------------------------------------------------

class TestAuditDocumentEnhancements:

    def setup_method(self):
        self.resolver = Section208Resolver()

    def test_document_contains_ist_timestamp_label(self):
        doc = self.resolver.generate_audit_request({"lat": 12.9, "lon": 80.2})
        assert "TIMESTAMP (IST)" in doc

    def test_document_contains_evidence_hash_label(self):
        doc = self.resolver.generate_audit_request({"lat": 12.9, "lon": 80.2})
        assert "EVIDENCE HASH" in doc

    def test_document_contains_64char_hex_hash(self):
        doc = self.resolver.generate_audit_request({"lat": 12.9, "lon": 80.2})
        # Find a 64-char hex sequence in the document
        import re
        found = re.search(r"[0-9a-f]{64}", doc)
        assert found is not None, "No 64-char hex hash found in audit document"

    def test_document_still_contains_lat(self):
        doc = self.resolver.generate_audit_request({"lat": 12.924, "lon": 80.230})
        assert "12.924" in doc

    def test_document_still_mentions_section_208(self):
        doc = self.resolver.generate_audit_request({"lat": 0.0, "lon": 0.0})
        assert "208" in doc


# ---------------------------------------------------------------------------
# challenge_speed_camera — GPS distance check
# ---------------------------------------------------------------------------

class TestGPSDistanceChallenge:

    def setup_method(self):
        self.resolver = Section208Resolver()

    def _camera(self, lat=12.9, lon=80.2):
        return {"lat": lat, "lon": lon, "type": "speed_camera"}

    def test_sign_within_500m_gps_verified(self):
        # Sign 200 m north of camera → compliant
        sign_lat = 12.9 + (200 / 111_000)
        result = self.resolver.challenge_speed_camera(
            self._camera(), signage_detected=False,
            sign_lat=sign_lat, sign_lon=80.2
        )
        assert result["status"] == "LEGAL_COMPLIANCE_VERIFIED"

    def test_sign_outside_500m_gps_challenged(self):
        # Sign 800 m north of camera → not compliant
        sign_lat = 12.9 + (800 / 111_000)
        result = self.resolver.challenge_speed_camera(
            self._camera(), signage_detected=True,   # boolean says compliant
            sign_lat=sign_lat, sign_lon=80.2         # but GPS says 800m → override
        )
        assert result["status"] == "CHALLENGE_GENERATED"

    def test_sign_distance_m_in_result_when_gps_provided(self):
        sign_lat = 12.9 + (800 / 111_000)
        result = self.resolver.challenge_speed_camera(
            self._camera(), signage_detected=False,
            sign_lat=sign_lat, sign_lon=80.2
        )
        assert "sign_distance_m" in result
        assert result["sign_distance_m"] > 500

    def test_sign_distance_m_not_in_result_when_no_gps(self):
        result = self.resolver.challenge_speed_camera(
            self._camera(), signage_detected=False
        )
        assert "sign_distance_m" not in result

    def test_gps_result_keys_include_new_field(self):
        sign_lat = 12.9 + (800 / 111_000)
        result = self.resolver.challenge_speed_camera(
            self._camera(), signage_detected=False,
            sign_lat=sign_lat, sign_lon=80.2
        )
        assert {"status", "document", "legal_basis", "statutory_sources", "sign_distance_m"}.issubset(
            result.keys()
        )

    def test_gps_distance_accuracy(self):
        # 800 m north: ~0.0072°
        sign_lat = 12.9 + (800 / 111_000)
        result = self.resolver.challenge_speed_camera(
            self._camera(), signage_detected=False,
            sign_lat=sign_lat, sign_lon=80.2
        )
        # Should be 800 m ± 10 m
        assert abs(result["sign_distance_m"] - 800) < 10
