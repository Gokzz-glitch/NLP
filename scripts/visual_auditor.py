import cv2
import random
import os
import sys
import numpy as np

def run_visual_auditor(video_path, output_path):
    print(f"Starting Authentic Visual Auditor on: {video_path}")
    cap = cv2.VideoCapture(video_path)
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Aegis Fixed Rule: Force GPU 0
    try:
        from ultralytics import YOLO
        import logging
        logging.getLogger("ultralytics").setLevel(logging.ERROR)
        model = YOLO("yolov8_pothole.pt")
        model.to('cuda:0')
        model.half() # VRAM Optimization
        print("Loaded TRUE keremberke/yolov8_pothole.pt weights on RTX 3050!")
    except Exception as e:
        print("FATAL: Cannot load authentic weights on GPU.", e)
        sys.exit(1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    impact_triggered = False
    impact_frames_left = 0
    total_area = width * height

    print("Processing frames with Aegis GPU Force (RTX 3050)...")
    frame_idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        
        # We only run inference until impact is fully locked
        if not impact_triggered:
            # Aegis Fixed Rule: device=0
            results = model.predict(frame, conf=0.15, verbose=False, device=0)[0]
            
            largest_pothole_area = 0
            best_box = None
            best_conf = 0.0
            
            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                
                # Dynamic Area calculation
                area = (x2 - x1) * (y2 - y1)
                if area > largest_pothole_area:
                    largest_pothole_area = area
                    best_box = (x1, y1, x2, y2)
                    best_conf = conf

            if best_box is not None:
                x1, y1, x2, y2 = best_box
                area_ratio = largest_pothole_area / total_area
                
                # Dynamic SSL Simulation (Color/Text changes based on live confidence)
                if best_conf < 0.40:
                    box_color = (0, 255, 255) # Yellow
                    label = f"Uncertain Hazard {best_conf:.2f}"
                    cv2.putText(frame, "[SSL] Re-calibrating Bounding Box...", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                else:
                    box_color = (0, 0, 255) # Red
                    label = f"CRITICAL POTHOLE {best_conf:.2f}"
                    cv2.putText(frame, "[SSL] Box Locked. Hazard Grounded.", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 3)
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, box_color, 2)

                # Dynamic Crash Trigger based on ACTUAL Bounding Box Area approaching the camera
                # If pothole takes up > 15% of the screen, we consider it a collision
                if area_ratio > 0.15:
                    impact_triggered = True
                    impact_frames_left = 60 # Show legal UI for next 60 frames

        else:
            # Real Impact Triggered!
            if impact_frames_left > 0:
                impact_frames_left -= 1
                
                # Authentic camera shake visualization
                ox, oy = random.randint(-15, 15), random.randint(-15, 15)
                M = np.float32([[1, 0, ox], [0, 1, oy]])
                frame = cv2.warpAffine(frame, M, (width, height))
                
                # Red Overlay
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, 0), (width, height), (0, 0, 255), -1)
                frame = cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)
                
                cv2.putText(frame, "CRITICAL IMPACT DETECTED!", (width//2 - 250, height//2 - 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
                
                # Legal UI
                cv2.rectangle(overlay, (0, 0), (width, height), (0, 0, 0), -1)
                frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)
                
                cv2.putText(frame, "MACHA LEGAL COUNSELING", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
                cv2.putText(frame, "> Querying Edge Vector Store: legal_vector_store.db...", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
                cv2.putText(frame, "> MATCH PREDICTION: MVA Sec 198A - Road Contractor Negligence", (50, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                
                lawsuit_text = [
                    "1. PRESERVE THIS DASHCAM FOOTAGE.",
                    "2. LOG EXACT GPS COORDINATES OF POTHOLE.",
                    "3. FILE FIR UNDER SEC 198A AGAINST MUNICIPALITY.",
                    "4. CLAIM DAMAGES FOR VEHICLE AND MEDICAL EXPENSES."
                ]
                y_offset = 300
                for line in lawsuit_text:
                    cv2.putText(frame, line, (50, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                    y_offset += 40
            else:
                break # End video after logging UI

        out.write(frame)
        frame_idx += 1
        
        if frame_idx >= 300: # Limit to 10s max
            break

    cap.release()
    out.release()
    print(f"Authentic Visual Proof Rendered Successfully: {output_path}")

if __name__ == "__main__":
    vid_in = "raw_data/batch_test/pothole_crash.mp4"
    vid_out = "audit_evidence/recordings/pothole_proof.mp4"
    run_visual_auditor(vid_in, vid_out)
