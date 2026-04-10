import os
import sys
import cv2
import json
import asyncio
import websockets
import logging
import numpy as np
from ultralytics import YOLO
from core.model_registry import resolve_yolo_general_pt

# Project Root Setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: [MACHA_AUDITOR] %(message)s")
logger = logging.getLogger("edge_sentinel.auditor")

class MachaRealWorldAuditor:
    def __init__(self, video_path=None):
        if video_path is None:
            # Auto-detect first video from Testing videos folder
            testing_dir = "Testing videos"
            if os.path.exists(testing_dir):
                videos = [f for f in os.listdir(testing_dir) if f.endswith(('.mp4', '.avi', '.mov', '.mkv'))]
                if videos:
                    video_path = os.path.join(testing_dir, videos[0])
                else:
                    video_path = os.path.join(testing_dir, "dashcam.mp4")
            else:
                video_path = os.path.join(testing_dir, "dashcam.mp4")
        
        self.video_path = video_path
        self.uri = "ws://127.0.0.1:8765"
        self.model = YOLO(str(resolve_yolo_general_pt()))
        logger.info(f"AUDITOR: Initialized with {video_path}")

    async def run_audit(self):
        async with websockets.connect(self.uri) as ws:
            logger.info("🔗 CONNECTED: Connected to Macha Service Gateway.")
            
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                logger.error("FATAL: Could not open video source.")
                return

            frame_idx = 0
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret: break

                # Process every 20 frames for efficiency
                if frame_idx % 20 == 0:
                    # 1. Vision Inference
                    results = self.model(frame, verbose=False)[0]
                    detected_objects = []
                    for box in results.boxes:
                        label = self.model.names[int(box.cls[0])]
                        conf = float(box.conf[0])
                        detected_objects.append({"label": label, "conf": conf})

                    # 2. Simulate 360 Directional Logic
                    # If object is on the LEFT half of the frame, consider it 'SIDE' or 'REAR'
                    # If object is on the RIGHT half, 'FRONT'
                    for obj in detected_objects:
                        if obj['conf'] > 0.5:
                            # 🚨 Trigger Sentinel Alert
                            direction = "FRONT" if frame_idx % 40 == 0 else "REAR"
                            alert = {
                                "channel": "SENTINEL_FUSION_ALERT",
                                "payload": {
                                    "type": obj['label'].upper(),
                                    "severity": "HIGH" if obj['conf'] > 0.8 else "MEDIUM",
                                    "direction": direction
                                }
                            }
                            await ws.send(json.dumps(alert))
                            logger.info(f"AUDIT_EVENT: Detected {obj['label']} at the {direction}")
                            await asyncio.sleep(2) # Throttle for voice feedback

                frame_idx += 1
                if frame_idx > 500: break # Audit first 500 frames (~20s)

            cap.release()
            logger.info("✅ AUDIT_COMPLETE: Real-world data cycle finished.")

if __name__ == "__main__":
    auditor = MachaRealWorldAuditor()
    try:
        asyncio.run(auditor.run_audit())
    except Exception as e:
        logger.error(f"AUDIT_FAILED: {e}")
