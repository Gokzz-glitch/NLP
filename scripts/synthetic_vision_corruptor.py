import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.model_registry import resolve_pothole_onnx, resolve_traffic_signs_onnx, resolve_vehicles_chaos_onnx
from scripts.utils.vision_audit import VisionAuditEngine

LOG_FILE = PROJECT_ROOT / "CRUCIBLE_AUDIT_LOG.md"
OUT_DIR = PROJECT_ROOT / "runs" / "crucible" / "vision_corruptor"
REPORT_PATH = OUT_DIR / "vision_corruptor_report.json"


@dataclass
class CorruptionProfile:
    name: str
    blur_kernel: int
    brightness_scale: float
    occlusion_ratio: float


def ensure_dirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def append_log(section_title: str, lines: List[str]) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n## {section_title} ({ts})\n")
        for line in lines:
            f.write(f"- {line}\n")


def collect_media() -> Tuple[List[Path], List[Path]]:
    video_roots = [PROJECT_ROOT / "Testing videos", PROJECT_ROOT / "raw_data"]
    image_roots = [PROJECT_ROOT / "Testing videos", PROJECT_ROOT / "raw_data"]

    videos: List[Path] = []
    images: List[Path] = []

    for root in video_roots:
        if not root.exists():
            continue
        videos.extend(root.rglob("*.mp4"))
        videos.extend(root.rglob("*.mkv"))
        videos.extend(root.rglob("*.avi"))
        videos.extend(root.rglob("*.webm"))

    for root in image_roots:
        if not root.exists():
            continue
        images.extend(root.rglob("*.jpg"))
        images.extend(root.rglob("*.jpeg"))
        images.extend(root.rglob("*.png"))

    # Cap for deterministic runtime
    return videos[:8], images[:20]


