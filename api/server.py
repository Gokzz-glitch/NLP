"""Primary production API server for Edge-Sentinel."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional, Set

from api.storage import APIDatabase
from core.secret_manager import get_manager
from core.tls_config import TLSConfig, https_redirect_middleware

logger = logging.getLogger("edge_sentinel.api")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Optional FastAPI import — graceful degradation so importing this module
# in unit tests does not fail if fastapi is not installed.
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response, status
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration (all secrets from env — never hardcoded)
# ---------------------------------------------------------------------------
_RAZORPAY_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
_PROCESS_START = time.time()
_HAZARD_DEFAULT_WINDOW_SEC = int(os.getenv("HAZARD_WINDOW_SEC", "1800"))
_HAZARD_DEFAULT_LIMIT = int(os.getenv("HAZARD_LIMIT", "200"))
_MIN_HAZARD_WINDOW_SEC = 60
_MAX_HAZARD_WINDOW_SEC = 24 * 3600
_MIN_HAZARD_LIMIT = 1
_MAX_HAZARD_LIMIT = 1000
_API_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "API_ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    ).split(",")
    if origin.strip()
]


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
        event: Optional[str] = None


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


def _verify_ingest_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _load_fleet_api_keys() -> Set[str]:
    raw = os.getenv("FLEET_API_KEYS", "")
    single = os.getenv("FLEET_API_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if single.strip():
        keys.append(single.strip())
    return set(keys)


def _extract_api_token(x_api_key: Optional[str], authorization: Optional[str]) -> str:
    if x_api_key:
        return x_api_key.strip()
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return auth


def _log_event(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "ts": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    logger.info(json.dumps(payload, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> "FastAPI":
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "fastapi is not installed. Run: pip install fastapi uvicorn"
        )

    @asynccontextmanager
    async def lifespan(app: "FastAPI"):
        app.state.db = APIDatabase(os.getenv("EDGE_SPATIAL_DB_PATH", "edge_spatial.db"))
        app.state.fleet_api_keys = _load_fleet_api_keys()
        app.state.db.migrate()
        _log_event(
            "api_startup",
            db_path=app.state.db.db_path,
            allowed_origins=_API_ALLOWED_ORIGINS,
            fleet_key_count=len(app.state.fleet_api_keys),
        )
        try:
            yield
        finally:
            app.state.db.close()
            _log_event("api_shutdown")

    app = FastAPI(
        title="SmartSalai Edge-Sentinel API",
        version="1.0.0",
        description="Internal telemetry ingest + fleet hazard routing API.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_API_ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Ingest-Signature", "X-Razorpay-Signature"],
    )
    app = https_redirect_middleware(app)

    ingest_secret = get_manager(strict_mode=False).get("INGEST_HMAC_SECRET", required=False)
    if not ingest_secret:
        ingest_secret = os.getenv("INGEST_HMAC_SECRET", "").strip()

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        response.headers["X-Request-ID"] = request_id
        _log_event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=elapsed_ms,
            client_ip=request.client.host if request.client else "unknown",
        )
        return response

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            "service": "edge-sentinel-api",
            "uptime_sec": int(time.time() - _PROCESS_START),
            "db_path": app.state.db.db_path,
        }

    @app.get("/api/metrics")
    async def metrics():
        counts = app.state.db.metrics_summary()
        return {
            "service": "edge-sentinel-api",
            "uptime_sec": int(time.time() - _PROCESS_START),
            "metrics": counts,
        }

    @app.post("/api/v1/internal/ingest", status_code=status.HTTP_201_CREATED)
    async def ingest_telemetry(
        request: Request,
        x_ingest_signature: Optional[str] = Header(None),
    ):
        """
        Receive a telemetry event from an edge node (dashcam / IMU sensor).
        Writes to the edge_spatial.db SQLite store (WAL mode).
        """
        if not ingest_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="INGEST_HMAC_SECRET is not configured.",
            )
        raw_payload = await request.body()
        if not _verify_ingest_signature(raw_payload, x_ingest_signature or "", ingest_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid ingest signature.",
            )
        try:
            payload_dict = json.loads(raw_payload.decode("utf-8"))
            payload = TelemetryIngestPayload(**payload_dict)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload.",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid telemetry payload.",
            ) from exc
        app.state.db.insert_telemetry(payload.model_dump())
        _log_event(
            "ingest_accepted",
            request_id=getattr(request.state, "request_id", ""),
            node_id=payload.node_id,
            event_type=payload.event_type,
            hazard_class=payload.hazard_class,
            confidence=payload.confidence,
        )
        return {
            "status": "ACCEPTED",
            "event_type": payload.event_type,
            "node_id": payload.node_id,
            "server_epoch_ms": int(time.time() * 1000),
        }

    @app.get("/api/v1/fleet-routing-hazards")
    async def fleet_routing_hazards(
        request: Request,
        x_api_key: Optional[str] = Header(None),
        authorization: Optional[str] = Header(None),
        window_seconds: int = _HAZARD_DEFAULT_WINDOW_SEC,
        limit: int = _HAZARD_DEFAULT_LIMIT,
    ):
        """
        Returns active hazard feed for fleet routing decisions.
        Accepts X-API-Key or Authorization: Bearer <token>.
        """
        token = _extract_api_token(x_api_key, authorization)
        if not token or token not in app.state.fleet_api_keys:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API token.",
            )
        safe_window = max(_MIN_HAZARD_WINDOW_SEC, min(window_seconds, _MAX_HAZARD_WINDOW_SEC))
        safe_limit = max(_MIN_HAZARD_LIMIT, min(limit, _MAX_HAZARD_LIMIT))
        hazards = app.state.db.query_recent_hazards(window_seconds=safe_window, limit=safe_limit)
        return {
            "hazards": hazards,
            "window_seconds": safe_window,
            "generated_at_epoch_ms": int(time.time() * 1000),
            "request_id": getattr(request.state, "request_id", ""),
        }

    @app.post("/api/v1/webhook/razorpay")
    async def razorpay_webhook(
        request: Request,
        payload: RazorpayWebhookPayload,
        x_razorpay_signature: Optional[str] = Header(None),
    ):
        """
        Razorpay payment webhook handler.
        Verifies HMAC-SHA256 signature before processing.
        """
        if not _RAZORPAY_SECRET:
            raise HTTPException(status_code=503, detail="RAZORPAY_WEBHOOK_SECRET not configured.")

        raw_payload = await request.body()
        if x_razorpay_signature:
            valid = _verify_webhook_signature(raw_payload, x_razorpay_signature, _RAZORPAY_SECRET)
        else:
            if not payload.razorpay_payment_id or not payload.razorpay_order_id or not payload.razorpay_signature:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing webhook signature fields.",
                )
            valid = _verify_razorpay_signature(
                payload.razorpay_order_id,
                payload.razorpay_payment_id,
                payload.razorpay_signature,
                _RAZORPAY_SECRET,
            )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Razorpay signature. Payment verification failed.",
            )
        _log_event(
            "webhook_verified",
            request_id=getattr(request.state, "request_id", ""),
            payment_id=payload.razorpay_payment_id,
            order_id=payload.razorpay_order_id,
            event=payload.event,
        )
        return {"status": "PAYMENT_VERIFIED", "payment_id": payload.razorpay_payment_id}

    return app


# ---------------------------------------------------------------------------
# ASGI app instance (used by uvicorn)
# ---------------------------------------------------------------------------
if FASTAPI_AVAILABLE:
    app = create_app()

if __name__ == "__main__" and FASTAPI_AVAILABLE:
    import uvicorn

    tls_config = TLSConfig()
    if tls_config.use_https:
        tls_config.validate()
        uvicorn.run(
            "api.server:app",
            host="0.0.0.0",
            port=int(os.getenv("API_PORT", "8000")),
            ssl_certfile=tls_config.cert_path,
            ssl_keyfile=tls_config.key_path,
        )
    else:
        uvicorn.run("api.server:app", host="0.0.0.0", port=int(os.getenv("API_PORT", "8000")))
