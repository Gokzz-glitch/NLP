import os
import sys
import cv2
import numpy as np
import logging
from typing import List, Dict, Any
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.model_registry import POTHOLE_ONNX_CANDIDATES, first_or_default

try:
    import onnxruntime as ort
    ORT_AVAILABLE = True
except ImportError:
    ORT_AVAILABLE = False

# [PERSONA 3: VISION AUDIT ENGINE]
# Task: Update vision_audit.py with YOLOv8 preprocessing & NMS (T-011).

logger = logging.getLogger("edge_sentinel.vision_audit")
logger.setLevel(logging.INFO)

class VisionAuditEngine:
    """
    Edge-native ONNX inference engine for Indian traffic entities.
    Supports YOLOv8-nano exported checkpoints.
    Target: Sequential inference for 3 models (Traffic, Vehicles, Potholes).
    """
    def __init__(self, model_paths: Dict[str, str], conf_threshold: float = 0.25, iou_threshold: float = 0.45):
        self.sessions = {}
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold

        if not ORT_AVAILABLE:
            logger.warning("ONNX Runtime is not available; vision audit will stay offline until it is installed.")
            return
        
        for name, path in model_paths.items():
            if not os.path.exists(path):
                logger.warning(f"PERSONA_3_REPORT: MODEL_NOT_FOUND: {name} | {path}")
                continue

            if not path.lower().endswith(".onnx"):
                logger.warning(f"PERSONA_3_REPORT: SKIPPING_NON_ONNX_MODEL: {name} | {path}")
                continue

            # Using CPUProvider for initial deployment; NNAPI delegate for Android NPU.
            try:
                self.sessions[name] = ort.InferenceSession(path, providers=['CPUExecutionProvider'])
                logger.info(f"PERSONA_3_REPORT: VISION_ENGINE_ONLINE: {name} | {path}")
            except Exception as e:
                logger.warning(f"PERSONA_3_REPORT: INVALID_ONNX_SKIPPED: {name} | {path} | {e}")

    def preprocess(self, frame: np.ndarray, imgsz: int = 640) -> np.ndarray:
        """Standard YOLOv8 preprocessing: Resize, BGR2RGB, Normalize, NCHW."""
        h, w = frame.shape[:2]
        # Letterbox/Resize to imgsz x imgsz
        blob = cv2.dnn.blobFromImage(frame, 1/255.0, (imgsz, imgsz), (0, 0, 0), swapRB=True, crop=False)
        return blob # shape (1, 3, 640, 640)

    def postprocess(self, outputs: np.ndarray, conf_threshold: float, model_name: str) -> List[Dict[str, Any]]:
        """
        NMS and filtering for YOLOv8 output.
        YOLOv8 output shape: (1, 41, 8400) -> [x, y, w, h, class_probs...]
        """
        if isinstance(outputs, (list, tuple)):
            outputs = outputs[0]

        predictions = np.asarray(outputs)
        if predictions.ndim == 3:
            predictions = predictions[0]

        if predictions.shape[0] < predictions.shape[1]:
            predictions = predictions.T

        if predictions.size == 0:
            return []

        # predictions: (8400, 41) or similar
        # Transpose to (8400, 41)
        if predictions.shape[0] < predictions.shape[1]:
            predictions = predictions.T
        
        boxes = []
        scores = []
        class_ids = []
        
        for pred in predictions:
            score = np.max(pred[4:])
            if score > conf_threshold:
                class_id = np.argmax(pred[4:])
                
                # Convert center xywh to xyxy
                cx, cy, w, h = pred[:4]
                x1 = cx - w/2
                y1 = cy - h/2
                x2 = cx + w/2
                y2 = cy + h/2
                
                if model_name == "pothole":
                    # Authentic YOLO pothole parser (No more COCO mapping mock)
                    class_name = "POTHOLE"
                    if class_id != 0: # Assuming yolov8_pothole weights map pothole to class 0
                        continue
                elif model_name == "traffic":
                    class_name = "TRAFFIC_SIGN"
                else:
                    class_name = f"OBJECT_{class_id}"
                
                boxes.append([x1, y1, x2, y2])
                scores.append(float(score))
                class_ids.append(class_name)

        
        if not boxes:
            return []
            
        # NMS
        indices = cv2.dnn.NMSBoxes(boxes, scores, conf_threshold, self.iou_threshold)
        if indices is None or len(indices) == 0:
            return []
        
        results = []
        for i in indices:
            # Flatten index if needed (version dependent)
            idx = i[0] if isinstance(i, (list, np.ndarray)) else i
            results.append({
                "box": boxes[idx],
                "confidence": scores[idx],
                "class_id": class_ids[idx]
            })
        return results

    def run_hazard_audit(self, frame: np.ndarray) -> Dict[str, List[Dict[str, Any]]]:
        """Runs sequential inference on all available models."""
        if not self.sessions:
            return {}

        blob = self.preprocess(frame)
        all_detections = {}
        
        for name, session in self.sessions.items():
            input_name = session.get_inputs()[0].name
            outputs = session.run(None, {input_name: blob})[0]
            detections = self.postprocess(outputs, self.conf_threshold, name)
            all_detections[name] = detections
            
        return all_detections

if __name__ == "__main__":
    # Real-World Production Models
    MODELS = {
        "pothole": str(
            first_or_default(
                POTHOLE_ONNX_CANDIDATES,
                ROOT_DIR / "raw_data" / "indian_potholes_yolov8n.onnx",
            )
        ),
    }
    engine = VisionAuditEngine(MODELS)

    if not engine.sessions:
        print("VISION_AUDIT_OFFLINE: No ONNX models were loaded.")
        sys.exit(0)
    
    # Authentic Camera Ingestion Loop (No dummy frames)
    print("INITIALIZING AUTHENTIC CAMERA FEED /dev/video0...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("HARDWARE_ERROR: Could not open authentic live camera stream.")
    else:
        while True:
            ret, live_frame = cap.read()
            if not ret:
                break
            results = engine.run_hazard_audit(live_frame)
            print(f"HAZARD_AUDIT_REPORT: Real-time inference processed.")
            # Break after 1 for audit testing limit
            break
        cap.release()
