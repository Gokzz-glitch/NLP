"""
tests/test_section_208_resolver.py

Unit tests for section_208_resolver.py — Section208Resolver.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from section_208_resolver import Section208Resolver


class TestSection208Resolver:

    def setup_method(self):
        self.resolver = Section208Resolver()

    def _camera(self, lat=12.9, lon=80.2, typ="speed_camera"):
        return {"lat": lat, "lon": lon, "type": typ}

    # --- challenge_speed_camera ---

    def test_camera_no_signage_generates_challenge(self):
        result = self.resolver.challenge_speed_camera(self._camera(), signage_detected=False)
        assert result["status"] == "CHALLENGE_GENERATED"

    def test_camera_with_signage_compliant(self):
        result = self.resolver.challenge_speed_camera(self._camera(), signage_detected=True)
        assert result["status"] == "LEGAL_COMPLIANCE_VERIFIED"

    def test_non_camera_type_no_signage_compliant(self):
        result = self.resolver.challenge_speed_camera(
            self._camera(typ="traffic_light"), signage_detected=False
        )
        assert result["status"] == "LEGAL_COMPLIANCE_VERIFIED"

    def test_non_camera_type_with_signage_compliant(self):
        result = self.resolver.challenge_speed_camera(
            self._camera(typ="stop_sign"), signage_detected=True
        )
        assert result["status"] == "LEGAL_COMPLIANCE_VERIFIED"

    def test_challenge_contains_legal_basis(self):
        result = self.resolver.challenge_speed_camera(self._camera(), signage_detected=False)
        assert "legal_basis" in result
        assert "208" in result["legal_basis"]

    def test_challenge_contains_document(self):
        result = self.resolver.challenge_speed_camera(self._camera(), signage_detected=False)
        assert "document" in result
        assert len(result["document"]) > 0

    def test_challenge_contains_only_expected_keys(self):
        result = self.resolver.challenge_speed_camera(self._camera(), signage_detected=False)
        assert set(result.keys()) == {"status", "document", "legal_basis"}

    def test_compliance_contains_only_status(self):
        result = self.resolver.challenge_speed_camera(self._camera(), signage_detected=True)
        assert set(result.keys()) == {"status"}

    # --- generate_audit_request ---

    def test_audit_request_contains_lat(self):
        doc = self.resolver.generate_audit_request({"lat": 12.924, "lon": 80.230})
        assert "12.924" in doc

    def test_audit_request_contains_lon(self):
        doc = self.resolver.generate_audit_request({"lat": 12.924, "lon": 80.230})
        # Python may drop trailing zero (80.23 == 80.230), so check the numeric prefix
        assert "80.23" in doc

    def test_audit_request_mentions_section_208(self):
        doc = self.resolver.generate_audit_request({"lat": 0.0, "lon": 0.0})
        assert "208" in doc

    def test_audit_request_mentions_morth(self):
        doc = self.resolver.generate_audit_request({"lat": 0.0, "lon": 0.0})
        assert "MoRTH" in doc or "Traffic" in doc

    def test_audit_request_is_string(self):
        doc = self.resolver.generate_audit_request({"lat": 1.0, "lon": 2.0})
        assert isinstance(doc, str)

    def test_audit_request_nonempty(self):
        doc = self.resolver.generate_audit_request({"lat": 1.0, "lon": 2.0})
        assert len(doc.strip()) > 0

    # --- Custom db_path ---

    def test_custom_db_path_stored(self):
        r = Section208Resolver(db_path="custom.db")
        assert r.db_path == "custom.db"
