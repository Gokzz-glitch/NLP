"""
tests/test_irad_serializer.py

Unit tests for core/irad_serializer.py covering:
  - serialize_near_miss: all required iRAD V-NMS-01 fields present
  - data_integrity_sha3_256: valid 64-char hex digest
  - submission_ts_ist: IST timezone offset in string
  - device_id propagated
  - road_type override respected
  - serialize_to_json: valid JSON, contains event_id
  - _ist_now: format and IST offset
  - _sha3_256_hex: length, determinism, uniqueness
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from datetime import datetime

from core.irad_serializer import serialize_near_miss, serialize_to_json, _sha3_256_hex, _ist_now
from agents.imu_near_miss_detector import NearMissEvent, NearMissSeverity


def _make_event(**kwargs):
    defaults = dict(
        event_id="test-uuid-1234",
        timestamp_epoch_ms=1700000000000,
        severity=NearMissSeverity.HIGH,
        lateral_g_peak=0.50,
        longitudinal_decel_ms2=6.0,
        yaw_rate_peak_degs=45.0,
        rms_jerk_ms3=8.0,
        tcn_anomaly_score=0.75,
        gps_lat=12.920,
        gps_lon=80.230,
    )
    defaults.update(kwargs)
    return NearMissEvent(**defaults)


# ---------------------------------------------------------------------------
# serialize_near_miss — required fields
# ---------------------------------------------------------------------------

class TestSerializeNearMiss:

    def test_returns_dict(self):
        assert isinstance(serialize_near_miss(_make_event()), dict)

    def test_schema_version(self):
        assert serialize_near_miss(_make_event())["schema_version"] == "V-NMS-01"

    def test_event_id_preserved(self):
        assert serialize_near_miss(_make_event(event_id="abc-123"))["event_id"] == "abc-123"

    def test_irad_category_code(self):
        assert serialize_near_miss(_make_event())["irad_category_code"] == "V-NMS-01"

    def test_severity_is_string(self):
        r = serialize_near_miss(_make_event(severity=NearMissSeverity.CRITICAL))
        assert r["severity"] == "CRITICAL"

    def test_device_id_propagated(self):
        r = serialize_near_miss(_make_event(), device_id="VLTD-123")
        assert r["device_id"] == "VLTD-123"

    def test_device_id_default_unknown(self):
        assert serialize_near_miss(_make_event())["device_id"] == "UNKNOWN"

    def test_submission_ts_ist_present(self):
        r = serialize_near_miss(_make_event())
        assert "submission_ts_ist" in r
        assert "+05:30" in r["submission_ts_ist"]

    def test_data_integrity_hash_present(self):
        r = serialize_near_miss(_make_event())
        assert "data_integrity_sha3_256" in r

    def test_data_integrity_hash_is_64_chars(self):
        r = serialize_near_miss(_make_event())
        assert len(r["data_integrity_sha3_256"]) == 64

    def test_data_integrity_hash_is_valid_hex(self):
        r = serialize_near_miss(_make_event())
        int(r["data_integrity_sha3_256"], 16)  # Must not raise

    def test_kinematic_fields_present(self):
        r = serialize_near_miss(_make_event())
        for f in ["lateral_g_peak", "longitudinal_decel_ms2",
                  "yaw_rate_peak_degs", "rms_jerk_ms3", "tcn_anomaly_score"]:
            assert f in r

    def test_gps_fields_present(self):
        r = serialize_near_miss(_make_event())
        assert "gps_lat" in r and "gps_lon" in r

    def test_sec208_flag_present(self):
        assert "triggered_sec208" in serialize_near_miss(_make_event())

    def test_road_type_override(self):
        r = serialize_near_miss(_make_event(), road_type="national_highway")
        assert r["road_type"] == "national_highway"

    def test_road_type_falls_back_to_event(self):
        evt = _make_event()
        evt.road_type = "urban"
        r = serialize_near_miss(evt)
        assert r["road_type"] == "urban"

    def test_integrity_hash_changes_when_payload_changes(self):
        r1 = serialize_near_miss(_make_event(lateral_g_peak=0.5))
        r2 = serialize_near_miss(_make_event(lateral_g_peak=0.9))
        assert r1["data_integrity_sha3_256"] != r2["data_integrity_sha3_256"]


# ---------------------------------------------------------------------------
# IST timestamp
# ---------------------------------------------------------------------------

class TestISTTimestamp:

    def test_contains_ist_offset(self):
        assert "+05:30" in _ist_now()

    def test_parseable_format(self):
        ts = _ist_now()
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S+05:30")


# ---------------------------------------------------------------------------
# SHA3-256 hex
# ---------------------------------------------------------------------------

class TestSHA3Hex:

    def test_length_64(self):
        assert len(_sha3_256_hex("test data")) == 64

    def test_deterministic(self):
        assert _sha3_256_hex("same") == _sha3_256_hex("same")

    def test_different_input_different_hash(self):
        assert _sha3_256_hex("A") != _sha3_256_hex("B")


# ---------------------------------------------------------------------------
# serialize_to_json
# ---------------------------------------------------------------------------

class TestSerializeToJson:

    def test_returns_valid_json(self):
        result = serialize_to_json(_make_event())
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_json_contains_event_id(self):
        result = serialize_to_json(_make_event(event_id="json-test"))
        assert json.loads(result)["event_id"] == "json-test"

    def test_json_contains_schema_version(self):
        result = serialize_to_json(_make_event())
        assert json.loads(result)["schema_version"] == "V-NMS-01"
