"""
api/
SmartSalai Edge-Sentinel — REST API Layer

Endpoints:
  POST /api/v1/internal/ingest        — Receive vision/IMU telemetry events
  GET  /api/v1/fleet-routing-hazards  — Premium fleet routing hazard feed (auth required)
  POST /api/v1/webhook/razorpay       — Payment webhook (signature-verified)
"""
from .server import create_app

__all__ = ["create_app"]
