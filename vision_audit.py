import os
import sys
import numpy as np
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import onnxruntime as ort
    ORT_AVAILABLE = True
except ImportError:
    ORT_AVAILABLE = False
    print("WARNING: [onnxruntime not installed. Vision engine unavailable; mock mode active.]")

# CONFIGURATION — override via environment variable if needed
_PROJECT_ROOT = os.path.dirname(__file__)
MODEL_PATH = os.getenv(
    "VISION_MODEL_PATH",
    os.path.join(_PROJECT_ROOT, "models", "vision", "indian_traffic_yolov8.onnx"),
)

# YOLOv8n input resolution
_INPUT_W = 640
_INPUT_H = 640
# Confidence threshold for detections
_CONF_THRESHOLD = float(os.getenv("VISION_CONF_THRESHOLD", "0.45"))

# Class labels for Indian traffic ONNX model
# (Must match the label order used when the model was trained on Roboflow.)
INDIAN_TRAFFIC_CLASSES = [
    "speed_limit_sign",   # 0
    "stop_sign",          # 1
    "no_entry",           # 2
    "pedestrian_crossing",# 3
    "speed_camera",       # 4
    "traffic_light_red",  # 5
    "traffic_light_green",# 6
    "traffic_light_yellow",# 7
    "pothole",            # 8
    "road_work",          # 9
    "pedestrian",         # 10
    "two_wheeler",        # 11
    "auto_rickshaw",      # 12
    "car",                # 13
    "bus",                # 14
    "truck",              # 15
]


class VisionAuditEngine:
    """
    Edge-native ONNX inference engine for Indian traffic entities.

    Two modes:
      ONNX_MODE  — real YOLOv8n ONNX inference (requires model file + onnxruntime)
      MOCK_MODE  — returns empty detections; safe for unit tests and CI

    Use VISION_MODEL_PATH env var to point at a custom model file.
    Set VISION_MOCK_MODE=1 to force mock mode (useful in test environments).
    """

    def __init__(self, model_path=None):
        if model_path is None:
            model_path = MODEL_PATH

        self._mock = (
            os.getenv("VISION_MOCK_MODE", "0") == "1"
            or not ORT_AVAILABLE
            or not os.path.exists(model_path)
        )

        if self._mock:
            print(
                "PERSONA_3_REPORT: VISION_ENGINE_MOCK_MODE. "
                "Set VISION_MODEL_PATH to a valid .onnx file and ensure onnxruntime is "
                "installed to enable real inference."
            )
            self.session = None
            self.input_name = None
        else:
            self.session = ort.InferenceSession(
                model_path, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            print(f"PERSONA_3_REPORT: VISION_ENGINE_ONLINE: {model_path}")

    @property
    def is_mock(self) -> bool:
        return self._mock

    def preprocess(self, image_frame: np.ndarray) -> np.ndarray:
        """
        YOLOv8 standard preprocessing:
          1. Resize to 640×640 with letterboxing (preserve aspect ratio)
          2. BGR → RGB
          3. Normalise to [0, 1]
          4. NHWC → NCHW, add batch dim → shape (1, 3, 640, 640) float32

        Args:
            image_frame: HxWx3 uint8 BGR numpy array (OpenCV convention)
        Returns:
            (1, 3, 640, 640) float32 tensor
        """
        if not CV2_AVAILABLE:
            # Without cv2, produce a zero tensor of the correct shape
            return np.zeros((1, 3, _INPUT_H, _INPUT_W), dtype=np.float32)

        h, w = image_frame.shape[:2]
        scale = min(_INPUT_W / w, _INPUT_H / h)
        new_w, new_h = int(w * scale), int(h * scale)

        resized = cv2.resize(image_frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Letterbox: pad to 640×640 with grey (114, 114, 114)
        canvas = np.full((_INPUT_H, _INPUT_W, 3), 114, dtype=np.uint8)
        pad_x = (_INPUT_W - new_w) // 2
        pad_y = (_INPUT_H - new_h) // 2
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized

        # BGR → RGB, normalise, NHWC → NCHW
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        return rgb.transpose(2, 0, 1)[np.newaxis, :, :, :]  # (1, 3, H, W)

    def postprocess(self, raw_output: np.ndarray, conf_threshold: float = _CONF_THRESHOLD) -> list:
        """
        Parse YOLOv8 ONNX output into detection dicts.

        YOLOv8 ONNX output shape: (1, 4+num_classes, num_anchors) — transposed.
        Returns list of {"label": str, "conf": float, "bbox": [x1,y1,x2,y2]}
        """
        # YOLOv8 ONNX output: (1, num_classes+4, 8400)
        preds = raw_output[0]  # (num_classes+4, 8400) or (8400, num_classes+4)

        # Normalise to (8400, num_classes+4)
        if preds.shape[0] < preds.shape[1]:
            preds = preds.T  # (8400, C+4)

        detections = []
        num_classes = len(INDIAN_TRAFFIC_CLASSES)

        for row in preds:
            cx, cy, bw, bh = row[0], row[1], row[2], row[3]
            class_scores = row[4: 4 + num_classes]
            best_cls = int(np.argmax(class_scores))
            conf = float(class_scores[best_cls])
            if conf < conf_threshold:
                continue
            label = INDIAN_TRAFFIC_CLASSES[best_cls] if best_cls < num_classes else f"class_{best_cls}"
            x1 = float(cx - bw / 2)
            y1 = float(cy - bh / 2)
            x2 = float(cx + bw / 2)
            y2 = float(cy + bh / 2)
            detections.append({"label": label, "conf": round(conf, 3), "bbox": [x1, y1, x2, y2]})

        return detections

    def run_inference(self, image_frame: np.ndarray) -> list:
        """
        Run end-to-end detection on a single BGR frame.

        Args:
            image_frame: HxWx3 uint8 BGR numpy array; or None in mock mode.
        Returns:
            List of detection dicts: [{"label": str, "conf": float, "bbox": [x1,y1,x2,y2]}, …]
            Returns [] in mock mode (safe for pipeline testing without a model).
        """
        if self._mock:
            return []

        blob = self.preprocess(image_frame)
        raw = self.session.run(None, {self.input_name: blob})
        return self.postprocess(raw[0])


if __name__ == "__main__":
    engine = VisionAuditEngine(MODEL_PATH)
    print(f"Mock mode: {engine.is_mock}")
    if not engine.is_mock:
        # Quick sanity-check with a blank frame
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        results = engine.run_inference(blank)
        print(f"Detections on blank frame: {results}")

