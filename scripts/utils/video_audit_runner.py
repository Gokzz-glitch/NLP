import cv2
import torch
import os
from pathlib import Path
import logging
from ultralytics import YOLO
import sys

ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from core.model_registry import resolve_yolo_general_pt, resolve_yolo_pothole_pt

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VideoAudit")

# Paths
ROOT_DIR = ROOT_PATH
VIDEO_SOURCE = ROOT_DIR / "raw_data/production_audit/ftglJqTnQ1Q.f134.mp4"
OUTPUT_PATH = ROOT_DIR / "dashboard/showcase/audit_demo.mp4"
POTHOLE_MODEL_PATH = resolve_yolo_pothole_pt()
GENERAL_MODEL_PATH = resolve_yolo_general_pt()

def run_video_audit(max_seconds=10):
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    logger.info(f"Using device: {device}")
    
    # Load models
    pothole_model = YOLO(str(POTHOLE_MODEL_PATH)).to(device)
    general_model = YOLO(str(GENERAL_MODEL_PATH)).to(device)
    
    # Open video
    cap = cv2.VideoCapture(str(VIDEO_SOURCE))
    if not cap.isOpened():
        logger.error(f"Could not open video: {VIDEO_SOURCE}")
        return
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    interval = int(fps) # 1 frame per second
    
    logger.info(f"Performing Keyframe Audit (1 frame/sec) for {max_seconds}s...")
    
    count = 0
    while cap.isOpened() and count < max_seconds * fps:
        ret, frame = cap.read()
        if not ret:
            break
            
        if count % interval == 0:
            sec = count // interval
            logger.info(f"Auditing second {sec}...")
            
            # Run inference
            res_p = pothole_model(frame, conf=0.25, verbose=False)[0]
            res_g = general_model(frame, conf=0.35, verbose=False)[0]
            
            # Draw results
            annotated = frame.copy()
            
            # Potholes
            for box in res_p.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 3)
                cv2.putText(annotated, "POTHOLE", (x1, y1-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                            
            # General
            for box in res_g.boxes:
                cls = int(box.cls[0])
                name = general_model.names[cls]
                if name in ['car', 'bus', 'truck', 'traffic light', 'stop sign', 'person']:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(annotated, name.upper(), (x1, y1-10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # Save frame
            out_name = f"video_audit_sec_{sec}.jpg"
            cv2.imwrite(str(ROOT_DIR / "dashboard/showcase" / out_name), annotated)

        count += 1

    cap.release()
    logger.info("Keyframe audit complete.")

if __name__ == "__main__":
    run_video_audit()
