import os
import sys
import subprocess
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# SMARTSALAI: SPECIALIZED MODEL TRAINER
# Uses Kaggle open datasets to train YOLOv8 models for:
# 1. Pothole Detection (Indian Roads)
# 2. Indian Traffic Signs
# Replaces generic yolov8n.onnx with domain-specific weights.
# ============================================================

KAGGLE_USERNAME = os.getenv("KAGGLE_USERNAME")
KAGGLE_KEY = os.getenv("KAGGLE_KEY")
if not KAGGLE_USERNAME or not KAGGLE_KEY:
    raise RuntimeError(
        "KAGGLE_USERNAME and KAGGLE_KEY must be set via environment variables "
        "or a secret manager before running training."
    )

# Write kaggle.json so the CLI works
kaggle_dir = Path.home() / ".kaggle"
kaggle_dir.mkdir(exist_ok=True)
kaggle_cfg = kaggle_dir / "kaggle.json"
if not kaggle_cfg.exists():
    kaggle_cfg.write_text(json.dumps({"username": KAGGLE_USERNAME, "key": KAGGLE_KEY}))
    kaggle_cfg.chmod(0o600)

def run(cmd, **kwargs):
    print(f"\n>> {cmd}")
    return subprocess.run(cmd, shell=True, **kwargs)

def download_pothole_dataset():
    out = Path("raw_data/pothole_dataset")
    if list(out.glob("**/*.yaml")):
        print("[SKIP] Pothole dataset already downloaded.")
        return
    out.mkdir(parents=True, exist_ok=True)
    print("\n--- Downloading Pothole Detection Dataset from Kaggle ---")
    run(f'python -c "from kaggle.api.kaggle_api_extended import KaggleApi; api = KaggleApi(); api.authenticate(); api.dataset_download_files(\'anggadwisunarto/potholes-detection-yolov8\', path=\'{out}\', unzip=True)"')

def download_traffic_dataset():
    out = Path("raw_data/traffic_dataset")
    if list(out.glob("**/*.yaml")):
        print("[SKIP] Traffic dataset already downloaded.")
        return
    out.mkdir(parents=True, exist_ok=True)
    print("\n--- Downloading Indian Traffic Signs Dataset from Kaggle ---")
    run(f'python -c "from kaggle.api.kaggle_api_extended import KaggleApi; api = KaggleApi(); api.authenticate(); api.dataset_download_files(\'kaustubhrastogi17/traffic-signs-dataset-indian-roads\', path=\'{out}\', unzip=True)"')

def find_yaml(dataset_dir: str):
    yamls = list(Path(dataset_dir).glob("**/*.yaml"))
    if yamls:
        return str(yamls[0])
    return None

def train_pothole_model():
    print("\n=== TRAINING POTHOLE DETECTION MODEL ===")
    from ultralytics import YOLO
    model = YOLO("yolov8n.pt")
    data_yaml = find_yaml("raw_data/pothole_dataset")
    if not data_yaml:
        print("ERROR: No .yaml found in pothole dataset. Check Kaggle download.")
        return None
    print(f"Using data file: {data_yaml}")
    results = model.train(
        data=data_yaml,
        epochs=50,          # REAL-WORLD IMPLEMENTATION: 50 epochs for high convergence
        imgsz=640,
        project="runs/train",
        name="pothole_v1",
        exist_ok=True,
        device=0
    )
    # Export best.pt -> ONNX
    best_pt = Path("runs/train/pothole_v1/weights/best.pt")
    if best_pt.exists():
        print("\nExporting pothole model to ONNX...")
        export_model = YOLO(str(best_pt))
        export_model.export(format="onnx", dynamic=False, simplify=True)
        onnx_path = str(best_pt).replace(".pt", ".onnx")
        target = "raw_data/pothole_v1.onnx"
        Path(onnx_path).rename(target)
        print(f"Pothole model saved to: {target}")
        return target
    return None

def train_traffic_model():
    print("\n=== TRAINING INDIAN TRAFFIC SIGN MODEL ===")
    from ultralytics import YOLO
    model = YOLO("yolov8n.pt")
    data_yaml = find_yaml("raw_data/traffic_dataset")
    if not data_yaml:
        print("ERROR: No .yaml found in traffic dataset. Check Kaggle download.")
        return None
    print(f"Using data file: {data_yaml}")
    results = model.train(
        data=data_yaml,
        epochs=50,          # REAL-WORLD IMPLEMENTATION: 50 epochs
        imgsz=640,
        project="runs/train",
        name="traffic_v1",
        exist_ok=True,
        device=0
    )
    best_pt = Path("runs/train/traffic_v1/weights/best.pt")
    if best_pt.exists():
        print("\nExporting traffic model to ONNX...")
        export_model = YOLO(str(best_pt))
        export_model.export(format="onnx", dynamic=False, simplify=True)
        onnx_path = str(best_pt).replace(".pt", ".onnx")
        target = "raw_data/traffic_v1.onnx"
        Path(onnx_path).rename(target)
        print(f"Traffic model saved to: {target}")
        return target
    return None

if __name__ == "__main__":
    print("="*60)
    print("  SMARTSALAI: DOMAIN-SPECIFIC MODEL TRAINER")
    print("  Building specialized Indian Road Vision Models")
    print("="*60)

    download_pothole_dataset()
    download_traffic_dataset()

    pothole_model = train_pothole_model()
    traffic_model = train_traffic_model()

    print("\n" + "="*60)
    print("  TRAINING COMPLETE")
    print(f"  Pothole model: {pothole_model or 'FAILED'}")
    print(f"  Traffic model: {traffic_model or 'FAILED'}")
    print("  Update vision_audit.py model_paths to use these weights!")
    print("="*60)
