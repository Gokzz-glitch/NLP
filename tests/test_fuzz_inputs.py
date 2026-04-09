"""
tests/test_fuzz_inputs.py
SmartSalai Edge-Sentinel — Input Fuzzing & Negative Tests

Tests that every public input surface rejects or gracefully handles
unexpected / malformed / adversarial input without crashing.

Coverage:
  - API server endpoints (ingest, fleet-routing, razorpay webhook)
  - AgentBus publish with garbage payloads
  - ZKPEnvelopeBuilder with extreme numeric edge cases
  - Sec208DrafterAgent with missing / null fields
  - LegalRAGAgent with injection-style queries
  - BLEMeshMessage with oversized / truncated bytes
  - IMUSample with NaN / Inf / extreme values
  - Section208Resolver with empty / corrupt DB path
"""

from __future__ import annotations

import sys
import os
import json
import random
import string
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _random_str(n: int = 32) -> str:
    return "".join(random.choices(string.printable, k=n))


def _random_bytes(n: int = 32) -> bytes:
    return bytes(random.getrandbits(8) for _ in range(n))


# ──────────────────────────────────────────────────────────────────────────────
# 1. API Server — ingest endpoint fuzzing
# ──────────────────────────────────────────────────────────────────────────────

class TestAPIFuzzing:
    """Fuzz the FastAPI server endpoints with malformed payloads."""

    @pytest.fixture(scope="class")
    def client(self):
        try:
            from fastapi.testclient import TestClient
            from api.server import create_app
            return TestClient(create_app())
        except ImportError:
            pytest.skip("fastapi or httpx not available")

    # --- ingest endpoint ---

    def test_ingest_valid_minimal(self, client):
        resp = client.post("/api/v1/internal/ingest", json={
            "node_id": "test-node-01",
            "event_type": "vision_detection",
            "timestamp": 1700000000.0,
        })
        assert resp.status_code == 201

    def test_ingest_missing_node_id(self, client):
        resp = client.post("/api/v1/internal/ingest", json={
            "event_type": "vision_detection",
        })
        assert resp.status_code == 422  # FastAPI validation error

    def test_ingest_missing_event_type(self, client):
        resp = client.post("/api/v1/internal/ingest", json={
            "node_id": "n1",
        })
        assert resp.status_code == 422

    def test_ingest_confidence_out_of_range_high(self, client):
        resp = client.post("/api/v1/internal/ingest", json={
            "node_id": "n1", "event_type": "vision",
            "confidence": 2.5,  # > 1.0 — should fail validation
        })
        assert resp.status_code == 422

    def test_ingest_confidence_negative(self, client):
        resp = client.post("/api/v1/internal/ingest", json={
            "node_id": "n1", "event_type": "vision",
            "confidence": -0.5,
        })
        assert resp.status_code == 422

    def test_ingest_extra_unknown_fields(self, client):
        """Extra fields must be silently ignored (not cause 500)."""
        resp = client.post("/api/v1/internal/ingest", json={
            "node_id": "n1", "event_type": "vision",
            "__proto__": "injection_attempt",
            "timestamp": 1700000000.0,
        })
        # Pydantic v2 extra='ignore' → 201; v1 may differ
        assert resp.status_code in (201, 422)

    def test_ingest_empty_body(self, client):
        resp = client.post("/api/v1/internal/ingest", json={})
        assert resp.status_code == 422

    def test_ingest_non_json_body(self, client):
        resp = client.post(
            "/api/v1/internal/ingest",
            data="not_json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_ingest_huge_node_id(self, client):
        resp = client.post("/api/v1/internal/ingest", json={
            "node_id": "A" * 10_000,
            "event_type": "x",
            "timestamp": 1700000000.0,
        })
        # Must not cause 500; validation or acceptance both ok
        assert resp.status_code in (201, 422)

    def test_ingest_sql_injection_node_id(self, client):
        resp = client.post("/api/v1/internal/ingest", json={
            "node_id": "'; DROP TABLE hazards; --",
            "event_type": "vision",
            "timestamp": 1700000000.0,
        })
        assert resp.status_code in (201, 422)

    # --- fleet-routing endpoint ---

    def test_fleet_routing_no_api_key(self, client):
        resp = client.get("/api/v1/fleet-routing-hazards")
        assert resp.status_code == 401

    def test_fleet_routing_wrong_api_key(self, client):
        resp = client.get(
            "/api/v1/fleet-routing-hazards",
            headers={"X-API-Key": "totally-wrong-key"},
        )
        assert resp.status_code == 401

    def test_fleet_routing_empty_api_key(self, client):
        resp = client.get(
            "/api/v1/fleet-routing-hazards",
            headers={"X-API-Key": ""},
        )
        assert resp.status_code == 401

    # --- razorpay webhook ---

    def test_razorpay_missing_signature(self, client):
        resp = client.post("/api/v1/webhook/razorpay", json={
            "razorpay_payment_id": "pay_abc",
            "razorpay_order_id": "order_xyz",
        })
        assert resp.status_code == 400

    def test_razorpay_garbage_signature(self, client):
        resp = client.post("/api/v1/webhook/razorpay", json={
            "razorpay_payment_id": "pay_abc",
            "razorpay_order_id": "order_xyz",
            "razorpay_signature": "not_a_real_sig",
        })
        assert resp.status_code == 400

    def test_razorpay_empty_body(self, client):
        resp = client.post("/api/v1/webhook/razorpay", json={})
        assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# 2. AgentBus — garbage payload publishing must not crash
# ──────────────────────────────────────────────────────────────────────────────

class TestAgentBusFuzzing:

    def test_publish_none_payload(self):
        import time
        from core.agent_bus import AgentBus, reset_bus
        reset_bus()
        bus = AgentBus()
        bus.start()
        # Should not raise
        bus.publish("test.topic", None)  # type: ignore[arg-type]
        time.sleep(0.05)
        bus.stop()
        reset_bus()

    def test_publish_nested_dict(self):
        import time
        from core.agent_bus import AgentBus, reset_bus
        reset_bus()
        bus = AgentBus()
        bus.start()
        bus.publish("test.topic", {"a": {"b": {"c": [1, 2, 3]}}})
        time.sleep(0.05)
        bus.stop()
        reset_bus()

    def test_publish_very_large_payload(self):
        import time
        from core.agent_bus import AgentBus, reset_bus
        reset_bus()
        bus = AgentBus()
        bus.start()
        large_payload = {"data": "x" * 100_000}
        bus.publish("test.topic", large_payload)
        time.sleep(0.05)
        bus.stop()
        reset_bus()

    def test_publish_many_messages_no_hang(self):
        import time
        from core.agent_bus import AgentBus, reset_bus
        reset_bus()
        bus = AgentBus()
        bus.start()
        for i in range(1000):
            bus.publish("test.flood", {"i": i})
        time.sleep(0.3)
        bus.stop()
        reset_bus()


# ──────────────────────────────────────────────────────────────────────────────
# 3. ZKPEnvelopeBuilder — extreme numeric edge cases
# ──────────────────────────────────────────────────────────────────────────────

class TestZKPFuzzing:

    def test_seal_zero_coordinates(self):
        from core.zkp_envelope import ZKPEnvelopeBuilder
        builder = ZKPEnvelopeBuilder()
        env = builder.seal({"gps_lat": 0.0, "gps_lon": 0.0}, "Test")
        opened = builder.open(env, env._blinding_bytes)
        assert opened.evidence_hash_verified

    def test_seal_max_float_payload(self):
        from core.zkp_envelope import ZKPEnvelopeBuilder
        builder = ZKPEnvelopeBuilder()
        payload = {"val": 1.7976931348623157e+308}
        env = builder.seal(payload, "MaxFloat")
        opened = builder.open(env, env._blinding_bytes)
        assert opened.evidence_hash_verified

    def test_seal_empty_payload(self):
        from core.zkp_envelope import ZKPEnvelopeBuilder
        builder = ZKPEnvelopeBuilder()
        env = builder.seal({}, "EmptyPayload")
        opened = builder.open(env, env._blinding_bytes)
        assert opened.evidence_hash_verified

    def test_seal_unicode_string_payload(self):
        from core.zkp_envelope import ZKPEnvelopeBuilder
        builder = ZKPEnvelopeBuilder()
        env = builder.seal({"text": "ஸ்மார்ட்சாலை 🛣️"}, "UnicodeTest")
        opened = builder.open(env, env._blinding_bytes)
        assert opened.evidence_hash_verified

    def test_open_with_wrong_blinding_factor_raises(self):
        from core.zkp_envelope import ZKPEnvelopeBuilder, TamperDetectedError
        builder = ZKPEnvelopeBuilder()
        env = builder.seal({"x": 1}, "Test")
        wrong_bytes = bytes([b ^ 0xFF for b in env._blinding_bytes])
        with pytest.raises((TamperDetectedError, Exception)):
            builder.open(env, wrong_bytes)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Sec208DrafterAgent — missing / null / malformed fields
# ──────────────────────────────────────────────────────────────────────────────

class TestSec208Fuzzing:

    def test_empty_camera_data(self):
        from agents.sec208_drafter import Sec208DrafterAgent
        drafter = Sec208DrafterAgent()
        result = drafter.evaluate(camera_data={}, signage_detected=False)
        assert result["status"] == "NOT_APPLICABLE"

    def test_none_camera_data(self):
        from agents.sec208_drafter import Sec208DrafterAgent
        drafter = Sec208DrafterAgent()
        # Should not raise; None input is coerced to {} → no device_id → NOT_APPLICABLE
        result = drafter.evaluate(camera_data=None, signage_detected=False)  # type: ignore[arg-type]
        assert "status" in result
        assert result["status"] == "NOT_APPLICABLE"

    def test_garbage_device_id(self):
        from agents.sec208_drafter import Sec208DrafterAgent
        drafter = Sec208DrafterAgent()
        result = drafter.evaluate(
            camera_data={"device_id": "'; DROP TABLE --", "lat": 0, "lon": 0},
            signage_detected=False,
        )
        assert "status" in result

    def test_nan_coordinates(self):
        import math
        from agents.sec208_drafter import Sec208DrafterAgent
        drafter = Sec208DrafterAgent()
        result = drafter.evaluate(
            camera_data={"device_id": "CAM-01", "lat": math.nan, "lon": math.nan},
            signage_detected=False,
        )
        assert "status" in result

    def test_negative_coordinates(self):
        from agents.sec208_drafter import Sec208DrafterAgent
        drafter = Sec208DrafterAgent()
        result = drafter.evaluate(
            camera_data={"device_id": "CAM-01", "lat": -90.0, "lon": -180.0},
            signage_detected=False,
        )
        assert "status" in result

    def test_very_long_device_id(self):
        from agents.sec208_drafter import Sec208DrafterAgent
        drafter = Sec208DrafterAgent()
        result = drafter.evaluate(
            camera_data={"device_id": "X" * 10_000, "lat": 12.9, "lon": 80.2},
            signage_detected=False,
        )
        assert "status" in result


# ──────────────────────────────────────────────────────────────────────────────
# 5. LegalRAGAgent — injection-style / adversarial queries
# ──────────────────────────────────────────────────────────────────────────────

class TestLegalRAGFuzzing:

    @pytest.fixture(scope="class")
    def agent(self):
        from agents.legal_rag import LegalRAGAgent
        a = LegalRAGAgent()
        a.load()
        return a

    @pytest.mark.parametrize("query", [
        "",                          # empty
        " " * 500,                   # whitespace only
        "'; DROP TABLE legal_statutes; --",   # SQL injection
        "<script>alert(1)</script>", # XSS attempt
        "\x00\x01\x02\x03",         # null bytes
        "A" * 10_000,               # huge input
        "நான் ஒரு மோட்டார் வாகனம்",  # Tamil Unicode
        "🚗💨🚦",                  # emoji
    ])
    def test_query_does_not_crash(self, agent, query):
        result = agent.query(query)
        assert "source" in result
        assert "results" in result
        assert isinstance(result["results"], list)


# ──────────────────────────────────────────────────────────────────────────────
# 6. BLEMeshMessage — truncated / corrupted bytes
# ──────────────────────────────────────────────────────────────────────────────

class TestBLEFuzzing:

    def test_from_bytes_empty_raises(self):
        from agents.ble_mesh_broker import MeshMessage
        with pytest.raises(Exception):
            MeshMessage.from_bytes(b"")

    def test_from_bytes_garbage(self):
        from agents.ble_mesh_broker import MeshMessage
        garbage = bytes(range(100))
        with pytest.raises(Exception):
            MeshMessage.from_bytes(garbage)

    def test_from_bytes_truncated_json(self):
        from agents.ble_mesh_broker import MeshMessage
        with pytest.raises(Exception):
            MeshMessage.from_bytes(b'{"msg_type": "H')

    def test_valid_message_within_mtu(self):
        from agents.ble_mesh_broker import MeshMessage, MsgType, HazardType
        msg = MeshMessage(
            msg_type=MsgType.HAZARD_ALERT,
            sender_id="node-fuzz",
            payload={
                "hazard_type": HazardType.POTHOLE,
                "lat": 12.924, "lon": 80.230,
                "severity": "HIGH", "confidence": 0.88,
            },
        )
        raw = msg.to_bytes()
        assert len(raw) <= 244


# ──────────────────────────────────────────────────────────────────────────────
# 7. IMUSample — NaN / Inf / extreme values must not crash detector
# ──────────────────────────────────────────────────────────────────────────────

class TestIMUFuzzing:

    def _make_detector(self):
        from agents.imu_near_miss_detector import NearMissDetector
        d = NearMissDetector()
        d.load()
        return d

    @pytest.mark.parametrize("ax,ay,az,gx,gy,gz", [
        (float("nan"), 0, 9.8, 0, 0, 0),
        (float("inf"), 0, 9.8, 0, 0, 0),
        (float("-inf"), 0, 9.8, 0, 0, 0),
        (1e308, 1e308, 1e308, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),          # all zeros
    ])
    def test_push_extreme_sample_no_crash(self, ax, ay, az, gx, gy, gz):
        import time
        from agents.imu_near_miss_detector import IMUSample, NearMissDetector
        detector = self._make_detector()
        t_ms = int(time.time() * 1000)
        # Must not raise; may return None or NearMissEvent
        try:
            detector.push_sample(IMUSample(t_ms, ax, ay, az, gx, gy, gz))
        except (ValueError, OverflowError, ZeroDivisionError):
            pass  # Acceptable to raise domain-level error; crash is not

    def test_push_negative_timestamp(self):
        from agents.imu_near_miss_detector import IMUSample, NearMissDetector
        detector = self._make_detector()
        sample = IMUSample(-1, 0.0, 0.0, 9.8, 0, 0, 0)
        try:
            detector.push_sample(sample)
        except (ValueError, OverflowError):
            pass


# ──────────────────────────────────────────────────────────────────────────────
# 8. Section208Resolver — corrupt / missing DB path
# ──────────────────────────────────────────────────────────────────────────────

class TestSection208ResolverFuzzing:

    def test_resolver_with_nonexistent_db(self):
        from section_208_resolver import Section208Resolver
        resolver = Section208Resolver(db_path="/nonexistent/path/does_not_exist.db")
        # Must fall back to statutory text, not raise
        text = resolver._lookup_statute("208")
        assert isinstance(text, str) and len(text) > 0

    def test_resolver_with_empty_db_path(self):
        from section_208_resolver import Section208Resolver
        resolver = Section208Resolver(db_path="")
        text = resolver._lookup_statute("208")
        assert isinstance(text, str)

    def test_resolver_sql_injection_section(self):
        from section_208_resolver import Section208Resolver
        resolver = Section208Resolver()
        # SQL injection in section parameter — must not crash or expose data
        text = resolver._lookup_statute("'; DROP TABLE legal_statutes; --")
        assert isinstance(text, str)
