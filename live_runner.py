#!/usr/bin/env python3
"""
live_runner.py
SmartSalai Edge-Sentinel — Live Testing Entry Point

Starts the FastAPI server with the live camera/inference pipeline wired in.
Open http://localhost:8000/ in a browser to see the live dashboard.

Usage:
  python live_runner.py                         # camera 0, port 8000
  python live_runner.py --camera 1              # second USB camera
  python live_runner.py --camera 0 --port 8080  # custom port
  python live_runner.py --simulate              # GPS/IMU sim without camera
  python live_runner.py --gps-lat 13.082 --gps-lon 80.270  # start GPS position

Prerequisites (install once):
  pip install opencv-python onnxruntime fastapi uvicorn websockets

For YOLOv8n ONNX model (real detection — optional, mock works without it):
  python scripts/download_models.py

Camera connection guide:
  USB webcam        → plug in, index 0 (or 1 if laptop has built-in cam)
  360 camera (USB)  → most expose as UVC — same cv2.VideoCapture(index)
  Car camera chain  → USB-A female → USB-A male → USB-C → laptop
                      Verify with: python -c "import cv2; print(cv2.VideoCapture(0).isOpened())"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("smartsalai.runner")


def _gps_simulation_thread(host: str, port: int) -> None:
    """
    Pushes simulated GPS coordinates to the server's /api/v1/gps/update
    endpoint so the dashboard shows moving coordinates even without a real
    GPS device.  Simulates a ~30 km/h drive around Chennai.
    """
    import math
    try:
        import requests  # type: ignore[import]
    except ImportError:
        try:
            import urllib.request
            import json as _json

            def _post(url: str, data: dict) -> None:
                req = urllib.request.Request(
                    url,
                    data=_json.dumps(data).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=2)
            requests_post = _post
        except Exception:
            logger.warning("[GPS-SIM] Could not post GPS updates — no http client available.")
            return
    else:
        def requests_post(url: str, data: dict) -> None:  # type: ignore[misc]
            requests.post(url, json=data, timeout=2)

    base_lat, base_lon = 13.0827, 80.2707  # Chennai
    gps_url = f"http://localhost:{port}/api/v1/gps/update"
    step = 0
    logger.info("[GPS-SIM] GPS simulation thread started → %s", gps_url)

    # Wait for server to be ready
    time.sleep(2.0)

    while True:
        # Move ~5 m per tick (0.5 s interval) in a gentle arc
        angle_rad = math.radians(step * 3)
        radius_deg = 0.001  # ~111 m radius
        lat = base_lat + radius_deg * math.sin(angle_rad)
        lon = base_lon + radius_deg * math.cos(angle_rad)
        try:
            requests_post(gps_url, {"lat": lat, "lon": lon})
        except Exception as exc:
            logger.debug("[GPS-SIM] Post failed: %s", exc)
        step += 1
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SmartSalai Edge-Sentinel — Live Testing Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--camera", type=int, default=0,
                        help="Camera device index (default: 0)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Server bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Server port (default: 8000)")
    parser.add_argument("--simulate", action="store_true",
                        help="Simulate GPS movement; no real camera required")
    parser.add_argument("--gps-lat", type=float, default=13.0827,
                        help="Starting GPS latitude (default: 13.0827 — Chennai)")
    parser.add_argument("--gps-lon", type=float, default=80.2707,
                        help="Starting GPS longitude (default: 80.2707 — Chennai)")
    parser.add_argument("--log-level", default="info",
                        choices=["debug", "info", "warning", "error"],
                        help="Log verbosity (default: info)")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Configure environment before importing api.server
    # ------------------------------------------------------------------
    os.environ["LIVE_CAMERA_ENABLED"] = "0" if args.simulate else "1"
    os.environ["CAMERA_INDEX"]        = str(args.camera)
    os.environ["GPS_LAT"]             = str(args.gps_lat)
    os.environ["GPS_LON"]             = str(args.gps_lon)

    # ------------------------------------------------------------------
    # Pre-flight checks
    # ------------------------------------------------------------------
    try:
        import cv2  # noqa: F401
        logger.info("[PREFLIGHT] ✓ cv2 (OpenCV) available")
        if not args.simulate:
            cap = cv2.VideoCapture(args.camera)
            if cap.isOpened():
                logger.info("[PREFLIGHT] ✓ Camera %d opens successfully", args.camera)
                cap.release()
            else:
                logger.warning(
                    "[PREFLIGHT] ✗ Camera %d could not be opened. "
                    "Check USB connection or use --camera N for a different index.",
                    args.camera,
                )
    except ImportError:
        logger.warning(
            "[PREFLIGHT] ✗ cv2 not installed — camera stream unavailable. "
            "Install with: pip install opencv-python"
        )

    try:
        import onnxruntime  # noqa: F401
        logger.info("[PREFLIGHT] ✓ onnxruntime available — ONNX inference enabled")
    except ImportError:
        logger.warning(
            "[PREFLIGHT] ✗ onnxruntime not installed — vision inference in mock mode. "
            "Install with: pip install onnxruntime"
        )

    model_path = os.environ.get(
        "VISION_MODEL_PATH",
        os.path.join(os.path.dirname(__file__), "models", "vision", "indian_traffic_yolov8.onnx"),
    )
    if os.path.exists(model_path):
        logger.info("[PREFLIGHT] ✓ ONNX model found: %s", model_path)
    else:
        logger.warning(
            "[PREFLIGHT] ✗ ONNX model not found at %s. "
            "Run: python scripts/download_models.py   (or set VISION_MODEL_PATH)",
            model_path,
        )

    # ------------------------------------------------------------------
    # GPS simulation thread (optional)
    # ------------------------------------------------------------------
    if args.simulate:
        t = threading.Thread(
            target=_gps_simulation_thread,
            args=(args.host, args.port),
            daemon=True,
            name="gps_simulation",
        )
        t.start()
        logger.info("[GPS-SIM] Simulation thread started.")

    # ------------------------------------------------------------------
    # Launch uvicorn
    # ------------------------------------------------------------------
    logger.info(
        "[SERVER] Starting SmartSalai Edge-Sentinel on http://%s:%d/",
        "localhost" if args.host == "0.0.0.0" else args.host,
        args.port,
    )
    logger.info("[SERVER] Dashboard: http://localhost:%d/", args.port)
    logger.info("[SERVER] Video feed: http://localhost:%d/video_feed", args.port)
    logger.info("[SERVER] WebSocket:  ws://localhost:%d/ws/live", args.port)

    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        logger.error("uvicorn not installed. Run: pip install uvicorn")
        sys.exit(1)

    uvicorn.run(
        "api.server:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
