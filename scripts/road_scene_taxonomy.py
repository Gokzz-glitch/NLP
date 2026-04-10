from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY_PATH = PROJECT_ROOT / "road_scene_taxonomy.json"

DEFAULT_ROAD_SCENE_CLASSES: List[str] = [
    "pothole",
    "manhole",
    "road_debris",
    "speed_bump",
    "roadwork",
    "accident",
    "vehicle",
    "pedestrian",
    "cyclist",
    "animal",
    "traffic_light",
    "stop_sign",
    "speed_limit_sign",
    "traffic_sign",
    "lane_marking",
    "crosswalk",
    "road_barrier",
    "cone",
    "road_surface_anomaly",
    "speed_camera",
    "other_road_object",
]

DEFAULT_ROAD_SCENE_ALIASES: Dict[str, List[str]] = {
    "pothole": ["pothole", "road_hole", "hole", "crater"],
    "manhole": ["manhole", "drain_cover", "utility_cover"],
    "road_debris": ["debris", "road_debris", "trash", "obstacle", "object_on_road"],
    "speed_bump": ["speed_bump", "speedbreaker", "speed_breaker", "bump", "hump"],
    "roadwork": ["roadwork", "construction", "work_zone", "road_construction"],
    "accident": ["accident", "collision", "crash", "wreck"],
    "vehicle": ["vehicle", "car", "truck", "bus", "van", "auto", "jeep"],
    "pedestrian": ["pedestrian", "person", "walker", "human"],
    "cyclist": ["cyclist", "bicycle", "bike", "rider", "motorcyclist"],
    "animal": ["animal", "dog", "cow", "buffalo", "cat"],
    "traffic_light": ["traffic_light", "traffic light", "signal", "stoplight"],
    "stop_sign": ["stop_sign", "stop sign", "stop board"],
    "speed_limit_sign": ["speed_limit_sign", "speed sign", "speed board", "speed limit board"],
    "traffic_sign": ["traffic_sign", "traffic sign", "road_sign", "road sign", "signboard", "sign board"],
    "lane_marking": ["lane_marking", "lane line", "lane", "road marking", "marking"],
    "crosswalk": ["crosswalk", "zebra crossing", "pedestrian crossing"],
    "road_barrier": ["road_barrier", "barrier", "guardrail", "divider", "road divider"],
    "cone": ["cone", "traffic cone", "bollard"],
    "road_surface_anomaly": ["road_surface_anomaly", "surface anomaly", "surface damage", "patch"],
    "other_road_object": ["other_road_object", "other", "unknown", "misc"],
}


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace("/", "_")


def load_taxonomy(taxonomy_path: Optional[Path] = None) -> Dict[str, Any]:
    candidate = taxonomy_path or Path(os.getenv("ROAD_SCENE_TAXONOMY_FILE", str(DEFAULT_TAXONOMY_PATH)))
    if candidate.exists():
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {
        "classes": list(DEFAULT_ROAD_SCENE_CLASSES),
        "aliases": dict(DEFAULT_ROAD_SCENE_ALIASES),
    }


def class_names(taxonomy_path: Optional[Path] = None) -> List[str]:
    payload = load_taxonomy(taxonomy_path)
    classes = payload.get("classes", [])
    if not isinstance(classes, list) or not classes:
        return list(DEFAULT_ROAD_SCENE_CLASSES)
    return [str(item).strip() for item in classes if str(item).strip()]


def class_id_map(taxonomy_path: Optional[Path] = None) -> Dict[str, int]:
    return {name: index for index, name in enumerate(class_names(taxonomy_path))}


def alias_map(taxonomy_path: Optional[Path] = None) -> Dict[str, str]:
    payload = load_taxonomy(taxonomy_path)
    aliases = payload.get("aliases", {})
    mapping: Dict[str, str] = {}

    if isinstance(aliases, dict):
        for canonical, values in aliases.items():
            canonical_name = str(canonical).strip()
            if not canonical_name:
                continue
            mapping[_normalize_token(canonical_name)] = canonical_name
            if isinstance(values, list):
                for value in values:
                    token = _normalize_token(value)
                    if token:
                        mapping[token] = canonical_name

    for name in class_names(taxonomy_path):
        mapping[_normalize_token(name)] = name
    return mapping


def canonicalize_label(label: Any, taxonomy_path: Optional[Path] = None) -> str:
    token = _normalize_token(label)
    if not token:
        return "other_road_object"
    mapping = alias_map(taxonomy_path)
    return mapping.get(token, token)


def bbox_to_yolo(box: Sequence[Any], image_width: int, image_height: int) -> Optional[Tuple[float, float, float, float]]:
    if not box or len(box) < 4:
        return None

    try:
        y1, x1, y2, x2 = [float(box[i]) for i in range(4)]
    except Exception:
        return None

    if x2 <= x1 or y2 <= y1:
        return None

    max_coord = max(abs(x1), abs(y1), abs(x2), abs(y2))
    if max_coord <= 1.5:
        # Already normalized to 0..1.
        y1 *= image_height
        y2 *= image_height
        x1 *= image_width
        x2 *= image_width
    elif max_coord <= 1000.0:
        # Default verifier coordinate space.
        y1 = y1 / 1000.0 * image_height
        y2 = y2 / 1000.0 * image_height
        x1 = x1 / 1000.0 * image_width
        x2 = x2 / 1000.0 * image_width

    if x2 <= x1 or y2 <= y1:
        return None

    width = float(image_width)
    height = float(image_height)
    x_center = ((x1 + x2) / 2.0) / width
    y_center = ((y1 + y2) / 2.0) / height
    box_width = (x2 - x1) / width
    box_height = (y2 - y1) / height

    if not all(map(lambda value: 0.0 <= value <= 1.0, [x_center, y_center, box_width, box_height])):
        return None

    return x_center, y_center, box_width, box_height


def deterministic_split_key(image_path: Path) -> int:
    digest = hashlib.sha1(str(image_path).encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:8], 16)


def write_ssl_training_yaml(dataset_root: Path, class_names_list: Sequence[str]) -> Path:
    dataset_root = Path(dataset_root)
    train_manifest = dataset_root / "train.txt"
    val_manifest = dataset_root / "val.txt"
    yaml_path = dataset_root / "data.yaml"
    classes = [str(name).strip() for name in class_names_list if str(name).strip()]
    lines = [
        f"path: {dataset_root.as_posix()}",
        f"train: {train_manifest.name}",
        f"val: {val_manifest.name}",
        f"nc: {len(classes)}",
        "names:",
    ]
    for name in classes:
        lines.append(f"  - {name}")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path
