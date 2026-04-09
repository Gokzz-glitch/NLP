"""
simulation/dashcam_sim.py
=========================
Single front-facing dashcam simulation harness — Track 1.

Purpose
-------
Run the SmartSalai Edge-Sentinel vision + IMU pipeline against a dashcam
video (or synthetic frames in CI) and emit per-frame advisory events.

This is the **primary simulation target** before 360-degree hardware is
available.  All 360-camera logic lives in ``camera_ingest.MultiCameraRig``
and can be plugged in later without changing this file's public API.

Hardware target (Track 1)
--------------------------
* Acer Aspire 7, Intel i5-12th gen, 8/16 GB RAM
* NVIDIA GeForce RTX 3050 Mobile, 4 GB VRAM
* Single USB/built-in dashcam (see ``config_acer_aspire7.yaml``)

SAFETY NOTE
-----------
All outputs are **advisory / informational only**.
No driving, braking, or steering decisions are made.
The driver remains solely responsible for safe vehicle operation.
See SAFETY.md for the full disclaimer.

Usage (CLI)
-----------
    # Replay a recorded dashcam file:
    python -m simulation.dashcam_sim --source file --path /path/to/dashcam.mp4

    # Capture from a live USB dashcam (device index 0):
    python -m simulation.dashcam_sim --source device --device-index 0

    # CI / smoke-test mode (synthetic frames, no real camera needed):
    python -m simulation.dashcam_sim --source synthetic --max-frames 30

    # Limit to first N frames from a file:
    python -m simulation.dashcam_sim --source file --path dashcam.mp4 --max-frames 100
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

# Ensure repo root is importable when executed as a script
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from simulation.camera_ingest import (
    CalibrationParams,
    CameraFrame,
    CameraSource,
    DashcamDeviceSource,
    DashcamFileSource,
    SyntheticFrameSource,
)

logger = logging.getLogger("dashcam_sim")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DashcamSimConfig:
    """
    Runtime configuration for the dashcam simulation harness.

    All values map directly to the YAML keys in ``config_acer_aspire7.yaml``.
    """
    # Camera
    source: str = "synthetic"           # "file" | "device" | "synthetic"
    path: str = ""                       # dashcam file path (source="file")
    device_index: int = 0               # USB/CSI device index (source="device")
    max_frames: Optional[int] = None    # None → process entire source

    # Frame processing
    target_fps: float = 15.0            # Downsample to this FPS (0 = no limit)
    resize_width: int = 640             # Resize before running inference
    resize_height: int = 360

    # Detection thresholds (advisory only — never used for control decisions)
    detection_confidence_min: float = 0.45
    iou_threshold: float = 0.40

    # IMU fusion (forward to NearMissDetector)
    imu_sample_rate_hz: float = 100.0
    imu_window_size_samples: int = 128

    # Hardware
    use_gpu: bool = True                # Use CUDA/TensorRT if available
    num_cpu_threads: int = 4

    # Output
    output_jsonl: str = ""              # Write one JSON object per frame here
    show_display: bool = False          # Show OpenCV window (requires display)

    @classmethod
    def from_yaml(cls, path: str) -> "DashcamSimConfig":
        """Load config from a YAML file (requires PyYAML)."""
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ImportError("PyYAML is required: pip install pyyaml") from exc
        with open(path) as fh:
            data = yaml.safe_load(fh)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Frame-level result
# ---------------------------------------------------------------------------

@dataclass
class FrameResult:
    """Advisory output produced for a single dashcam frame."""
    frame_index: int
    timestamp_s: float
    camera_id: str
    # Detections list (label, confidence, bbox_xywh)
    detections: List[Dict[str, Any]] = field(default_factory=list)
    # High-level advisory events
    advisory_events: List[str] = field(default_factory=list)
    # Processing latency
    inference_ms: float = 0.0
    frame_width: int = 0
    frame_height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Minimal stub detector (no model weights required for simulation / CI)
# ---------------------------------------------------------------------------

class _StubDetector:
    """
    Rule-based, deterministic stub that mimics a YOLO-style detector.

    Used when the ONNX model is not available (CI, first-time setup).
    Produces plausible detections based on frame brightness heuristics so
    downstream logic can be exercised without real model weights.

    NOT FOR PRODUCTION USE — replace with the real ONNX inference pipeline.
    """

    LABELS = [
        "vehicle", "pedestrian", "speed_limit_sign",
        "pothole", "speed_camera", "traffic_light",
    ]

    def __init__(self, conf_threshold: float = 0.45) -> None:
        self.conf_threshold = conf_threshold

    def predict(self, bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Return a list of {label, confidence, bbox_xywh} dicts."""
        h, w = bgr.shape[:2]
        brightness = float(bgr.mean())
        detections: List[Dict[str, Any]] = []

        # Heuristic: very dark frames → night, very bright → daytime
        rng = np.random.default_rng(seed=int(brightness * 1000) & 0xFFFF_FFFF)

        n_det = rng.integers(0, 4)
        for _ in range(n_det):
            label = self.LABELS[rng.integers(len(self.LABELS))]
            conf = float(rng.uniform(0.40, 0.95))
            if conf < self.conf_threshold:
                continue
            bx = int(rng.uniform(0, w * 0.7))
            by = int(rng.uniform(0, h * 0.7))
            bw = int(rng.uniform(w * 0.05, w * 0.25))
            bh = int(rng.uniform(h * 0.05, h * 0.25))
            detections.append({
                "label": label,
                "confidence": round(conf, 3),
                "bbox_xywh": [bx, by, bw, bh],
            })
        return detections


