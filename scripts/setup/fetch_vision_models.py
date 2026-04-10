import json
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from config import VISION_MODEL_DIR, IN_COLAB

try:
    from roboflow import Roboflow
except Exception:
    Roboflow = None

load_dotenv()
api_key = os.getenv("ROBOFLOW_API_KEY")


# Core object groups for Indian-road safety and accident-risk scenarios.
INDIAN_ROAD_OBJECT_GROUPS = {
    "vulnerable_road_users": ["person", "bicycle", "motorcycle", "rider_without_helmet"],
    "high_mass_vehicles": ["bus", "truck", "tractor", "construction_vehicle"],
    "mixed_traffic_vehicles": ["car", "auto_rickshaw", "motorcycle", "van"],
    "road_infrastructure_hazards": ["pothole", "speed_breaker", "broken_edge", "debris"],
    "control_and_compliance": ["traffic_light", "stop_sign", "indian_traffic_sign", "lane_marking"],
    "incident_signals": ["collision", "overturned_vehicle", "stalled_vehicle", "pedestrian_fall"],
}


# Base general-purpose weights (COCO) for most common road objects.
BASE_MODELS = [
    {
        "name": "yolov8n",
        "source": "ultralytics",
        "weights": "yolov8n.pt",
        "covers": [
            "person", "bicycle", "car", "motorcycle", "bus", "truck", "traffic_light", "stop_sign"
        ],
    },
    {
        "name": "yolov8s",
        "source": "ultralytics",
        "weights": "yolov8s.pt",
        "covers": [
            "person", "bicycle", "car", "motorcycle", "bus", "truck", "traffic_light", "stop_sign"
        ],
    },
]


# India/domain-specialized models for potholes/signs/road-specific classes.
SPECIALIZED_MODELS = [
    {
        "name": "indian_pothole_detector",
        "workspace": "intel-unnati-training-program",
        "project": "pothole-detection-bqu6s",
        "version": 1,
        "location": "raw_data/pothole_dl",
        "covers": ["pothole", "road_surface_damage"],
    },
    {
        "name": "indian_traffic_signs",
        "workspace": "as-u7s8u",
        "project": "indian-traffic-signs-yolov8",
        "version": 1,
        "location": "raw_data/traffic_dl",
        "covers": ["indian_traffic_sign", "warning_sign", "regulatory_sign"],
    },
    {
        "name": "indian_roads_detection",
        "workspace": "wirehead",
        "project": "indian-roads-detection",
        "version": 2,
        "location": "raw_data/indian_roads_dl",
        "covers": ["car", "bus", "truck", "motorcycle", "auto_rickshaw", "road_lane"],
    },
]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _download_base_models(vision_dir: Path, manifest: dict) -> None:
    try:
        from ultralytics import YOLO
    except Exception as e:
        print(f"BASE_MODEL_SETUP_FAILED: ultralytics not available ({e})")
        return

    for model_cfg in BASE_MODELS:
        weights = model_cfg["weights"]
        print(f"FETCHING BASE MODEL: {weights}")
        try:
            # YOLO(...) auto-downloads known pretrained checkpoints if absent.
            YOLO(weights)
            src = Path(weights)
            dst = vision_dir / weights
            if src.exists() and src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            elif not src.exists() and not dst.exists():
                print(f"WARN: Base weights not found after download step: {weights}")

            manifest["weights"].append(
                {
                    "name": model_cfg["name"],
                    "source": model_cfg["source"],
                    "path": str(dst),
                    "covers": model_cfg["covers"],
                    "status": "ready" if dst.exists() else "missing",
                }
            )
        except Exception as e:
            print(f"FAILED_BASE_MODEL_{weights}: {e}")
            manifest["weights"].append(
                {
                    "name": model_cfg["name"],
                    "source": model_cfg["source"],
                    "path": str(vision_dir / weights),
                    "covers": model_cfg["covers"],
                    "status": f"failed: {e}",
                }
            )


def _download_specialized_models(rf: Roboflow, manifest: dict) -> None:
    for model_cfg in SPECIALIZED_MODELS:
        print(
            f"FETCHING SPECIALIZED MODEL: {model_cfg['project']} "
            f"(workspace={model_cfg['workspace']}, version={model_cfg['version']})"
        )
        try:
            rf.workspace(model_cfg["workspace"]).project(model_cfg["project"]).version(
                model_cfg["version"]
            ).download("yolov8", location=model_cfg["location"])

            manifest["weights"].append(
                {
                    "name": model_cfg["name"],
                    "source": "roboflow",
                    "path": model_cfg["location"],
                    "covers": model_cfg["covers"],
                    "status": "ready",
                }
            )
        except Exception as e:
            print(f"FAILED_SPECIALIZED_MODEL_{model_cfg['project']}: {e}")
            manifest["weights"].append(
                {
                    "name": model_cfg["name"],
                    "source": "roboflow",
                    "path": model_cfg["location"],
                    "covers": model_cfg["covers"],
                    "status": f"failed: {e}",
                }
            )

def download_vision_models():
    allow_local = os.getenv("ALLOW_LOCAL_VISION_FETCH", "0") == "1"
    if not IN_COLAB and not allow_local:
        print("LOCAL_FETCH_BLOCKED: Set ALLOW_LOCAL_VISION_FETCH=1 to run on local machine.")
        print("TIP: Cloud/Colab remains the recommended path for large model downloads.")
        return

    if not api_key:
        print("WARN: ROBOFLOW_API_KEY missing. Specialized India datasets will be skipped.")
    if Roboflow is None:
        print("WARN: roboflow package missing. Specialized India datasets will be skipped.")

    rf = Roboflow(api_key=api_key) if (api_key and Roboflow is not None) else None

    if IN_COLAB:
        print(f"SHIELD ACTIVE: Using Cloud Disk ({VISION_MODEL_DIR}) to save your local SSD.")

    vision_dir = Path(VISION_MODEL_DIR)
    _ensure_dir(vision_dir)

    manifest = {
        "objective": "Indian-road object detection with accident-risk coverage",
        "object_groups": INDIAN_ROAD_OBJECT_GROUPS,
        "weights": [],
    }

    # Temporarily switch to the cloud directory to download Roboflow artifacts
    original_cwd = os.getcwd()
    os.chdir(VISION_MODEL_DIR)

    try:
        _download_base_models(vision_dir, manifest)

        if rf:
            _download_specialized_models(rf, manifest)
        else:
            for model_cfg in SPECIALIZED_MODELS:
                manifest["weights"].append(
                    {
                        "name": model_cfg["name"],
                        "source": "roboflow",
                        "path": model_cfg["location"],
                        "covers": model_cfg["covers"],
                        "status": "skipped: missing ROBOFLOW_API_KEY",
                    }
                )

        manifest_path = vision_dir / "indian_road_model_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"INDIAN_ROAD_MODEL_MANIFEST_WRITTEN: {manifest_path}")
    finally:
        # Return to original CWD even if a download fails.
        os.chdir(original_cwd)

if __name__ == "__main__":
    download_vision_models()
