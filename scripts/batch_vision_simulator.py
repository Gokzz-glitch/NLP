import os
import cv2
import sys
from pathlib import Path
from tqdm import tqdm
from scripts.utils.vision_audit import VisionAuditEngine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.model_registry import resolve_pothole_onnx, resolve_traffic_signs_onnx

# [PERSONA 3: BATCH VISION AUDITOR]
# Automates the ingest and YOLO prediction for autonomous dashcam videos.

def batch_simulate():
    print("=========================================================")
    print(" EDGE-SENTINEL: AUTONOMOUS DUAL-MODEL PROCESSOR ")
    print("=========================================================")
    
    video_dir = Path("Testing videos/")
    out_dir = Path("runs/detect/specialized_sim/")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    videos = list(video_dir.glob("*.mp4")) + list(video_dir.glob("*.mkv")) + list(video_dir.glob("*.webm"))
    if not videos:
        print("Error: No videos found in Testing videos. Aborting batch process.")
        return
        
    print(f"Success: Found {len(videos)} autonomous driving test scenarios.")
    
    models = {
        "traffic": str(resolve_traffic_signs_onnx()),
        "pothole": str(resolve_pothole_onnx()),
    }
    
    print(f"Loading Dual Vision Engines (Pothole + Traffic)...\n")
    engine = VisionAuditEngine(models, conf_threshold=0.35)
    
    for i, vid in enumerate(videos, 1):
        print(f"--- [PROCESSSING SCENARIO {i}/{len(videos)}]: {vid.name} ---")
        
        cap = cv2.VideoCapture(str(vid))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        
        out_path = out_dir / vid.name
        # Use XVID since it plays well natively on Windows via .avi
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        # Change extension to .avi for compatibility
        out_path = out_path.with_suffix('.avi')
        out = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))
        
        frame_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        for _ in tqdm(range(frame_total), desc="Processing Frames"):
            ret, frame = cap.read()
            if not ret:
                break
                
            # Run our NPU ONNX pipelines
            detections = engine.run_hazard_audit(frame)
            
            # Overlay Bounding Boxes
            for model_name, model_dets in detections.items():
                for det in model_dets:
                    x1, y1, x2, y2 = map(int, det["box"])
                    cls_name = det["class_id"]
                    conf = det["confidence"]
                    
                    # Colors
                    if cls_name == "POTHOLE":
                        color = (0, 0, 255) # Red for Pothole hazards
                    else:
                        color = (255, 165, 0) # Orange for Traffic
                        
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    label = f"{cls_name} {conf:.2f}"
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            # Add HUD
            cv2.putText(frame, "SMARTSALAI EDGE DUAL-VISION ACTIVE", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            out.write(frame)
            
        cap.release()
        out.release()
        print(f"Video saved to: {out_path}")
            
    print("\n=========================================================")
    print(" BATCH SIMULATION COMPLETE.")
    print(" Output files saved directly to: runs/detect/specialized_sim/")
    print("=========================================================")

if __name__ == "__main__":
    batch_simulate()
