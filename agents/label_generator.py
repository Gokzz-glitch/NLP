import os
import json
import logging
from pathlib import Path

# [PERSONA 8: LABEL GENERATOR]
# Converts Gemini visual grounding JSONs into YOLOv8 .txt format.
# Gemini coordinates: [ymin, xmin, ymax, xmax] in 0-1000 scale.
# YOLO format: [class_id, x_center, y_center, width, height] in 0-1 scale.

logger = logging.getLogger("edge_sentinel.labeler")
logger.setLevel(logging.INFO)

class YOLOAutoLabeler:
    def __init__(self, data_dir: str = "raw_data/self_labeled/", output_dir: str = "raw_data/self_labeled_train/"):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.img_dir = self.output_dir / "images"
        self.lbl_dir = self.output_dir / "labels"
        
        self.img_dir.mkdir(parents=True, exist_ok=True)
        self.lbl_dir.mkdir(parents=True, exist_ok=True)

    def process_all(self):
        """Processes all verified JSON files in data_dir."""
        json_files = list(self.data_dir.glob("*.json"))
        count = 0
        
        for j_file in json_files:
            try:
                with open(j_file, "r") as f:
                    data = json.load(f)
                
                verification = data.get("teacher_vqa", {})
                if not verification.get("hazard_confirmed"):
                    continue
                
                bbox = verification.get("bounding_box") # [ymin, xmin, ymax, xmax]
                if not bbox or len(bbox) != 4:
                    continue
                
                # Verify corresponding image exists
                # In bridge, image was saved as jerk_TIMESTAMP.jpg
                # JSON was saved as self_TIMESTAMP.json
                # Wait, the ID in JSON is self_{timestamp}. 
                # Let's find the matching image.
                # Actually, the audit_jerk_event stores the image path.
                
                # For now, let's look for any .jpg with the same timestamp or closest match
                # Better: find the jpg that was processed.
                
                # Logic: Since we want to find the image, we assume it's in the same folder.
                # The bridge saves jerk_{ts}.jpg and then learner saves self_{ts}.json.
                # Let's assume the user manually links them or we look for the latest JPG.
                
                # IMPROVEMENT: The JSON should contain the image path.
                # Let's check learner_agent.py again. (It doesn't store the path yet).
                
                # Fallback search for .jpg in the same folder
                img_path = self._find_matching_image(j_file)
                if not img_path:
                    logger.warning(f"No matching image found for {j_file}")
                    continue
                
                # Convert to YOLO
                yolo_bbox = self._convert_to_yolo(bbox)
                
                # Write YOLO file
                stem = j_file.stem
                with open(self.lbl_dir / f"{stem}.txt", "w") as f:
                    # Class 0: Pothole
                    f.write(f"0 {yolo_bbox[0]} {yolo_bbox[1]} {yolo_bbox[2]} {yolo_bbox[3]}\n")
                
                # Copy image
                import shutil
                shutil.copy(img_path, self.img_dir / f"{stem}.jpg")
                
                count += 1
                
            except Exception as e:
                logger.error(f"Failed to process {j_file}: {e}")
        
        logger.info(f"YOLO_LABELER: Processed {count} samples.")
        return count

    def _find_matching_image(self, json_path: Path):
        """Looks for a .jpg with the same timestamp ID."""
        ts_id = json_path.stem.split("_")[-1]
        for img in self.data_dir.glob(f"*{ts_id}.jpg"):
            return img
        return None

    def _convert_to_yolo(self, gemini_bbox):
        """
        Gemini: [ymin, xmin, ymax, xmax] (0-1000)
        YOLO: [x_center, y_center, width, height] (0-1)
        """
        ymin, xmin, ymax, xmax = gemini_bbox
        
        # Normalize to 0-1
        ymin, xmin, ymax, xmax = ymin/1000.0, xmin/1000.0, ymax/1000.0, xmax/1000.0
        
        w = xmax - xmin
        h = ymax - ymin
        x_center = xmin + (w / 2)
        y_center = ymin + (h / 2)
        
        return [x_center, y_center, w, h]

if __name__ == "__main__":
    labeler = YOLOAutoLabeler()
    labeler.process_all()
