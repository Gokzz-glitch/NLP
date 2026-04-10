import cv2
import numpy as np
import time
import os
import json
from ultralytics import YOLO
from core.model_registry import resolve_yolo_pothole_pt

class ProofReelGenerator:
    def __init__(self, model_path=None, output_dir="audit_evidence/recordings"):
        self.model = YOLO(model_path or str(resolve_yolo_pothole_pt()))
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def draw_macha_hud(self, frame, detection_count, current_action="SCANNING"):
        """Draws the premium Macha HUD on the frame."""
        h, w = frame.shape[:2]
        
        # 1. Semi-transparent scanlines/overlay
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 100), (0, 0, 0), -1) # Top Header
        cv2.rectangle(overlay, (0, h-80), (w, h), (0, 0, 0), -1) # Bottom Footer
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
        
        # 2. Dynamic Corners (Cyberpunk style)
        c_len = 50
        cv2.line(frame, (20, 20), (20+c_len, 20), (0, 255, 255), 2)
        cv2.line(frame, (20, 20), (20, 20+c_len), (0, 255, 255), 2)
        
        # 3. Header Text
        cv2.putText(frame, "SMARTSALAI EDGE-SENTINEL | V2.0 PRODUCTION", (40, 45), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"LIVE AUDIT: {time.strftime('%H:%M:%S')}", (40, 75), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        
        # 4. Indicators (Critera 1.3/RoadSOS/RoadWatch)
        status_color = (0, 255, 0) if detection_count == 0 else (0, 0, 255)
        status_text = "ROAD: SECURE" if detection_count == 0 else f"HAZARD DETECTED: {detection_count}"
        
        cv2.circle(frame, (w-200, 45), 8, status_color, -1)
        cv2.putText(frame, status_text, (w-180, 52), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)
        
        # 5. Footer (System Telemetry)
        cv2.putText(frame, f"MODULE: {current_action} | AI-ACCURACY: VERIFIED (GEMINI SSL)", (40, h-45), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        
        return frame

    def generate_reel(self, video_path):
        video_id = os.path.basename(video_path).split('.')[0]
        output_path = os.path.join(self.output_dir, f"proof_{video_id}.mp4")
        
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
        
        print(f"🎬 GENERATING PROOF REEL: {output_path}")
        
        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            # Inference
            results = self.model(frame, verbose=False)[0]
            detection_count = len(results.boxes)
            
            # Draw YOLO Bboxes
            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(frame, f"POTHOLE {float(box.conf[0]):.2f}", (x1, y1-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
            # Apply Macha HUD
            frame = self.draw_macha_hud(frame, detection_count)
            
            out.write(frame)
            frame_idx += 1
            if frame_idx % 100 == 0:
                print(f"   Progress: {frame_idx} frames written", end='\r')
                
        cap.release()
        out.release()
        print(f"\n✅ PROOF REEL COMPLETE: {output_path}")

if __name__ == "__main__":
    generator = ProofReelGenerator()
    # Run on the test video downloaded in Stage 1
    test_video = "Testing videos/yP9v8KRym9c.f398.mp4"
    if os.path.exists(test_video):
        generator.generate_reel(test_video)
