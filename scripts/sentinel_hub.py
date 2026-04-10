import cv2
import asyncio
import os
import json
import base64
import time
import sys
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.sos_responder import SOSResponderAgent
from core.model_registry import resolve_yolo_general_pt, resolve_yolo_pothole_pt

app = FastAPI(title="SmartSalai Edge-Sentinel Hub")

# Configuration
MODEL_PATH = str(resolve_yolo_pothole_pt())
VIDEO_SOURCE = "video_sources.txt" # We'll use the first URL or a local file if provided

# Lazy-loaded runtime components to avoid blocking API startup.
model = None
auditor = None
sos_manager = SOSResponderAgent()


def ensure_runtime_components():
    global model, auditor
    if model is None:
        from ultralytics import YOLO
        print("🧠 LOADING SENTINEL VISION BRAIN...")
        try:
            model = YOLO(MODEL_PATH)
        except Exception:
            model = YOLO(str(resolve_yolo_general_pt()))
    if auditor is None:
        from scripts.audit_with_gemini import AIAuditor
        auditor = AIAuditor()

# Shared State
class SentinelState:
    def __init__(self):
        self.last_frame = None
        self.last_detections = []
        self.is_running = True

state = SentinelState()

def get_video_stream():
    """Generator for MJPEG stream of YOLO-processed frames."""
    ensure_runtime_components()
    cap = cv2.VideoCapture(0) # Default to webcam for 'Live' interaction
    if not cap.isOpened():
        # Fallback to a sample video if webcam isn't available
        cap = cv2.VideoCapture("raw_data/sample_road_v1.mp4")

    while state.is_running:
        success, frame = cap.read()
        if not success:
            break

        # 1. Inference (Student)
        results = model.predict(frame, conf=0.25, verbose=False)[0]
        state.last_frame = frame.copy()
        state.last_detections = []

        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            label = f"{results.names[cls_id]} {conf:.2f}"
            
            state.last_detections.append({"label": label, "rect": [x1, y1, x2, y2]})
            
            # Draw Production HUD Bounding Box
            color = (0, 255, 0) # Green for "Detected"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # 2. Encode for Streaming
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.get("/")
async def get_dashboard():
    dashboard_path = PROJECT_ROOT / "dashboard" / "index_interactive.html"
    if not dashboard_path.exists():
        return HTMLResponse(content="SmartSalai Sentinel Hub is running.", status_code=200)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(get_video_stream(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/trigger_sos")
async def trigger_sos():
    print("🚨 MANUAL SOS TRIGGERED FROM DASHBOARD!")
    result = sos_manager.initiate_emergency_protocol({
        "reason": "Manual dashboard SOS",
        "severity": "CRITICAL",
        "lat": 12.9716,
        "lon": 77.5946,
        "gps": "Live GPS (User Interaction)",
    })
    return {"status": "SOS_SENT", "log": result}

@app.post("/ask_teacher")
async def ask_teacher():
    """Captures the current frame and asks the Gemini Teacher for an audit."""
    ensure_runtime_components()
    if state.last_frame is not None:
        cv2.imwrite("raw_data/last_dashboard_frame.jpg", state.last_frame)
        print("🔬 REQUESTING TEACHER AUDIT OF CURRENT FRAME...")
        # Simulating the auditor call for the dashboard
        report = auditor.audit_single_frame("raw_data/last_dashboard_frame.jpg")
        return {"status": "AUDIT_COMPLETE", "reasoning": report}
    return {"status": "ERROR", "reasoning": "No frame captured."}


@app.get("/api/telemetry/health")
async def telemetry_health():
    telemetry_file = PROJECT_ROOT / "logs" / "telemetry_health.json"
    if telemetry_file.exists():
        try:
            return json.loads(telemetry_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "ERROR", "reason": f"Invalid telemetry snapshot: {exc}"}

    return {
        "status": "WARMING_UP",
        "reason": "No telemetry snapshot yet. Emit alerts and ACKs to initialize metrics.",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
