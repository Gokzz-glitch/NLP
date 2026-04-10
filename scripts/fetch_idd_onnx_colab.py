# [COLAB_ONLY] SmartSalai IDD Weights Fetch & Export 
# Run this in your Colab notebook to bypass the Hardware Shield.

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.secret_manager import get_secret
try:
    from roboflow import Roboflow
except ImportError:
    !pip install -q roboflow ultralytics
    from roboflow import Roboflow

from ultralytics import YOLO

def fetch_idd_weights():
    # 1. Initialize Roboflow (using key from env or pass directly)
    api_key = get_secret("ROBOFLOW_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ROBOFLOW_API_KEY is not set in this runtime")
    rf = Roboflow(api_key=api_key)
    project = rf.workspace("indian-road-dataset").project("indian-roads-detection")
    dataset = project.version(2).download("yolov8")
    
    # 2. Export to ONNX (Heavy Workload - Hardware Shield Compliant)
    src_pt = os.path.join(dataset.location, "weights", "best.pt")
    model = YOLO(src_pt)
    model.export(format="onnx")
    
    # 3. Sync to Google Drive / models/vision/
    dest_path = "/content/drive/My Drive/NLP/models/vision/indian_vehicles_chaos_yolov8n.onnx"
    onnx_path = src_pt.replace(".pt", ".onnx")
    
    if os.path.exists(onnx_path):
        import shutil
        shutil.copy(onnx_path, dest_path)
        print(f"SUCCESS: Weight-sync complete to {dest_path}")
    else:
        print("ERROR: Export failed.")

if __name__ == "__main__":
    fetch_idd_weights()
