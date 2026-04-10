import os
import cv2
import random
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
logger = logging.getLogger("DashcamShowcase")

# Paths
ROOT_DIR = ROOT_PATH
IMAGE_DIR = ROOT_DIR / "Indian-Traffic-Sign-1/test/images"
OUTPUT_DIR = ROOT_DIR / "dashboard/showcase"
POTHOLE_MODEL_PATH = resolve_yolo_pothole_pt()
GENERAL_MODEL_PATH = resolve_yolo_general_pt()

# Create output dir if not exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run_showcase(num_images=12):
    import torch
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    logger.info(f"Using device: {device}")
    
    pothole_model = YOLO(str(POTHOLE_MODEL_PATH))
    general_model = YOLO(str(GENERAL_MODEL_PATH))
    
    # Move to device
    pothole_model.to(device)
    general_model.to(device)
    
    # Get test images
    all_images = list(IMAGE_DIR.glob("*.jpg"))
    if not all_images:
        logger.error(f"No images found in {IMAGE_DIR}")
        return
    
    # Select a random subset for diversity
    selected_images = random.sample(all_images, min(len(all_images), num_images))
    
    logger.info(f"Processing {len(selected_images)} images for showcase...")
    
    results_data = []
    
    for idx, img_path in enumerate(selected_images):
        logger.info(f"Processing [{idx+1}/{len(selected_images)}]: {img_path.name}")
        
        # Load image
        img = cv2.imread(str(img_path))
        if img is None:
            continue
            
        # 1. Run Pothole Detection
        res_pothole = pothole_model(img, conf=0.25)[0]
        
        # 2. Run General Detection (Traffic Signs, Vehicles, etc.)
        res_general = general_model(img, conf=0.35)[0]
        
        # --- Visualization Logic ---
        annotated_img = img.copy()
        
        # Draw Potholes (Red BBoxes)
        for box in res_pothole.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (0, 0, 255), 3) # Red
            cv2.putText(annotated_img, f"POTHOLE {conf:.0%}", (x1, y1-10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # Draw General Objects (Green BBoxes)
        for box in res_general.boxes:
            cls = int(box.cls[0])
            name = general_model.names[cls]
            # Focus on traffic/road related for dashcam feel
            if name in ['car', 'bus', 'truck', 'traffic light', 'stop sign', 'person']:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (0, 255, 0), 2) # Green
                cv2.putText(annotated_img, f"{name.upper()} {conf:.0%}", (x1, y1-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Save annotated image
        output_path = OUTPUT_DIR / f"detected_{img_path.name}"
        cv2.imwrite(str(output_path), annotated_img)
        
        results_data.append({
            "name": img_path.name,
            "output": f"detected_{img_path.name}",
            "potholes": len(res_pothole.boxes),
            "objects": len(res_general.boxes)
        })

    logger.info("Showcase batch processing complete.")
    return results_data

if __name__ == "__main__":
    run_showcase()
