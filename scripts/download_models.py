#!/usr/bin/env python3
"""
scripts/download_models.py
SmartSalai Edge-Sentinel — Model Acquisition Script (ERR-001 resolver)

Downloads and converts the YOLOv8-nano vision model to ONNX format.

Sources (tried in order):
  1. Roboflow  — Indian road-sign detection project (best accuracy, needs API key)
  2. HuggingFace — community ONNX snapshot (no API key, may need HF_TOKEN for gated repos)
  3. ultralytics — base YOLOv8n (no API key; for pipeline smoke-tests only, wrong labels)

Usage:
  python scripts/download_models.py            # auto-select best available source
  python scripts/download_models.py --source roboflow
  python scripts/download_models.py --source hf
  python scripts/download_models.py --source ultralytics

Environment variables (set in .env or export):
  ROBOFLOW_API_KEY   — Roboflow API key (roboflow.com → account → API keys)
  HF_TOKEN           — HuggingFace token (optional, for gated repos)
  VISION_MODELS_DIR  — destination directory (default: models/vision/)
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import tempfile

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    pass  # python-dotenv optional here

VISION_MODELS_DIR = os.getenv(
    "VISION_MODELS_DIR",
    os.path.join(_PROJECT_ROOT, "models", "vision"),
)
TARGET_ONNX = os.path.join(VISION_MODELS_DIR, "indian_traffic_yolov8.onnx")

ROBOFLOW_WORKSPACE = "viren-daultani-y0fio"
ROBOFLOW_PROJECT   = "road-signs-indian-p2kgu"
ROBOFLOW_VERSION   = 1

HF_REPO_ID  = "arnabdhar/YOLOv8-nano-indian-traffic-signs"
HF_FILENAME = "model.onnx"

# ---------------------------------------------------------------------------
# Source: Roboflow
# ---------------------------------------------------------------------------

def _download_roboflow(api_key: str) -> bool:
    print("[ERR-001] Trying Roboflow source …")
    try:
        from roboflow import Roboflow  # noqa: PLC0415
    except ImportError:
        print("  SKIP: roboflow package not installed. Run: pip install roboflow")
        return False

    try:
        rf = Roboflow(api_key=api_key)
        project = rf.workspace(ROBOFLOW_WORKSPACE).project(ROBOFLOW_PROJECT)
        dataset = project.version(ROBOFLOW_VERSION).download("yolov8")
    except Exception as exc:
        print(f"  SKIP: Roboflow download failed: {exc}")
        return False

    # Export .pt → ONNX
    best_pt = os.path.join(dataset.location, "weights", "best.pt")
    if not os.path.exists(best_pt):
        print(f"  SKIP: best.pt not found at {best_pt}")
        return False

    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except ImportError:
        print("  SKIP: ultralytics not installed. Run: pip install ultralytics")
        return False

    model = YOLO(best_pt)
    with tempfile.TemporaryDirectory() as tmp:
        model.export(format="onnx", project=tmp)
        onnx_src = best_pt.replace(".pt", ".onnx")
        if not os.path.exists(onnx_src):
            # ultralytics exports to project subdir
            onnx_src = os.path.join(dataset.location, "weights", "best.onnx")

        if not os.path.exists(onnx_src):
            print(f"  SKIP: ONNX export not found at {onnx_src}")
            return False

        os.makedirs(VISION_MODELS_DIR, exist_ok=True)
        shutil.copy(onnx_src, TARGET_ONNX)

    print(f"  SUCCESS: {TARGET_ONNX}")
    return True


# ---------------------------------------------------------------------------
# Source: HuggingFace
# ---------------------------------------------------------------------------

def _download_hf(token: str | None) -> bool:
    print("[ERR-001] Trying HuggingFace source …")
    try:
        from huggingface_hub import hf_hub_download  # noqa: PLC0415
    except ImportError:
        print("  SKIP: huggingface_hub not installed. Run: pip install huggingface_hub")
        return False

    try:
        path = hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=HF_FILENAME,
            token=token or None,
        )
    except Exception as exc:
        print(f"  SKIP: HuggingFace download failed: {exc}")
        return False

    os.makedirs(VISION_MODELS_DIR, exist_ok=True)
    shutil.copy(path, TARGET_ONNX)
    print(f"  SUCCESS: {TARGET_ONNX}")
    return True


# ---------------------------------------------------------------------------
# Source: ultralytics base (pipeline smoke-test only)
# ---------------------------------------------------------------------------

def _download_ultralytics() -> bool:
    print("[ERR-001] Trying ultralytics base YOLOv8n (SMOKE-TEST ONLY — wrong class labels) …")
    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except ImportError:
        print("  SKIP: ultralytics not installed. Run: pip install ultralytics")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        model = YOLO("yolov8n.pt")
        model.export(format="onnx", project=tmp, name="yolov8n")
        candidates = [
            os.path.join(tmp, "yolov8n", "weights", "yolov8n.onnx"),
            os.path.join(tmp, "yolov8n.onnx"),
            "yolov8n.onnx",
        ]
        src = next((c for c in candidates if os.path.exists(c)), None)
        if src is None:
            # ultralytics exports alongside the .pt
            import glob
            found = glob.glob("**/*.onnx", recursive=True)
            src = found[0] if found else None

        if src is None:
            print("  SKIP: ONNX export not found after ultralytics export.")
            return False

        os.makedirs(VISION_MODELS_DIR, exist_ok=True)
        shutil.copy(src, TARGET_ONNX)

    print(
        f"  SUCCESS: {TARGET_ONNX}\n"
        "  WARNING: This is a base COCO model — class labels DO NOT match\n"
        "           INDIAN_TRAFFIC_CLASSES. Use Roboflow source for production."
    )
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Download YOLOv8 vision model for SmartSalai")
    parser.add_argument(
        "--source",
        choices=["auto", "roboflow", "hf", "ultralytics"],
        default="auto",
        help="Model source (default: auto = try in order roboflow → hf → ultralytics)",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if file exists")
    args = parser.parse_args()

    if os.path.exists(TARGET_ONNX) and not args.force:
        print(f"[ERR-001] Model already present at {TARGET_ONNX}")
        print("  Use --force to re-download.")
        sys.exit(0)

    roboflow_key = os.getenv("ROBOFLOW_API_KEY", "")
    hf_token = os.getenv("HF_TOKEN", "")

    order: list
    if args.source == "roboflow":
        order = [("roboflow", lambda: _download_roboflow(roboflow_key))]
    elif args.source == "hf":
        order = [("hf", lambda: _download_hf(hf_token))]
    elif args.source == "ultralytics":
        order = [("ultralytics", _download_ultralytics)]
    else:  # auto
        order = [
            ("roboflow",    lambda: _download_roboflow(roboflow_key) if roboflow_key else False),
            ("hf",          lambda: _download_hf(hf_token)),
            ("ultralytics", _download_ultralytics),
        ]

    for name, fn in order:
        try:
            if fn():
                print(f"\n[ERR-001] RESOLVED via '{name}'. Vision engine will leave mock mode.")
                sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR in source '{name}': {exc}")

    print(
        "\n[ERR-001] All download sources failed.\n"
        "  See models/vision/README.md for manual installation instructions.\n"
        "  Vision engine will continue in MOCK_MODE until the model is provided."
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
