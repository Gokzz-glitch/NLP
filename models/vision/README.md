# models/vision — ONNX Vision Models

## Expected files

| Filename | Size | Description |
|---|---|---|
| `indian_traffic_yolov8.onnx` | ~6 MB | YOLOv8n trained on Indian road-sign & traffic-enforcement dataset |

---

## ERR-001 — How to obtain the model

### Option A: Automated download (Roboflow, requires API key)

```bash
# 1. Set credentials in .env (see .env.example)
cp .env.example .env
# Edit .env and add ROBOFLOW_API_KEY

# 2. Run the download script
python scripts/download_models.py
```

### Option B: HuggingFace (no API key required for public repos)

```bash
python scripts/download_models.py --source hf
```

### Option C: Base YOLOv8n (pipeline smoke-test only, wrong class labels)

```bash
python scripts/download_models.py --source ultralytics
```

---

## Label contract

`vision_audit.py` expects detections whose `label` values match:

```
INDIAN_TRAFFIC_CLASSES = [
    "speed_limit_sign", "stop_sign", "no_entry",
    "pedestrian_crossing", "speed_camera",
    "traffic_light_red", "traffic_light_green", "traffic_light_yellow",
    "pothole", "road_work", "pedestrian", "two_wheeler",
    "auto_rickshaw", "car", "bus", "truck",
]
```

---

## Git note

`*.onnx` files are in `.gitignore` to avoid committing large binaries.
The empty `.gitkeep` keeps this directory tracked.
