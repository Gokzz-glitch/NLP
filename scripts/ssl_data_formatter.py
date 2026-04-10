import os
import json
import glob
import shutil
from pathlib import Path

import cv2

from scripts.road_scene_taxonomy import bbox_to_yolo, canonicalize_label

def format_ssl_data(input_dir, output_dir, classes_map):
    """
    Parses dynamic SSL JSON labels into YOLOv8 .txt format bounding boxes.
    """
    print(f"🔄 Formatting SSL data from {input_dir}...")
    
    images_dir = os.path.join(output_dir, 'images')
    labels_dir = os.path.join(output_dir, 'labels')
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)
    
    json_files = glob.glob(os.path.join(input_dir, "*.json"))
    success_count = 0
    
    for j_path in json_files:
        try:
            with open(j_path, 'r') as f:
                data = json.load(f)
            
            vqa = data.get('teacher_vqa', {}) or {}
            raw_objects = vqa.get('scene_objects') or vqa.get('objects') or []
            if not isinstance(raw_objects, list):
                raw_objects = []

            if not raw_objects and vqa.get('hazard_confirmed', False):
                raw_objects = [{
                    'class': vqa.get('type', 'other_road_object'),
                    'confidence': vqa.get('confidence', 0.0),
                    'bounding_box': vqa.get('bounding_box', [0, 0, 0, 0]),
                }]

            if not raw_objects:
                continue
            
            # Find associated image
            base_id = data.get('id', '')
            # Try to find corresponding image file
            pattern = os.path.join(input_dir, f"*{data['timestamp']}*.jpg")
            img_matches = glob.glob(pattern)
            
            if not img_matches:
                # Direct matched id
                img_path = j_path.replace('.json', '.jpg')
                if not os.path.exists(img_path):
                    continue
            else:
                img_path = img_matches[0]

            image = cv2.imread(img_path)
            if image is None:
                continue
            image_height, image_width = image.shape[:2]

            label_lines = []
            for raw_obj in raw_objects:
                if not isinstance(raw_obj, dict):
                    continue

                hazard_type = canonicalize_label(raw_obj.get('class') or raw_obj.get('type') or raw_obj.get('name'))
                if hazard_type not in classes_map:
                    continue

                class_id = classes_map[hazard_type]
                yolo_box = bbox_to_yolo(
                    raw_obj.get('bounding_box') or raw_obj.get('bbox') or raw_obj.get('box') or [0, 0, 0, 0],
                    image_width,
                    image_height,
                )
                if not yolo_box:
                    continue

                x_c, y_c, w, h = yolo_box
                label_lines.append(f"{class_id} {x_c:.5f} {y_c:.5f} {w:.5f} {h:.5f}")

            if not label_lines:
                continue
            
            # Copy image to output/images
            dst_img = os.path.join(images_dir, os.path.basename(img_path))
            shutil.copy2(img_path, dst_img)
            
            # Write label
            label_name = os.path.basename(img_path).replace('.jpg', '.txt')
            dst_label = os.path.join(labels_dir, label_name)
            
            with open(dst_label, 'w') as lf:
                lf.write("\n".join(label_lines) + "\n")
                
            success_count += 1
            
        except Exception as e:
            print(f"Skipping {j_path} due to parsing error: {e}")
            
    print(f"✅ Formatted {success_count} SSL samples into YOLO format at {output_dir}")

if __name__ == "__main__":
    # Standard classes for the hazard SSL Loop
    from scripts.road_scene_taxonomy import class_id_map

    CLASSES = class_id_map()
    
    # Allows the script to be run locally or mapped dynamically on Colab
    base_raw = os.environ.get("SSL_RAW_DIR", "raw_data/self_labeled")
    base_out = os.environ.get("SSL_OUT_DIR", "datasets/ssl_v1/train")
    
    format_ssl_data(base_raw, base_out, CLASSES)
