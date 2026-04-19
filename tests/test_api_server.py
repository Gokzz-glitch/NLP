import hashlib
import hmac
import importlib
import json

from fastapi.testclient import TestClient


def _load_server_module(monkeypatch, tmp_path):
    monkeypatch.setenv("API_USE_HTTPS", "false")
    monkeypatch.setenv("API_REQUIRE_HTTPS_REDIRECT", "false")
    monkeypatch.setenv("API_ALLOWED_ORIGINS", "http://localhost:8000")
    monkeypatch.setenv("CSRF_SECRET_KEY", "a" * 32)
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "b" * 32)
    monkeypatch.setenv("INGEST_HMAC_SECRET", "c" * 32)
    monkeypatch.setenv("FLEET_API_KEYS", "fleet-test-token")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "d" * 32)
    monkeypatch.setenv("EDGE_SPATIAL_DB_PATH", str(tmp_path / "edge_spatial.db"))

    import api.server as server_module

    return importlib.reload(server_module)


def test_ingest_and_hazard_feed(monkeypatch, tmp_path):
    server_module = _load_server_module(monkeypatch, tmp_path)
    with TestClient(server_module.app) as client:
        payload = {
            "node_id": "node-1",
            "event_type": "pothole_hazard",
            "hazard_class": "pothole",
            "confidence": 0.93,
            "gps_lat": 12.9,
            "gps_lon": 80.2,
        }
        raw = json.dumps(payload).encode("utf-8")
        signature = hmac.new(b"c" * 32, raw, hashlib.sha256).hexdigest()

        ingest_res = client.post(
            "/api/v1/internal/ingest",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Ingest-Signature": signature,
            },
        )
        assert ingest_res.status_code == 201

        hazards_res = client.get(
            "/api/v1/fleet-routing-hazards",
            headers={"X-API-Key": "fleet-test-token"},
        )
        assert hazards_res.status_code == 200
        body = hazards_res.json()
        assert len(body["hazards"]) >= 1
        assert body["hazards"][0]["hazard_class"] == "pothole"


def test_metrics_and_health(monkeypatch, tmp_path):
    server_module = _load_server_module(monkeypatch, tmp_path)
    with TestClient(server_module.app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        metrics = client.get("/api/metrics")
        assert metrics.status_code == 200
        assert "metrics" in metrics.json()
