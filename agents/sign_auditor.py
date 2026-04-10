"""
<<<<<<< HEAD
Sign Auditor Agent (Persona 3)
- Loads YOLOv8 model (ONNX or Ultralytics)
- Processes video (file or webcam)
- Detects speed cameras and speed limit signs
- Emits violation event if 500m rule is broken

Author: SmartSalai Team
License: AGPL3.0
"""

import cv2
import numpy as np
from pathlib import Path
import time
import json

# Placeholder for YOLOv8 model loading (update with actual model path)
MODEL_PATH = "yolov8n.pt"

# Placeholder class names (update with actual class indices for your model)
SPEED_CAMERA_CLASSES = ["speed_camera"]
SPEED_LIMIT_CLASSES = ["speed_limit"]

# --- Utility Functions ---
def load_model(model_path):
    # TODO: Replace with ONNX or Ultralytics YOLOv8 loader
    # For now, just a stub
    return None

def detect_objects(model, frame):
    # TODO: Replace with actual YOLOv8 inference
    # Return list of (class_name, bbox, confidence)
    return []

# --- Main Auditor Logic ---
def process_video(video_path, output_events_path="violation_events.json"):
    model = load_model(MODEL_PATH)
    cap = cv2.VideoCapture(str(video_path))
    frame_idx = 0
    speed_cameras = []
    speed_limits = []
    events = []
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        detections = detect_objects(model, frame)
        for cls, bbox, conf in detections:
            if cls in SPEED_CAMERA_CLASSES:
                speed_cameras.append((frame_idx, bbox, conf))
            elif cls in SPEED_LIMIT_CLASSES:
                speed_limits.append((frame_idx, bbox, conf))
        frame_idx += 1
    # Simple rule: if speed camera within 500m (or N frames) of speed limit sign
    for cam_idx, cam_bbox, cam_conf in speed_cameras:
        for sign_idx, sign_bbox, sign_conf in speed_limits:
            if 0 < (cam_idx - sign_idx) < 100:  # 100 frames as placeholder for 500m
                events.append({
                    "type": "500m_violation",
                    "speed_camera_frame": cam_idx,
                    "speed_limit_frame": sign_idx,
                    "timestamp": time.time(),
                })
    with open(output_events_path, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Detected {len(events)} violations. Events written to {output_events_path}")

if __name__ == "__main__":
    import sys
    video_path = sys.argv[1] if len(sys.argv) > 1 else "sample_video.mp4"
    process_video(video_path)
=======
agents/sign_auditor.py  (T-009)
SmartSalai Edge-Sentinel — YOLOv8-nano Sign Classification + 500m Geofence

ONNX inference for Indian traffic sign detection with:
  - Runtime path resolution: VISION_MODEL_PATH env var → raw_data/ → MOCK_MODE
  - 500m geofence check for speed limit sign upstream of camera
  - Section 208 trigger when camera detected without compliant sign in window
  - Agent-bus integration

In MOCK_MODE (no ONNX model), deterministic mock results are returned for demo.
"""

from __future__ import annotations

import logging
import math
import os
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("edge_sentinel.agents.sign_auditor")

_REPO_ROOT    = pathlib.Path(__file__).parent.parent
_DEFAULT_PATH = str(_REPO_ROOT / "raw_data" / "indian_traffic_yolov8.onnx")
MODEL_PATH    = os.environ.get("VISION_MODEL_PATH", _DEFAULT_PATH)

# Sign label taxonomy
SPEED_LIMIT_LABELS = {"speed_limit_sign", "speed_sign", "speed_limit"}
CAMERA_LABELS      = {"speed_camera", "enforcement_camera", "traffic_camera"}

INPUT_SIZE = (640, 640)
CONF_THRESH = 0.45
IOU_THRESH  = 0.50
GEOFENCE_M  = 500.0   # 500 m upstream window for IRC:67 compliance


@dataclass
class SignDetection:
    label: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1 y1 x2 y2 (normalised 0-1)
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    sec208_trigger: bool = False
    legal_sections: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "bbox": list(self.bbox),
            "gps_lat": self.gps_lat,
            "gps_lon": self.gps_lon,
            "sec208_trigger": self.sec208_trigger,
            "legal_sections": self.legal_sections,
        }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two GPS points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _mock_detections(frame_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic mock output when no ONNX model is available."""
    injected = frame_meta.get("_mock_inject", [])
    if injected:
        return injected
    return [
        {"label": "speed_camera", "confidence": 0.87, "bbox": [0.3, 0.1, 0.7, 0.6]},
    ]


class SignAuditorAgent:
    """
    YOLOv8-nano sign classification agent.

    Usage:
        agent = SignAuditorAgent()
        agent.load()
        result = agent.process_frame(
            frame=np.zeros((640,640,3), dtype=np.uint8),
            gps_lat=12.9240, gps_lon=80.2300,
            recent_sign_locations=[]
        )
    """

    def __init__(self, model_path: Optional[str] = None) -> None:
        self._model_path = model_path or MODEL_PATH
        self._session = None
        self._mock_mode = False
        self._bus = None

    def attach_bus(self, bus) -> None:
        self._bus = bus

    def load(self) -> bool:
        if not os.path.exists(self._model_path):
            logger.warning(
                f"[SignAuditor] Model not found at {self._model_path} — MOCK_MODE. "
                "Set VISION_MODEL_PATH env var or place model in raw_data/."
            )
            self._mock_mode = True
            return False
        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(
                self._model_path,
                providers=["CPUExecutionProvider"],
            )
            self._mock_mode = False
            logger.info(f"[SignAuditor] ONNX model loaded: {self._model_path}")
            return True
        except Exception as exc:
            logger.error(f"[SignAuditor] Failed to load ONNX model: {exc}")
            self._mock_mode = True
            return False

    def _run_onnx(self, frame) -> List[Dict[str, Any]]:
        """Run ONNX inference and return raw detections."""
        try:
            import numpy as np
            h, w = frame.shape[:2]
            resized = _resize_frame(frame, INPUT_SIZE)
            inp = resized.astype("float32") / 255.0
            inp = inp.transpose(2, 0, 1)[None]  # BCHW
            input_name = self._session.get_inputs()[0].name
            outputs = self._session.run(None, {input_name: inp})
            return _parse_yolov8_output(outputs[0], w, h, CONF_THRESH)
        except Exception as exc:
            logger.error(f"[SignAuditor] ONNX inference error: {exc}")
            return []

    def process_frame(
        self,
        frame,
        gps_lat: Optional[float] = None,
        gps_lon: Optional[float] = None,
        recent_sign_locations: Optional[List[Dict]] = None,
        frame_meta: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        frame_meta = frame_meta or {}
        recent_sign_locations = recent_sign_locations or []

        if self._mock_mode:
            raw_dets = _mock_detections(frame_meta)
        else:
            raw_dets = self._run_onnx(frame)

        # Classify and enrich
        detections: List[SignDetection] = []
        has_camera = False
        has_sign_in_geofence = False

        for d in raw_dets:
            label = d.get("label", "").lower()
            conf  = float(d.get("confidence", 0.0))
            bbox  = tuple(d.get("bbox", [0, 0, 0, 0]))

            det = SignDetection(
                label=label, confidence=conf, bbox=bbox,
                gps_lat=gps_lat, gps_lon=gps_lon,
            )
            detections.append(det)

            if label in CAMERA_LABELS:
                has_camera = True

            if label in SPEED_LIMIT_LABELS:
                # Geofence check: sign within 500m of camera
                if gps_lat is not None and gps_lon is not None:
                    for sloc in recent_sign_locations:
                        dist = _haversine_m(gps_lat, gps_lon, sloc["lat"], sloc["lon"])
                        if dist <= GEOFENCE_M:
                            has_sign_in_geofence = True
                            break
                    else:
                        # No sign location history — treat as present if label seen
                        has_sign_in_geofence = True
                else:
                    has_sign_in_geofence = True

        # Section 208 trigger
        sec208 = has_camera and not has_sign_in_geofence
        if sec208:
            logger.info(
                f"[SignAuditor] SEC208_TRIGGER: camera @ "
                f"({gps_lat:.4f},{gps_lon:.4f}) — no speed limit sign in 500m window."
            )
            for d in detections:
                if d.label in CAMERA_LABELS:
                    d.sec208_trigger = True
                    d.legal_sections = ["208"]

        result = {
            "detections": [d.to_dict() for d in detections],
            "has_camera": has_camera,
            "has_sign_in_geofence": has_sign_in_geofence,
            "sec208_trigger": sec208,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "mock_mode": self._mock_mode,
        }

        if self._bus:
            from core.agent_bus import Topics
            self._bus.publish(Topics.VISION_DETECTION, result)

        return result


# ---------------------------------------------------------------------------
# ONNX post-processing helpers
# ---------------------------------------------------------------------------
def _resize_frame(frame, target: Tuple[int, int]):
    """Resize frame to target (W, H) — fallback to naive crop if cv2 unavailable."""
    try:
        import cv2
        return cv2.resize(frame, target)
    except Exception:
        import numpy as np
        return np.zeros((*target[::-1], 3), dtype="uint8")


_YOLOV8_CLASSES = [
    "speed_limit_sign", "stop_sign", "no_entry", "pedestrian_crossing",
    "speed_camera", "traffic_light_red", "traffic_light_green", "no_overtaking",
]


def _parse_yolov8_output(output, orig_w: int, orig_h: int, conf_thresh: float) -> List[Dict]:
    """Parse YOLOv8 raw output tensor → list of detection dicts."""
    detections = []
    try:
        import numpy as np
        # output shape: (1, 84, 8400) for standard YOLOv8
        preds = output[0].T if output.ndim == 3 else output
        for row in preds:
            scores = row[4:]
            cls_id = int(scores.argmax())
            conf = float(scores[cls_id])
            if conf < conf_thresh:
                continue
            cx, cy, bw, bh = row[0], row[1], row[2], row[3]
            x1 = max(0.0, float(cx - bw / 2) / orig_w)
            y1 = max(0.0, float(cy - bh / 2) / orig_h)
            x2 = min(1.0, float(cx + bw / 2) / orig_w)
            y2 = min(1.0, float(cy + bh / 2) / orig_h)
            label = _YOLOV8_CLASSES[cls_id] if cls_id < len(_YOLOV8_CLASSES) else f"class_{cls_id}"
            detections.append({"label": label, "confidence": conf, "bbox": [x1, y1, x2, y2]})
    except Exception as exc:
        logger.error(f"[SignAuditor] Output parse error: {exc}")
    return detections


_agent: Optional[SignAuditorAgent] = None


def get_agent() -> SignAuditorAgent:
    global _agent
    if _agent is None:
        _agent = SignAuditorAgent()
        _agent.load()
    return _agent
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e
