import cv2
import os
import glob
from ultralytics import YOLO
from core.model_registry import resolve_yolo_pothole_pt

# Model path
MODEL_PATH = str(resolve_yolo_pothole_pt())
TEST_VIDEOS_DIR = "Testing videos"

def validate_in_realtime():
    print(f"🚀 Initializing SmartSalai Edge Sentinel Real-Time Visualizer...")
    
    if not os.path.exists(MODEL_PATH):
        print(f"❌ Error: Model {MODEL_PATH} not found.")
        return
        
    model = YOLO(MODEL_PATH)
    
    # Get all potential video files
    video_files = glob.glob(os.path.join(TEST_VIDEOS_DIR, "*.mp4"))
    video_files += glob.glob(os.path.join(TEST_VIDEOS_DIR, "*.avi"))
    
    # Also check extension-less files if they are videos
    for f in os.listdir(TEST_VIDEOS_DIR):
        full_path = os.path.join(TEST_VIDEOS_DIR, f)
        if "." not in f and os.path.isfile(full_path):
            video_files.append(full_path)
            
    if not video_files:
        print(f"❌ No videos found in '{TEST_VIDEOS_DIR}'.")
        return

    print(f"✅ Found {len(video_files)} videos. Starting real-time feed...")
    print(f"⌨️  Press 'q' to skip to the next video, or 'Esc' to exit completely.")

    for video_path in video_files:
        print(f"\n▶️ Playing: {os.path.basename(video_path)}")
        cap = cv2.VideoCapture(video_path)
        out = None
        frame_count = 0
        
        if not cap.isOpened():
            print(f"⚠️ Could not read video {video_path}")
            continue
            
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            # Resize frame for better real-time display performance if it's too large (e.g. 4k)
            # height, width = frame.shape[:2]
            # if width > 1280:
            frame = cv2.resize(frame, (1280, 720))
                
            # Run YOLO inference with lower confidence to ensure we catch edge cases
            results = model.predict(frame, conf=0.10, verbose=False)
            
            annotated_frame = frame.copy()
            
            # Manually extract and draw bounding boxes to match standard YouTube demo aesthetics perfectly
            for r in results:
                boxes = r.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    conf = box.conf[0].item()
                    cls_id = int(box.cls[0].item())
                    cls_name = model.names[cls_id]
                    
                    # 1. Draw a clean, solid red bounding box (thickness 3)
                    box_color = (50, 50, 255) # Clean red (BGR)
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), box_color, 3)
                    
                    # 2. Add the solid text banner exactly on top of the boundary
                    label = f"{cls_name} {conf:.2f}"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.8
                    font_thickness = 2
                    
                    # Get text size to draw perfect solid background
                    (w, h), baseline = cv2.getTextSize(label, font, font_scale, font_thickness)
                    
                    # Text banner background
                    cv2.rectangle(annotated_frame, (x1, y1 - h - 10), (x1 + w + 10, y1), box_color, -1)
                    
                    # Text foreground (clean white)
                    cv2.putText(annotated_frame, label, (x1 + 5, y1 - 5), 
                                font, font_scale, (255, 255, 255), font_thickness)
            
            
            
            # HUD text - optimized for judge visibility
            cv2.putText(annotated_frame, "SMARTSALAI AEGIS: INFERENCE", (20, 50), 
                        cv2.FONT_HERSHEY_DUPLEX, 1.2, (0, 255, 255), 3)
            cv2.putText(annotated_frame, f"FEED: {os.path.basename(video_path)}", (20, 100), 
                        cv2.FONT_HERSHEY_DUPLEX, 1, (255, 200, 0), 3)
            
            # Write to output video instead of showing on isolated GUI session
            if out is None:
                # Initialize VideoWriter dynamically based on the first frame size
                h_f, w_f = annotated_frame.shape[:2]
                out_path = video_path.replace('.mp4', '_annotated.mp4').replace('.avi', '_annotated.avi')
                if '.' not in out_path: out_path += '_annotated.mp4'
                
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(out_path, fourcc, 30.0, (w_f, h_f))
                print(f"🎬 Saving processed video to: {out_path}")
                
            out.write(annotated_frame)
            frame_count += 1
            if frame_count % 30 == 0:
                print(f"   Processed {frame_count} frames...")
                
        if out is not None:
            out.release()
        cap.release()
        
    print("\n✅ All videos processed and saved to your 'Testing videos' folder.")

if __name__ == "__main__":
    validate_in_realtime()
