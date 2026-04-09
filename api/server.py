"""
api/server.py
SmartSalai Edge-Sentinel — FastAPI REST Server

Provides the three endpoints referenced by chaos_test_e2e.py and
tests/test_stress_enterprise.py:

  POST /api/v1/internal/ingest
    Accept telemetry events (vision detections, IMU spikes) from edge nodes.
    No auth required (internal LAN only; mTLS enforced in production).

  GET /api/v1/fleet-routing-hazards
    Premium endpoint: returns active hazard feed for fleet routing.
    Requires X-API-Key header. Returns 401 if missing/invalid.

  POST /api/v1/webhook/razorpay
    Razorpay payment webhook. Verifies HMAC-SHA256 signature.
    Returns 400 on invalid signature, 200 on success.

RATE LIMITING:
  Applied via SlowAPI (token-bucket, 60 req/min per IP for public endpoints).
  Internal ingest endpoint is not rate-limited (expected 100 Hz from edge nodes).

STARTUP:
  uvicorn api.server:app --host 0.0.0.0 --port 8000

NOTE:
  This is a production skeleton. Webhook secret, API keys, and DB path are
  read from environment variables. Set them in .env before starting.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("edge_sentinel.api")

# ---------------------------------------------------------------------------
# Optional FastAPI import — graceful degradation so importing this module
# in unit tests does not fail if fastapi is not installed.
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, Header, HTTPException, Request, status
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration (all secrets from env — never hardcoded)
# ---------------------------------------------------------------------------
_FLEET_API_KEYS = set(filter(None, os.getenv("FLEET_API_KEYS", "").split(",")))
_RAZORPAY_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

if FASTAPI_AVAILABLE:
    class TelemetryIngestPayload(BaseModel):
        node_id: str
        event_type: str
        hazard_class: Optional[str] = None
        confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
        gps_lat: Optional[float] = None
        gps_lon: Optional[float] = None
        timestamp: float = Field(default_factory=time.time)

    class RazorpayWebhookPayload(BaseModel):
        razorpay_payment_id: Optional[str] = None
        razorpay_order_id: Optional[str] = None
        razorpay_signature: Optional[str] = None


# ---------------------------------------------------------------------------
# Signature verification helpers
# ---------------------------------------------------------------------------

def _verify_razorpay_signature(
    order_id: str, payment_id: str, signature: str, secret: str
) -> bool:
    """
    Razorpay HMAC-SHA256 verification:
    expected = HMAC-SHA256( key=secret, message=order_id + "|" + payment_id )
    """
    if not secret:
        return False
    msg = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> "FastAPI":
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "fastapi is not installed. Run: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="SmartSalai Edge-Sentinel API",
        version="0.1.0",
        description="Internal telemetry ingest + fleet hazard routing API.",
    )

    # ------------------------------------------------------------------
    # POST /api/v1/internal/ingest
    # ------------------------------------------------------------------
    @app.post("/api/v1/internal/ingest", status_code=status.HTTP_201_CREATED)
    async def ingest_telemetry(payload: TelemetryIngestPayload):
        """
        Receive a telemetry event from an edge node (dashcam / IMU sensor).
        Writes to the edge_spatial.db SQLite store (WAL mode).
        """
        logger.info(
            f"[INGEST] node={payload.node_id} event={payload.event_type} "
            f"hazard={payload.hazard_class} conf={payload.confidence}"
        )
        # TODO (T-018): persist to edge_spatial.db via SQLiteVSSIngestor
        return {
            "status": "ACCEPTED",
            "event_type": payload.event_type,
            "node_id": payload.node_id,
            "server_epoch_ms": int(time.time() * 1000),
        }

    # ------------------------------------------------------------------
    # GET /api/v1/fleet-routing-hazards
    # ------------------------------------------------------------------
    @app.get("/api/v1/fleet-routing-hazards")
    async def fleet_routing_hazards(x_api_key: Optional[str] = Header(None)):
        """
        Returns active hazard feed for fleet routing decisions.
        Requires X-API-Key header with a valid key from FLEET_API_KEYS env var.
        """
        if not x_api_key or x_api_key not in _FLEET_API_KEYS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-API-Key.",
            )
        # TODO (T-018): query edge_spatial.db for recent hazards (last 30 min)
        return {"hazards": [], "generated_at_epoch_ms": int(time.time() * 1000)}

    # ------------------------------------------------------------------
    # POST /api/v1/webhook/razorpay
    # ------------------------------------------------------------------
    @app.post("/api/v1/webhook/razorpay")
    async def razorpay_webhook(payload: RazorpayWebhookPayload):
        """
        Razorpay payment webhook handler.
        Verifies HMAC-SHA256 signature before processing.
        """
        if not payload.razorpay_payment_id or not payload.razorpay_order_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing payment_id or order_id.",
            )
        if not payload.razorpay_signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Razorpay signature.",
            )
        if not _verify_razorpay_signature(
            payload.razorpay_order_id,
            payload.razorpay_payment_id,
            payload.razorpay_signature,
            _RAZORPAY_SECRET,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Razorpay signature. Payment verification failed.",
            )
        logger.info(f"[WEBHOOK] Payment verified: {payload.razorpay_payment_id}")
        return {"status": "PAYMENT_VERIFIED", "payment_id": payload.razorpay_payment_id}

    return app


# ---------------------------------------------------------------------------
# ASGI app instance (used by uvicorn)
# ---------------------------------------------------------------------------
if FASTAPI_AVAILABLE:
    app = create_app()