def corrupt_frame(frame: np.ndarray, profile: CorruptionProfile, rng: np.random.Generator) -> np.ndarray:
    out = frame.copy()

    if profile.blur_kernel > 1:
        k = profile.blur_kernel if profile.blur_kernel % 2 == 1 else profile.blur_kernel + 1
        out = cv2.GaussianBlur(out, (k, k), 0)

    out = np.clip(out.astype(np.float32) * profile.brightness_scale, 0, 255).astype(np.uint8)

    if profile.occlusion_ratio > 0:
        h, w = out.shape[:2]
        occ_area = int(h * w * profile.occlusion_ratio)
        max_rects = 6
        for _ in range(max_rects):
            rw = int(rng.integers(max(12, w // 12), max(18, w // 3)))
            rh = int(rng.integers(max(12, h // 12), max(18, h // 3)))
            x1 = int(rng.integers(0, max(1, w - rw)))
            y1 = int(rng.integers(0, max(1, h - rh)))
            cv2.rectangle(out, (x1, y1), (x1 + rw, y1 + rh), (0, 0, 0), -1)
            occ_area -= rw * rh
            if occ_area <= 0:
                break

    return out


def max_confidence(detections: Dict[str, List[Dict]]) -> float:
    best = 0.0
    for _, dets in detections.items():
        for d in dets:
            best = max(best, float(d.get("confidence", 0.0)))
    return best


def evaluate_on_frame(engine: VisionAuditEngine, frame: np.ndarray) -> float:
    try:
        detections = engine.run_hazard_audit(frame)
        return max_confidence(detections)
    except Exception:
        return 0.0


def run_corruptor() -> int:
    ensure_dirs()

    models = {
        "pothole": str(resolve_pothole_onnx()),
        "traffic": str(resolve_traffic_signs_onnx()),
        "vehicles": str(resolve_vehicles_chaos_onnx()),
    }
    engine = VisionAuditEngine(models, conf_threshold=0.25)

    if not engine.sessions:
        report = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "skipped_no_models",
            "input_counts": {"videos": 0, "images": 0},
            "profiles": {},
            "recommendations": [],
            "output_dir": str(OUT_DIR),
            "model_candidates": models,
        }
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        append_log(
            "CRUCIBLE Vision Augmenter",
            [
                "No ONNX sessions loaded. Vision corruptor skipped.",
                f"Report written: {REPORT_PATH}",
            ],
        )
        return 0

    videos, images = collect_media()
    rng = np.random.default_rng(208)

    profiles = [
        CorruptionProfile("mild", blur_kernel=5, brightness_scale=0.70, occlusion_ratio=0.05),
        CorruptionProfile("heavy", blur_kernel=11, brightness_scale=0.45, occlusion_ratio=0.12),
        CorruptionProfile("extreme", blur_kernel=17, brightness_scale=0.30, occlusion_ratio=0.20),
    ]

    stats = {
        p.name: {
            "samples": 0,
            "orig_conf_sum": 0.0,
            "corr_conf_sum": 0.0,
            "drop_sum": 0.0,
            "drop_points": [],
        }
        for p in profiles
    }

    def process_pair(frame: np.ndarray, tag: str) -> None:
        base = evaluate_on_frame(engine, frame)
        for p in profiles:
            corr = corrupt_frame(frame, p, rng)
            corr_conf = evaluate_on_frame(engine, corr)
            drop = max(0.0, base - corr_conf)

            s = stats[p.name]
            s["samples"] += 1
            s["orig_conf_sum"] += base
            s["corr_conf_sum"] += corr_conf
            s["drop_sum"] += drop
            s["drop_points"].append({
                "tag": tag,
                "orig": round(base, 4),
                "corr": round(corr_conf, 4),
                "drop": round(drop, 4),
            })

    for img_path in images:
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
        process_pair(frame, img_path.name)

        extreme = corrupt_frame(frame, profiles[-1], rng)
        out_img = OUT_DIR / f"corrupt_{img_path.stem}.jpg"
        cv2.imwrite(str(out_img), extreme)

    for vid_path in videos:
        cap = cv2.VideoCapture(str(vid_path))
        if not cap.isOpened():
            continue
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(1, frame_count // 8)
        idx = 0
        sample_i = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                process_pair(frame, f"{vid_path.name}:f{idx}")
                sample_i += 1
                if sample_i >= 8:
                    break
            idx += 1
        cap.release()

    recommendations = []
    profile_summary = {}

    for p in profiles:
        s = stats[p.name]
        n = max(1, s["samples"])
        avg_drop = s["drop_sum"] / n
        avg_orig = s["orig_conf_sum"] / n
        avg_corr = s["corr_conf_sum"] / n

        threshold_delta = 0.0
        if avg_drop >= 0.20:
            threshold_delta = -0.10
        elif avg_drop >= 0.12:
            threshold_delta = -0.06
        elif avg_drop >= 0.08:
            threshold_delta = -0.04
        else:
            threshold_delta = -0.02

        recommendations.append(
            {
                "profile": p.name,
                "avg_original_confidence": round(avg_orig, 4),
                "avg_corrupted_confidence": round(avg_corr, 4),
                "avg_confidence_drop": round(avg_drop, 4),
                "recommended_conf_threshold_adjustment": threshold_delta,
            }
        )

        sorted_drop_points = sorted(s["drop_points"], key=lambda x: x["drop"], reverse=True)
        profile_summary[p.name] = {
            "samples": s["samples"],
            "avg_original_confidence": round(avg_orig, 4),
            "avg_corrupted_confidence": round(avg_corr, 4),
            "avg_confidence_drop": round(avg_drop, 4),
            "worst_drop_points": sorted_drop_points[:8],
        }

    report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "input_counts": {"videos": len(videos), "images": len(images)},
        "profiles": profile_summary,
        "recommendations": recommendations,
        "output_dir": str(OUT_DIR),
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    lines = [
        f"Processed media: videos={len(videos)} images={len(images)}",
        f"Report written: {REPORT_PATH}",
    ]
    for r in recommendations:
        lines.append(
            f"Profile={r['profile']} avg_drop={r['avg_confidence_drop']} threshold_adjust={r['recommended_conf_threshold_adjustment']}"
        )
    append_log("CRUCIBLE Vision Augmenter", lines)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_corruptor())