# ---------------------------------------------------------------------------
# Advisory event generator
# ---------------------------------------------------------------------------

_ADVISORY_RULES: List[Dict[str, Any]] = [
    {
        "label": "speed_camera",
        "event": "ADVISORY: Speed camera detected ahead — check your speed.",
    },
    {
        "label": "pothole",
        "event": "ADVISORY: Road hazard (pothole) detected — reduce speed.",
    },
    {
        "label": "pedestrian",
        "event": "ADVISORY: Pedestrian detected — stay alert.",
    },
    {
        "label": "traffic_light",
        "event": "ADVISORY: Traffic signal detected — be prepared to stop.",
    },
]


def _generate_advisory_events(detections: List[Dict[str, Any]]) -> List[str]:
    labels_seen = {d["label"] for d in detections}
    return [
        rule["event"]
        for rule in _ADVISORY_RULES
        if rule["label"] in labels_seen
    ]


# ---------------------------------------------------------------------------
# Main simulation harness
# ---------------------------------------------------------------------------

class DashcamSimulator:
    """
    End-to-end dashcam simulation harness.

    Parameters
    ----------
    config : DashcamSimConfig
        Runtime configuration.
    detector : optional
        Object with a ``predict(bgr) -> List[Dict]`` method.  Defaults to
        ``_StubDetector`` when no real model is available.

    Example
    -------
    ::

        cfg = DashcamSimConfig(source="synthetic", max_frames=30)
        sim = DashcamSimulator(cfg)
        results = sim.run()
        print(f"Processed {len(results)} frames")
    """

    def __init__(self, config: DashcamSimConfig,
                 detector: Any = None) -> None:
        self.config = config
        self.detector = detector or _StubDetector(
            conf_threshold=config.detection_confidence_min
        )
        self._results: List[FrameResult] = []

    # -- source factory ------------------------------------------------------

    def _build_source(self) -> CameraSource:
        cfg = self.config
        if cfg.source == "file":
            if not cfg.path:
                raise ValueError("DashcamSimConfig.path must be set when source='file'")
            return DashcamFileSource(
                path=cfg.path,
                camera_id="front",
                max_frames=cfg.max_frames,
            )
        if cfg.source == "device":
            return DashcamDeviceSource(
                device_index=cfg.device_index,
                camera_id="front",
                width=1920, height=1080,
                fps=int(cfg.target_fps) or 30,
                max_frames=cfg.max_frames,
            )
        if cfg.source == "synthetic":
            return SyntheticFrameSource(
                camera_id="front",
                width=cfg.resize_width,
                height=cfg.resize_height,
                fps=int(cfg.target_fps) or 30,
                max_frames=cfg.max_frames or 30,
            )
        raise ValueError(
            f"Unknown source {cfg.source!r}. Valid: 'file', 'device', 'synthetic'"
        )

    # -- optional resize -----------------------------------------------------

    def _maybe_resize(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        th, tw = self.config.resize_height, self.config.resize_width
        if (h, w) == (th, tw):
            return bgr
        try:
            import cv2  # type: ignore
            return cv2.resize(bgr, (tw, th))
        except ImportError:
            # Cheap nearest-neighbour fallback (no deps needed for synthetic)
            row_idx = (np.arange(th) * h // th).astype(int)
            col_idx = (np.arange(tw) * w // tw).astype(int)
            return bgr[np.ix_(row_idx, col_idx)]

    # -- FPS limiter ---------------------------------------------------------

    def _fps_limiter(self) -> "_FPSLimiter":
        return _FPSLimiter(self.config.target_fps)

    # -- main loop -----------------------------------------------------------

    def run(self) -> List[FrameResult]:
        """
        Process all frames from the configured source.

        Returns the list of per-frame advisory results.
        Writes JSONL to ``config.output_jsonl`` if set.
        """
        self._results = []
        source = self._build_source()
        limiter = self._fps_limiter()
        jsonl_fh = None

        if self.config.output_jsonl:
            os.makedirs(os.path.dirname(self.config.output_jsonl) or ".", exist_ok=True)
            jsonl_fh = open(self.config.output_jsonl, "w")

        try:
            with source:
                for frame in source.stream():
                    limiter.wait()
                    result = self._process_frame(frame)
                    self._results.append(result)
                    if jsonl_fh:
                        jsonl_fh.write(json.dumps(result.to_dict()) + "\n")
                    if self.config.show_display:
                        self._maybe_display(frame, result)
        finally:
            if jsonl_fh:
                jsonl_fh.close()

        logger.info(
            "DashcamSimulator finished: %d frames processed, "
            "%d advisory events total.",
            len(self._results),
            sum(len(r.advisory_events) for r in self._results),
        )
        return self._results

    def _process_frame(self, frame: CameraFrame) -> FrameResult:
        bgr = self._maybe_resize(frame.bgr)
        t0 = time.perf_counter()
        detections = self.detector.predict(bgr)
        inference_ms = (time.perf_counter() - t0) * 1000.0
        advisory_events = _generate_advisory_events(detections)

        return FrameResult(
            frame_index=frame.frame_index,
            timestamp_s=frame.timestamp_s,
            camera_id=frame.camera_id,
            detections=detections,
            advisory_events=advisory_events,
            inference_ms=round(inference_ms, 2),
            frame_width=bgr.shape[1],
            frame_height=bgr.shape[0],
        )

    def _maybe_display(self, frame: CameraFrame, result: FrameResult) -> None:
        """Draw advisory overlay and show an OpenCV window (optional)."""
        try:
            import cv2  # type: ignore
        except ImportError:
            return
        bgr = frame.bgr.copy()
        for ev in result.advisory_events:
            cv2.putText(bgr, ev[:60], (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("SmartSalai — Dashcam Advisory", bgr)
        cv2.waitKey(1)

    # -- summary -------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return a JSON-serialisable summary of the simulation run."""
        n = len(self._results)
        all_events = [ev for r in self._results for ev in r.advisory_events]
        label_counts: Dict[str, int] = {}
        for r in self._results:
            for d in r.detections:
                label_counts[d["label"]] = label_counts.get(d["label"], 0) + 1
        avg_lat = (
            sum(r.inference_ms for r in self._results) / n if n else 0.0
        )
        return {
            "frames_processed": n,
            "total_advisory_events": len(all_events),
            "unique_advisory_events": list(set(all_events)),
            "detection_label_counts": label_counts,
            "avg_inference_ms": round(avg_lat, 2),
            "source": self.config.source,
        }


# ---------------------------------------------------------------------------
# FPS limiter helper
# ---------------------------------------------------------------------------

class _FPSLimiter:
    def __init__(self, target_fps: float) -> None:
        self._period = 1.0 / target_fps if target_fps > 0 else 0.0
        self._last = time.monotonic()

    def wait(self) -> None:
        if self._period <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self._period:
            time.sleep(self._period - elapsed)
        self._last = time.monotonic()


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SmartSalai — Dashcam Simulation Harness (Track 1: single front camera)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--source", choices=["file", "device", "synthetic"],
                   default="synthetic",
                   help="Camera source type.")
    p.add_argument("--path", default="",
                   help="Dashcam video file path (required when --source=file).")
    p.add_argument("--device-index", type=int, default=0,
                   help="USB/CSI device index (--source=device only).")
    p.add_argument("--max-frames", type=int, default=None,
                   help="Stop after this many frames (None = full source).")
    p.add_argument("--target-fps", type=float, default=15.0,
                   help="Processing frame rate (0 = no limit).")
    p.add_argument("--resize-width", type=int, default=640)
    p.add_argument("--resize-height", type=int, default=360)
    p.add_argument("--output-jsonl", default="",
                   help="Write per-frame advisory JSON-lines to this file.")
    p.add_argument("--show-display", action="store_true",
                   help="Show OpenCV window (requires a display / X11).")
    p.add_argument("--config", default="",
                   help="Path to YAML config (overrides all CLI flags).")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    if args.config:
        cfg = DashcamSimConfig.from_yaml(args.config)
    else:
        cfg = DashcamSimConfig(
            source=args.source,
            path=args.path,
            device_index=args.device_index,
            max_frames=args.max_frames,
            target_fps=args.target_fps,
            resize_width=args.resize_width,
            resize_height=args.resize_height,
            output_jsonl=args.output_jsonl,
            show_display=args.show_display,
        )

    sim = DashcamSimulator(cfg)
    sim.run()
    summary = sim.summary()

    print("\n── Dashcam Simulation Summary ──────────────────────────────────")
    print(json.dumps(summary, indent=2))
    print("────────────────────────────────────────────────────────────────")
    print(
        "\n[SAFETY] All outputs above are ADVISORY / INFORMATIONAL ONLY.\n"
        "         The driver is solely responsible for safe vehicle operation.\n"
        "         See SAFETY.md for the full disclaimer.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
