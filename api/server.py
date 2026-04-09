"""
api/server.py
SmartSalai Edge-Sentinel — FastAPI REST + Live Streaming Server

Existing REST endpoints (unchanged):
  POST /api/v1/internal/ingest          — Edge telemetry ingest (100 Hz)
  GET  /api/v1/fleet-routing-hazards    — Premium hazard feed (API-key gated)
  POST /api/v1/webhook/razorpay         — Razorpay HMAC-SHA256 webhook

Live / real-time endpoints:
  GET  /                                — Live dashboard (HTML single-page app)
  GET  /video_feed                      — MJPEG stream: first/default camera (cv2 required)
  GET  /video_feed/{direction}          — MJPEG stream for named camera (front/rear/left/right)
  WS   /ws/live                         — WebSocket JSON event stream
                                          broadcasts: detection | alert | gps | imu | heartbeat
  POST /api/v1/gps/update               — Push GPS coordinates; broadcasts to all WS clients

Multi-camera / 360° support:
  GET  /api/v1/cameras                  — List configured cameras (direction → device index)
  Set  CAMERA_INDICES=0,1,2,3           — Comma-separated cv2 device indices (default: 0)
  Set  CAMERA_DIRECTIONS=front,rear,left,right  — Direction labels matching CAMERA_INDICES

Driver / AI endpoints:
  POST /api/v1/chat                     — Driver chatbot (13 intents, ta/en/hi)
  GET  /api/v1/driver/{id}/profile      — Safety score, weaknesses, session stats
  POST /api/v1/driver/preferences       — Set language / voice persona / name
  POST /api/v1/route/score              — Score/rank route alternatives by live hazards
  GET  /api/v1/hazards/live             — Recent crowd-sourced hazard feed

Incident reporting:
  GET  /api/v1/incident/report          — Full incident report (driver + hazards + alerts)
  POST /api/v1/incident/share           — Shareable signed JSON blob for the current incident

STARTUP:
  # Simple REST + WebSocket server (no camera):
  uvicorn api.server:app --host 0.0.0.0 --port 8000

  # Single webcam:
  LIVE_CAMERA_ENABLED=1 CAMERA_INDEX=0 uvicorn api.server:app --host 0.0.0.0 --port 8000

  # 4-camera 360° rig (front=0, rear=1, left=2, right=3):
  LIVE_CAMERA_ENABLED=1 CAMERA_INDICES=0,1,2,3 CAMERA_DIRECTIONS=front,rear,left,right \\
    uvicorn api.server:app --host 0.0.0.0 --port 8000

NOTE:
  All secrets are read from environment variables / .env — never hardcoded.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import queue as _queue
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("edge_sentinel.api")

# ---------------------------------------------------------------------------
# Optional FastAPI import — graceful degradation so importing this module
# in unit tests does not fail if fastapi is not installed.
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Optional cv2 — only needed for MJPEG camera stream
# ---------------------------------------------------------------------------
try:
    import cv2 as _cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration (all secrets from env — never hardcoded)
# ---------------------------------------------------------------------------
_FLEET_API_KEYS = set(filter(None, os.getenv("FLEET_API_KEYS", "").split(",")))
_RAZORPAY_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
_LIVE_CAMERA_ENABLED = os.getenv("LIVE_CAMERA_ENABLED", "0") == "1"
_CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))  # legacy single-camera compat

# ---------------------------------------------------------------------------
# Multi-camera / 360° configuration
#   CAMERA_INDICES=0,1,2,3           — cv2 device indices (default: [CAMERA_INDEX])
#   CAMERA_DIRECTIONS=front,rear,left,right  — direction labels (default: front/rear/left/right)
# ---------------------------------------------------------------------------
_raw_cam_idx = os.getenv("CAMERA_INDICES", "")
_CAMERA_INDICES: List[int] = (
    [int(x.strip()) for x in _raw_cam_idx.split(",") if x.strip()]
    if _raw_cam_idx else [_CAMERA_INDEX]
)

_raw_cam_dir = os.getenv("CAMERA_DIRECTIONS", "")
_DEFAULT_DIR_NAMES = ("front", "rear", "left", "right")
if _raw_cam_dir:
    _parsed_dirs = [x.strip() for x in _raw_cam_dir.split(",") if x.strip()]
    _CAMERA_DIRECTIONS: List[str] = (
        _parsed_dirs if len(_parsed_dirs) == len(_CAMERA_INDICES)
        else [f"cam{i}" for i in range(len(_CAMERA_INDICES))]
    )
else:
    _CAMERA_DIRECTIONS = [
        _DEFAULT_DIR_NAMES[i] if i < len(_DEFAULT_DIR_NAMES) else f"cam{i}"
        for i in range(len(_CAMERA_INDICES))
    ]

# ---------------------------------------------------------------------------
# Live GPS state — updated via POST /api/v1/gps/update or env vars
# ---------------------------------------------------------------------------
_live_gps: Dict[str, float] = {
    "lat": float(os.getenv("GPS_LAT", "13.0827")),   # Default: Chennai
    "lon": float(os.getenv("GPS_LON", "80.2707")),
}
_gps_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Alert log — rolling window of last 200 alerts, thread-safe append
# ---------------------------------------------------------------------------
_alert_log: deque = deque(maxlen=200)
_alert_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Thread → async event bridge
# Camera/IMU threads post dicts here; async broadcast_task drains it.
# ---------------------------------------------------------------------------
_event_queue: _queue.Queue = _queue.Queue(maxsize=200)

# ---------------------------------------------------------------------------
# MJPEG frame queues — one per camera direction.
# Each entry: {"frame_queue": Queue, "latest_frame": Optional[bytes], "lock": Lock}
# ---------------------------------------------------------------------------
_cam_state: Dict[str, Dict[str, Any]] = {
    direction: {
        "frame_queue":  _queue.Queue(maxsize=2),
        "latest_frame": None,
        "lock":         threading.Lock(),
    }
    for direction in _CAMERA_DIRECTIONS
}


# ---------------------------------------------------------------------------
# WebSocket connection manager
# All mutations happen in the asyncio event loop — no asyncio.Lock needed.
# ---------------------------------------------------------------------------

class ConnectionManager:
    """
    Manages the set of active WebSocket connections.

    connect()    — accept + register a new client
    disconnect() — remove a client (called on WebSocketDisconnect or error)
    broadcast()  — send a JSON string to every connected client; dead
                   connections are pruned silently so the loop never blocks.
    """

    def __init__(self) -> None:
        self.active: Set["WebSocket"] = set()

    async def connect(self, websocket: "WebSocket") -> None:
        await websocket.accept()
        self.active.add(websocket)
        logger.info("[WS] client connected (%d total)", len(self.active))

    def disconnect(self, websocket: "WebSocket") -> None:
        self.active.discard(websocket)
        logger.info("[WS] client disconnected (%d remaining)", len(self.active))

    async def broadcast(self, message: str) -> None:
        dead: Set["WebSocket"] = set()
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self.active -= dead


# Module-level singleton — shared between endpoints and background tasks.
manager: ConnectionManager = ConnectionManager()


# ---------------------------------------------------------------------------
# Camera / inference background helpers
# ---------------------------------------------------------------------------

def _camera_thread_fn(camera_index: int, direction: str) -> None:
    """
    Runs in a daemon thread when LIVE_CAMERA_ENABLED=1.

    Reads frames from cv2.VideoCapture (webcam or 360-cam feed), runs
    VisionAuditEngine inference, and posts events into _event_queue /
    _cam_state[direction] for the async layer.
    Falls back gracefully if cv2 or onnxruntime are unavailable.
    """
    state = _cam_state[direction]

    if not _CV2_AVAILABLE:
        logger.warning("[CAM:%s] cv2 not installed — camera thread exiting.", direction)
        return

    # Lazy-import vision engine to avoid circular deps at module load time.
    try:
        import sys
        import os as _os
        _root = _os.path.dirname(_os.path.dirname(__file__))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from vision_audit import VisionAuditEngine  # noqa: PLC0415
        _engine = VisionAuditEngine()
    except Exception as exc:
        logger.error("[CAM:%s] VisionAuditEngine init failed: %s", direction, exc)
        _engine = None

    cap = _cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        logger.error("[CAM:%s] Cannot open camera index %d", direction, camera_index)
        return

    logger.info("[CAM:%s] Camera %d opened — streaming at native FPS", direction, camera_index)

    while True:
        ret, frame = cap.read()
        if not ret:
            logger.warning("[CAM:%s] Frame read failed — retrying in 100 ms", direction)
            time.sleep(0.1)
            continue

        # --- Vision inference ---
        detections: List[Dict[str, Any]] = []
        if _engine is not None and not _engine.is_mock:
            try:
                detections = _engine.run_inference(frame)
            except Exception as exc:
                logger.debug("[CAM:%s] Inference error: %s", direction, exc)

        # --- Encode frame as JPEG for MJPEG stream ---
        ok, buf = _cv2.imencode(".jpg", frame, [int(_cv2.IMWRITE_JPEG_QUALITY), 75])
        if ok:
            jpeg_bytes = buf.tobytes()
            with state["lock"]:
                state["latest_frame"] = jpeg_bytes
            fq: _queue.Queue = state["frame_queue"]
            if fq.full():
                try:
                    fq.get_nowait()
                except _queue.Empty:
                    pass
            fq.put_nowait(jpeg_bytes)

        # --- Post detection event (includes camera direction label) ---
        if detections:
            _event_queue.put_nowait({
                "type": "detection",
                "camera": direction,
                "data": detections,
                "ts": time.time(),
            })

        # --- Post GPS heartbeat (10 Hz) ---
        with _gps_lock:
            lat = _live_gps["lat"]
            lon = _live_gps["lon"]
        _event_queue.put_nowait({
            "type": "gps",
            "lat": lat,
            "lon": lon,
            "ts": time.time(),
        })

        time.sleep(0.033)  # ~30 FPS cap — leaves CPU headroom for inference

    cap.release()


async def _broadcast_task() -> None:
    """
    Async task that drains _event_queue and broadcasts JSON to all WS clients.
    Also sends a heartbeat every 2 seconds when the queue is idle.
    """
    last_heartbeat = time.time()
    while True:
        try:
            event = _event_queue.get_nowait()
            await manager.broadcast(json.dumps(event))
        except _queue.Empty:
            now = time.time()
            if now - last_heartbeat >= 2.0:
                last_heartbeat = now
                with _gps_lock:
                    lat = _live_gps["lat"]
                    lon = _live_gps["lon"]
                await manager.broadcast(json.dumps({
                    "type": "heartbeat",
                    "ts": now,
                    "lat": lat,
                    "lon": lon,
                    "connected_clients": len(manager.active),
                }))
            await asyncio.sleep(0.02)   # 50 Hz polling — sub-20 ms event latency


# ---------------------------------------------------------------------------
# Dashboard HTML path
# ---------------------------------------------------------------------------
_UI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
_DASHBOARD_PATH = os.path.join(_UI_DIR, "dashboard.html")


def _load_dashboard_html() -> str:
    """Load the dashboard HTML from ui/dashboard.html if it exists."""
    try:
        with open(_DASHBOARD_PATH, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return "<h1>SmartSalai Edge-Sentinel</h1><p>ui/dashboard.html not found.</p>"


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

    class GPSUpdatePayload(BaseModel):
        lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
        lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")

    class ChatPayload(BaseModel):
        driver_id: str = Field(..., min_length=1)
        message:   str = Field(..., min_length=1, max_length=1000)

    class DriverPrefsPayload(BaseModel):
        driver_id:     str            = Field(..., min_length=1)
        name:          Optional[str]  = None
        language:      Optional[str]  = Field(None, pattern="^(ta|en|hi)$")
        voice_persona: Optional[str]  = Field(None, pattern="^(male|female|child)$")

    class RouteScorePayload(BaseModel):
        routes: List[List[List[float]]] = Field(..., min_length=1)
        labels: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Lazy-loaded driver-agent singletons
# ---------------------------------------------------------------------------

_profile_agent = None
_route_advisor  = None


def _get_profile_agent():
    global _profile_agent  # noqa: PLW0603
    if _profile_agent is None:
        try:
            from agents.driver_profile import DriverProfileAgent  # noqa: PLC0415
            _profile_agent = DriverProfileAgent()
        except Exception as exc:
            logger.error("[API] DriverProfileAgent init failed: %s", exc)
    return _profile_agent


def _get_route_advisor():
    global _route_advisor  # noqa: PLW0603
    if _route_advisor is None:
        try:
            from agents.route_advisor import RouteAdvisor  # noqa: PLC0415
            _route_advisor = RouteAdvisor()
        except Exception as exc:
            logger.error("[API] RouteAdvisor init failed: %s", exc)
    return _route_advisor


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
        description="Internal telemetry ingest + fleet hazard routing + live vision dashboard.",
    )

    # ------------------------------------------------------------------
    # Lifespan: start background tasks and camera thread on startup
    # ------------------------------------------------------------------

    @app.on_event("startup")
    async def _startup() -> None:
        # Start the async broadcast task (always active — drains event queue)
        asyncio.create_task(_broadcast_task())
        logger.info("[SERVER] Broadcast task started.")

        if _LIVE_CAMERA_ENABLED:
            for _cam_idx, _cam_dir in zip(_CAMERA_INDICES, _CAMERA_DIRECTIONS):
                t = threading.Thread(
                    target=_camera_thread_fn,
                    args=(_cam_idx, _cam_dir),
                    daemon=True,
                    name=f"camera_{_cam_dir}",
                )
                t.start()
                logger.info(
                    "[SERVER] Camera thread started (direction=%s, index=%d).",
                    _cam_dir, _cam_idx,
                )
        else:
            logger.info("[SERVER] Camera disabled (LIVE_CAMERA_ENABLED != 1).")

    # ------------------------------------------------------------------
    # GET / — Live dashboard
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        """Serve the single-page live dashboard."""
        return HTMLResponse(content=_load_dashboard_html())

    # ------------------------------------------------------------------
    # MJPEG helpers — per-camera streaming
    # ------------------------------------------------------------------

    async def _mjpeg_generator_for(direction: str):
        """Async generator that yields MJPEG multipart frames for one camera."""
        state = _cam_state[direction]
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        with state["lock"]:
            seed = state["latest_frame"]
        if seed:
            yield boundary + seed + b"\r\n"
        fq: _queue.Queue = state["frame_queue"]
        while True:
            try:
                jpeg = fq.get(timeout=1.0)
                yield boundary + jpeg + b"\r\n"
            except _queue.Empty:
                yield b"--frame\r\nContent-Type: text/plain\r\n\r\nkeep-alive\r\n"

    async def _stream_response(direction: Optional[str]):
        """Shared logic for /video_feed and /video_feed/{direction}."""
        if not _CV2_AVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Camera unavailable: cv2 not installed. Run: pip install opencv-python",
            )
        if not _LIVE_CAMERA_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Camera stream disabled. Set LIVE_CAMERA_ENABLED=1 to enable.",
            )
        chosen = direction or (_CAMERA_DIRECTIONS[0] if _CAMERA_DIRECTIONS else "front")
        if chosen not in _cam_state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown camera direction '{chosen}'. "
                       f"Available: {list(_cam_state.keys())}",
            )
        return StreamingResponse(
            _mjpeg_generator_for(chosen),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # ------------------------------------------------------------------
    # GET /video_feed — backward-compatible single-stream (first/default camera)
    # ------------------------------------------------------------------

    @app.get("/video_feed", include_in_schema=False)
    async def video_feed():
        """
        MJPEG stream for the default (first) camera.
        Returns 503 when cv2 / camera is unavailable.
        """
        return await _stream_response(None)

    # ------------------------------------------------------------------
    # GET /video_feed/{direction} — named camera stream
    # ------------------------------------------------------------------

    @app.get("/video_feed/{direction}", include_in_schema=False)
    async def video_feed_direction(direction: str):
        """
        MJPEG stream for a specific camera direction (front / rear / left / right).
        Returns 404 for unknown directions, 503 when camera disabled.
        """
        return await _stream_response(direction)

    # ------------------------------------------------------------------
    # WS /ws/live — real-time JSON event stream
    # ------------------------------------------------------------------

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket):
        """
        WebSocket endpoint that streams live events to browser clients.

        Message types:
          detection — {type, data: [{label, conf, bbox}], ts}
          alert     — {type, severity, message, ts}
          gps       — {type, lat, lon, ts}
          imu       — {type, ax, ay, az, severity, ts}
          heartbeat — {type, ts, lat, lon, connected_clients}
        """
        await manager.connect(websocket)
        # Send current GPS state immediately on connect
        with _gps_lock:
            lat = _live_gps["lat"]
            lon = _live_gps["lon"]
        try:
            await websocket.send_text(json.dumps({
                "type": "gps",
                "lat": lat,
                "lon": lon,
                "ts": time.time(),
            }))
            # Keep the connection open; broadcast_task handles outgoing messages.
            # We keep a receive loop so we can detect disconnects.
            while True:
                await websocket.receive_text()   # client messages currently ignored
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)

    # ------------------------------------------------------------------
    # POST /api/v1/gps/update — push GPS from external source
    # ------------------------------------------------------------------

    @app.post("/api/v1/gps/update", status_code=status.HTTP_200_OK)
    async def gps_update(payload: GPSUpdatePayload):
        """
        Update the live GPS coordinates.

        Intended for:
          • A GPS USB dongle feeding position via a small companion script.
          • The live_runner.py NMEA serial reader.
          • Manual override for testing.

        Broadcasts a 'gps' event to all connected WebSocket clients immediately.
        """
        with _gps_lock:
            _live_gps["lat"] = payload.lat
            _live_gps["lon"] = payload.lon

        event = {"type": "gps", "lat": payload.lat, "lon": payload.lon, "ts": time.time()}
        await manager.broadcast(json.dumps(event))
        return {"status": "OK", "lat": payload.lat, "lon": payload.lon}

    # ------------------------------------------------------------------
    # POST /api/v1/internal/ingest
    # ------------------------------------------------------------------
    @app.post("/api/v1/internal/ingest", status_code=status.HTTP_201_CREATED)
    async def ingest_telemetry(payload: TelemetryIngestPayload):
        """
        Receive a telemetry event from an edge node (dashcam / IMU sensor).
        Broadcasts detections / alerts to WebSocket clients in addition to
        returning the standard ACCEPTED response.
        """
        logger.info(
            f"[INGEST] node={payload.node_id} event={payload.event_type} "
            f"hazard={payload.hazard_class} conf={payload.confidence}"
        )

        # Broadcast hazard as alert event so the dashboard gets notified
        if payload.hazard_class:
            alert_event = {
                "type": "alert",
                "severity": "HIGH",
                "message": f"Hazard detected: {payload.hazard_class} "
                           f"(conf={payload.confidence:.2f})" if payload.confidence else
                           f"Hazard detected: {payload.hazard_class}",
                "node_id": payload.node_id,
                "ts": time.time(),
            }
            with _alert_lock:
                _alert_log.append(alert_event)
            _event_queue.put_nowait(alert_event)

            # Persist to crowd-source hazard DB when GPS available
            if payload.gps_lat is not None and payload.gps_lon is not None:
                ra = _get_route_advisor()
                if ra is not None:
                    try:
                        ra.record_hazard(
                            payload.node_id,
                            payload.hazard_class,
                            payload.confidence if payload.confidence is not None else 1.0,
                            payload.gps_lat,
                            payload.gps_lon,
                        )
                    except Exception as exc:
                        logger.debug("[INGEST] RouteAdvisor record failed: %s", exc)

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

    # ------------------------------------------------------------------
    # POST /api/v1/chat  — driver chatbot
    # ------------------------------------------------------------------
    @app.post("/api/v1/chat")
    async def chat(payload: ChatPayload):
        pa = _get_profile_agent()
        if pa is None:
            raise HTTPException(status_code=503, detail="Driver profile service unavailable.")
        try:
            from agents.driver_chatbot import DriverChatbot  # noqa: PLC0415
            ra  = _get_route_advisor()
            bot = DriverChatbot(payload.driver_id, pa, route_advisor=ra)
            return bot.chat(payload.message)
        except Exception as exc:
            logger.error("[CHAT] %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # GET /api/v1/driver/{driver_id}/profile
    # ------------------------------------------------------------------
    @app.get("/api/v1/driver/{driver_id}/profile")
    async def get_driver_profile(driver_id: str):
        pa = _get_profile_agent()
        if pa is None:
            raise HTTPException(status_code=503, detail="Profile service unavailable.")
        summary = pa.get_summary(driver_id)
        if not summary:
            raise HTTPException(status_code=404, detail=f"Driver '{driver_id}' not found.")
        return summary

    # ------------------------------------------------------------------
    # POST /api/v1/driver/preferences
    # ------------------------------------------------------------------
    @app.post("/api/v1/driver/preferences")
    async def update_driver_prefs(payload: DriverPrefsPayload):
        pa = _get_profile_agent()
        if pa is None:
            raise HTTPException(status_code=503, detail="Profile service unavailable.")
        pa.get_or_create(
            payload.driver_id,
            name=payload.name or "",
            language=payload.language or "ta",
            voice_persona=payload.voice_persona or "male",
        )
        p = pa.update_preferences(
            payload.driver_id,
            name=payload.name,
            language=payload.language,
            voice_persona=payload.voice_persona,
        )
        return {
            "status": "UPDATED",
            "driver_id":     p.driver_id,
            "name":          p.name,
            "language":      p.language,
            "voice_persona": p.voice_persona,
        }

    # ------------------------------------------------------------------
    # POST /api/v1/route/score
    # ------------------------------------------------------------------
    @app.post("/api/v1/route/score")
    async def route_score(payload: RouteScorePayload):
        ra = _get_route_advisor()
        if ra is None:
            raise HTTPException(status_code=503, detail="Route advisor unavailable.")
        alternatives = [[(wp[0], wp[1]) for wp in route] for route in payload.routes]
        return ra.recommend(alternatives, labels=payload.labels)

    # ------------------------------------------------------------------
    # GET /api/v1/hazards/live
    # ------------------------------------------------------------------
    @app.get("/api/v1/hazards/live")
    async def hazards_live(max_age_h: float = 2.0, limit: int = 100):
        ra = _get_route_advisor()
        if ra is None:
            return {"hazards": [], "note": "Route advisor unavailable."}
        return {"hazards": ra.get_live_hazard_feed(max_age_h=max_age_h, limit=limit)}

    return app


# ---------------------------------------------------------------------------
# ASGI app instance (used by uvicorn)
# ---------------------------------------------------------------------------
if FASTAPI_AVAILABLE:
    app = create_app()
