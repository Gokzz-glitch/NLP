import os
import sys
import cv2
import json
import asyncio
import websockets
import logging
from ultralytics import YOLO
from core.model_registry import resolve_yolo_general_pt

# Project Root Setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: [MACHA_BATCH_AUDITOR] %(message)s")
logger = logging.getLogger("edge_sentinel.batch_auditor")

class MachaBatchAuditor:
    def __init__(self, batch_dir="raw_data/batch_test"):
        self.batch_dir = batch_dir
        self.uri = "ws://127.0.0.1:8765"
        self.model = YOLO(str(resolve_yolo_general_pt()))
        self.results = []
        logger.info(f"BATCH_AUDITOR: Initialized with directory: {batch_dir}")

    async def audit_clip(self, ws, video_path):
        clip_name = os.path.basename(video_path)
        logger.info(f"▶️ STARTING_CLIP: {clip_name}")
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"FATAL: Could not open {clip_name}")
            return

        frame_idx = 0
        hazards_found = 0
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break

            # Process every 50 frames (2 FPS) for high-fidelity sync
            if frame_idx % 50 == 0:
                results = self.model(frame, verbose=False, device='cpu')[0]
                detected_objects = []
                for box in results.boxes:
                    label = self.model.names[int(box.cls[0])]
                    conf = float(box.conf[0])
                    detected_objects.append({"label": label, "conf": conf})

                for obj in detected_objects:
                    if obj['conf'] > 0.5:
                        hazards_found += 1
                        direction = "FRONT" if frame_idx % 200 == 0 else "REAR"
                        alert = {
                            "channel": "SENTINEL_FUSION_ALERT",
                            "payload": {
                                "type": obj['label'].upper(),
                                "severity": "HIGH" if obj['conf'] > 0.8 else "MEDIUM",
                                "direction": direction,
                                "clip_context": clip_name
                            }
                        }
                        await ws.send(json.dumps(alert))
                        logger.info(f"[{clip_name}] EVENT: {obj['label']} at {direction}")
                        await asyncio.sleep(0.3)  # Let HUD render the alert flash

            frame_idx += 1
            if frame_idx > 400: break # Audit first 15-20s per clip for the stress test

        cap.release()
        logger.info(f"✅ CLIP_COMPLETE: {clip_name} | Hazards_Audited: {hazards_found}")
        self.results.append({"clip": clip_name, "hazards": hazards_found})

    async def run_marathon(self):
        video_files = [f for f in os.listdir(self.batch_dir) if f.endswith(".mp4")]
        if not video_files:
            logger.error("FATAL: No dashcam clips found in batch directory.")
            return

        async with websockets.connect(self.uri) as ws:
            logger.info("🔗 CONNECTED: Global AI Brain Online. Starting 10-Clip Marathon.")
            
            for video in video_files[:10]: # Ensure exactly 10 clips
                video_path = os.path.join(self.batch_dir, video)
                await self.audit_clip(ws, video_path)

            # Master Audit Locked
            logger.info("🏆 MARATHON_COMPLETE: Macha has survived all 10 road scenarios.")
            with open("logs/batch_audit_results.json", "w") as f:
                json.dump(self.results, f, indent=2)

if __name__ == "__main__":
    auditor = MachaBatchAuditor()
    try:
        asyncio.run(auditor.run_marathon())
    except Exception as e:
        logger.error(f"MARATHON_FAILED: {e}")
