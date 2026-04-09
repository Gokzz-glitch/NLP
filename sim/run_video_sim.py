"""
sim/run_video_sim.py
SmartSalai Edge-Sentinel — Video / Synthetic Simulation Harness

Runs the detection + IMU pipeline on either:
  (a) A recorded video clip (dashcam / 360-cam) — requires OpenCV
  (b) Synthetic frames (--synthetic flag) — no video file needed

For each frame / IMU sample, collects and exports:
  - Frame latency (ms per frame)
  - Throughput (FPS)
  - Peak memory usage (MB)
  - Detection counts per class
  - Near-miss event counts by severity
  - Scenario metadata

Output is a JSON metrics file (--metrics-out) and a terminal summary.

IMPORTANT — SIMULATION ONLY:
  Outputs of this script are for offline research evaluation.
  Do NOT use these metrics to claim real-world ADAS readiness.

Usage:
  # Synthetic (no video clip needed):
  python sim/run_video_sim.py --synthetic --duration 60 --metrics-out /tmp/metrics.json

  # Real clip (requires OpenCV):
  python sim/run_video_sim.py --video 360-cam.mp4 --scenario urban_arterial_day \\
         --vehicle car_compact --metrics-out /tmp/metrics.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s [SIM] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("edge_sentinel.sim")

# ──────────────────────────────────────────────────────────────────────────────
# Optional heavy imports
# ──────────────────────────────────────────────────────────────────────────────

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import numpy as np
    NP_AVAILABLE = True
except ImportError:
    NP_AVAILABLE = False

# ──────────────────────────────────────────────────────────────────────────────
# Metrics data structure
# ──────────────────────────────────────────────────────────────────────────────

SAFETY_DISCLAIMER = (
    "SIMULATION ONLY — NOT CERTIFIED ADAS — "
    "DO NOT USE TO MAKE REAL DRIVING DECISIONS"
)


@dataclass
class SimMetrics:
    scenario_name: str
    vehicle_class: str
    mode: str                        # "synthetic" | "video"
    video_path: Optional[str]
    duration_s: float
    total_frames: int
    frames_processed: int
    dropped_frames: int

    # Timing
    frame_latencies_ms: List[float] = field(default_factory=list)
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_fps: float = 0.0

    # Memory
    peak_memory_mb: float = 0.0
    avg_memory_mb: float = 0.0

    # Detection counts
    detection_counts: Dict[str, int] = field(default_factory=dict)
    near_miss_counts: Dict[str, int] = field(default_factory=dict)

    # Section 208 events
    sec208_triggers: int = 0

    # iRAD records emitted
    irad_records_emitted: int = 0

    disclaimer: str = SAFETY_DISCLAIMER

    def finalise(self) -> "SimMetrics":
        lats = sorted(self.frame_latencies_ms)
        n = len(lats)
        if n:
            self.avg_latency_ms = sum(lats) / n
            self.p95_latency_ms = lats[int(0.95 * n)]
            self.p99_latency_ms = lats[int(0.99 * n)]
        if self.duration_s > 0:
            self.avg_fps = self.frames_processed / self.duration_s
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Trim raw latency list to keep JSON manageable
        if len(d["frame_latencies_ms"]) > 500:
            d["frame_latencies_ms"] = d["frame_latencies_ms"][:500]
        return d


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic frame generator
# ──────────────────────────────────────────────────────────────────────────────

def _generate_synthetic_frame(scenario, vehicle, frame_idx: int) -> Dict[str, Any]:
    """
    Return a fake 'frame result' that mimics what the SignAuditorAgent
    would return on a real frame.  Parameterised by road scenario and
    vehicle class kinematic modifiers.
    """
    rng = random.Random(frame_idx)  # reproducible per-frame

    # Randomly detect objects based on scenario camera density and traffic
    detections = []
    if rng.random() < scenario.camera_density_per_km * 0.01:
        detections.append({
            "label": "speed_camera",
            "confidence": round(rng.uniform(0.72, 0.96), 3),
            "bbox": [0.3, 0.1, 0.7, 0.4],
        })
    if rng.random() < 0.04:
        detections.append({
            "label": "speed_limit_sign",
            "confidence": round(rng.uniform(0.70, 0.95), 3),
            "bbox": [0.1, 0.0, 0.3, 0.3],
        })
    if rng.random() < scenario.pothole_prob_per_s / 30.0:
        detections.append({
            "label": "pothole",
            "confidence": round(rng.uniform(0.60, 0.90), 3),
            "bbox": [0.4, 0.6, 0.6, 0.9],
        })

    return {
        "frame_idx": frame_idx,
        "detections": detections,
        "sec208_trigger": False,  # set by auditor logic below
    }


def _generate_synthetic_imu(scenario, vehicle, t_s: float) -> Dict[str, float]:
    """
    Return synthetic 6-DOF IMU values for the given time point.
    Incorporates road roughness, pothole spikes, and speed-bump events.
    """
    rng = random.Random(int(t_s * 1000))
    roughness = scenario.roughness_rms_g * rng.gauss(0, 1)

    # Pothole spike
    spike_z = 0.0
    if rng.random() < scenario.pothole_prob_per_s / 100.0:
        spike_z = scenario.pothole_jerk_ms3 * rng.uniform(0.8, 1.2)

    # Lateral cornering
    lat_g = 0.0
    if rng.random() < scenario.sharp_turn_prob_per_s / 100.0:
        lat_g = rng.uniform(*scenario.lateral_g_range) * vehicle.lateral_g_multiplier

    return {
        "ax": lat_g * 9.80665,
        "ay": roughness * 9.80665,
        "az": 9.80665 + spike_z * vehicle.jerk_multiplier,
        "gx": 0.0,
        "gy": 0.0,
        "gz": lat_g * 30.0,  # rough yaw rate approximation
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main simulation runner
# ──────────────────────────────────────────────────────────────────────────────

def run_simulation(
    mode: str = "synthetic",
    video_path: Optional[str] = None,
    scenario_name: str = "urban_arterial_day",
    vehicle_name: str = "two_wheeler_100cc",
    duration_s: float = 60.0,
    target_fps: float = 30.0,
) -> SimMetrics:
    """
    Run the pipeline on synthetic or video input and return SimMetrics.

    Parameters
    ----------
    mode          : "synthetic" or "video"
    video_path    : path to video file (only used if mode="video")
    scenario_name : key from sim.scenarios.ROAD_SCENARIOS
    vehicle_name  : key from sim.scenarios.VEHICLE_CLASSES
    duration_s    : simulation duration in seconds (synthetic mode only)
    target_fps    : target frame rate for synthetic mode
    """
    from sim.scenarios import ROAD_SCENARIOS, VEHICLE_CLASSES
    from agents.imu_near_miss_detector import NearMissDetector, IMUSample
    from agents.sign_auditor import SignAuditorAgent
    from agents.sec208_drafter import Sec208DrafterAgent
    from core.irad_serializer import IRADSerializer

    scenario = ROAD_SCENARIOS.get(scenario_name)
    if scenario is None:
        raise ValueError(f"Unknown scenario: {scenario_name!r}. "
                         f"Available: {list(ROAD_SCENARIOS.keys())}")

    vehicle = VEHICLE_CLASSES.get(vehicle_name)
    if vehicle is None:
        raise ValueError(f"Unknown vehicle: {vehicle_name!r}. "
                         f"Available: {list(VEHICLE_CLASSES.keys())}")

    metrics = SimMetrics(
        scenario_name=scenario.name,
        vehicle_class=vehicle.name,
        mode=mode,
        video_path=video_path,
        duration_s=duration_s,
        total_frames=0,
        frames_processed=0,
        dropped_frames=0,
    )

    # Initialise pipeline components
    detector = NearMissDetector()
    detector.load()

    auditor = SignAuditorAgent(model_path="/nonexistent/model.onnx")
    auditor.load()

    drafter = Sec208DrafterAgent()
    serializer = IRADSerializer()

    # Start memory tracking
    tracemalloc.start()
    mem_samples: List[float] = []

    logger.info(
        f"[SIM START] scenario={scenario.name!r} vehicle={vehicle.name!r} "
        f"mode={mode} duration={duration_s}s"
    )
    logger.warning(f"  ⚠  {SAFETY_DISCLAIMER}")

    wall_start = time.perf_counter()

    if mode == "synthetic":
        n_frames = int(duration_s * target_fps)
        metrics.total_frames = n_frames
        t_ms = int(time.time() * 1000)

        for frame_idx in range(n_frames):
            t_s = frame_idx / target_fps

            frame_wall_start = time.perf_counter()

            # --- IMU sample ---
            imu = _generate_synthetic_imu(scenario, vehicle, t_s)
            t_ms += 10  # 100 Hz IMU
            sample = IMUSample(
                timestamp_epoch_ms=t_ms,
                accel_x_ms2=imu["ax"],
                accel_y_ms2=imu["ay"],
                accel_z_ms2=imu["az"],
                gyro_x_degs=imu["gx"],
                gyro_y_degs=imu["gy"],
                gyro_z_degs=imu["gz"],
            )
            near_miss_event = detector.push_sample(sample)

            if near_miss_event:
                sev = near_miss_event.severity.value
                metrics.near_miss_counts[sev] = metrics.near_miss_counts.get(sev, 0) + 1
                record = serializer.from_near_miss({
                    "severity": sev,
                    "near_miss_score": float(near_miss_event.tcn_anomaly_score),
                    "speed_kmh": 0.0,
                })
                record.finalise()
                metrics.irad_records_emitted += 1

            # --- Vision frame (every 3rd IMU sample ≈ 30 FPS) ---
            if frame_idx % 3 == 0:
                frame_data = _generate_synthetic_frame(scenario, vehicle, frame_idx)
                for det in frame_data["detections"]:
                    lbl = det["label"]
                    metrics.detection_counts[lbl] = (
                        metrics.detection_counts.get(lbl, 0) + 1
                    )

                # Section 208 check
                has_cam = any(d["label"] == "speed_camera" for d in frame_data["detections"])
                has_sign = any(d["label"] == "speed_limit_sign" for d in frame_data["detections"])
                if has_cam:
                    result = drafter.evaluate(
                        camera_data={"device_id": "CAM-SIM", "lat": 12.924, "lon": 80.230},
                        signage_detected=has_sign,
                    )
                    if result["status"] == "CHALLENGE_GENERATED":
                        metrics.sec208_triggers += 1

            frame_latency_ms = (time.perf_counter() - frame_wall_start) * 1000
            metrics.frame_latencies_ms.append(frame_latency_ms)
            metrics.frames_processed += 1

            # Sample memory every 100 frames
            if frame_idx % 100 == 0:
                cur, peak = tracemalloc.get_traced_memory()
                mem_samples.append(peak / 1024 / 1024)

    elif mode == "video":
        if not CV2_AVAILABLE:
            raise ImportError(
                "OpenCV (cv2) is required for video mode. "
                "Install with: pip install opencv-python-headless"
            )
        if not video_path or not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path!r}")

        cap = cv2.VideoCapture(video_path)
        metrics.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        t_ms = int(time.time() * 1000)

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_wall_start = time.perf_counter()

            # SignAuditor on real frame
            result = auditor.process_frame(
                frame=frame, gps_lat=12.924, gps_lon=80.230
            )
            for det in result.get("detections", []):
                lbl = det.get("label", "unknown")
                metrics.detection_counts[lbl] = metrics.detection_counts.get(lbl, 0) + 1

            if result.get("sec208_trigger"):
                metrics.sec208_triggers += 1

            # Synthetic IMU (video doesn't carry IMU)
            imu = _generate_synthetic_imu(scenario, vehicle, frame_idx / 30.0)
            t_ms += 33  # ~30 FPS
            sample = IMUSample(
                timestamp_epoch_ms=t_ms,
                accel_x_ms2=imu["ax"], accel_y_ms2=imu["ay"], accel_z_ms2=imu["az"],
                gyro_x_degs=imu["gx"], gyro_y_degs=imu["gy"], gyro_z_degs=imu["gz"],
            )
            near_miss_event = detector.push_sample(sample)
            if near_miss_event:
                sev = near_miss_event.severity.value
                metrics.near_miss_counts[sev] = metrics.near_miss_counts.get(sev, 0) + 1

            latency_ms = (time.perf_counter() - frame_wall_start) * 1000
            metrics.frame_latencies_ms.append(latency_ms)
            metrics.frames_processed += 1
            frame_idx += 1

            if frame_idx % 100 == 0:
                cur, peak = tracemalloc.get_traced_memory()
                mem_samples.append(peak / 1024 / 1024)

            elapsed = time.perf_counter() - wall_start
            if duration_s and elapsed >= duration_s:
                break

        cap.release()
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use 'synthetic' or 'video'.")

    # Finalise
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    metrics.peak_memory_mb = peak / 1024 / 1024
    metrics.avg_memory_mb = (sum(mem_samples) / len(mem_samples)) if mem_samples else 0.0
    metrics.duration_s = time.perf_counter() - wall_start
    metrics.dropped_frames = metrics.total_frames - metrics.frames_processed
    metrics.finalise()

    return metrics


# ──────────────────────────────────────────────────────────────────────────────
# Terminal report
# ──────────────────────────────────────────────────────────────────────────────

def print_report(m: SimMetrics) -> None:
    print("\n" + "═" * 70)
    print(f"  SmartSalai Edge-Sentinel — Simulation Report")
    print(f"  ⚠  {m.disclaimer}")
    print("═" * 70)
    print(f"  Scenario   : {m.scenario_name}")
    print(f"  Vehicle    : {m.vehicle_class}")
    print(f"  Mode       : {m.mode}" + (f" ({m.video_path})" if m.video_path else ""))
    print(f"  Duration   : {m.duration_s:.1f}s")
    print(f"  Frames     : {m.frames_processed:,} / {m.total_frames:,} "
          f"(dropped: {m.dropped_frames})")
    print("─" * 70)
    print(f"  Latency    : avg={m.avg_latency_ms:.2f}ms "
          f"p95={m.p95_latency_ms:.2f}ms p99={m.p99_latency_ms:.2f}ms")
    print(f"  FPS        : {m.avg_fps:.1f}")
    print(f"  Memory     : peak={m.peak_memory_mb:.1f}MB avg={m.avg_memory_mb:.1f}MB")
    print("─" * 70)
    print(f"  Detections : {m.detection_counts}")
    print(f"  Near-Misses: {m.near_miss_counts}")
    print(f"  Sec-208    : {m.sec208_triggers} trigger(s)")
    print(f"  iRAD       : {m.irad_records_emitted} record(s) emitted")
    print("═" * 70 + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SmartSalai Edge-Sentinel — Simulation Harness (research-only)",
        epilog="⚠  Output is for SIMULATION RESEARCH only. Not ADAS. Not safety-certified.",
    )
    p.add_argument("--synthetic", action="store_true",
                   help="Run synthetic simulation (no video clip required)")
    p.add_argument("--video", metavar="PATH",
                   help="Path to dashcam/360-cam video file (requires OpenCV)")
    p.add_argument("--scenario", default="urban_arterial_day",
                   help="Road scenario key (see sim/scenarios.py)")
    p.add_argument("--vehicle", default="two_wheeler_100cc",
                   help="Vehicle class key (see sim/scenarios.py)")
    p.add_argument("--duration", type=float, default=60.0,
                   help="Simulation duration in seconds (default: 60)")
    p.add_argument("--fps", type=float, default=30.0,
                   help="Target FPS for synthetic mode (default: 30)")
    p.add_argument("--metrics-out", metavar="PATH",
                   help="Path to write JSON metrics output")
    p.add_argument("--all-scenarios", action="store_true",
                   help="Run ALL scenarios × vehicle combinations and export aggregate")
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.all_scenarios:
        from sim.scenarios import ROAD_SCENARIOS, VEHICLE_CLASSES
        all_results = []
        for sc_key in ROAD_SCENARIOS:
            for veh_key in VEHICLE_CLASSES:
                logger.info(f"Running {sc_key} × {veh_key} …")
                m = run_simulation(
                    mode="synthetic",
                    scenario_name=sc_key,
                    vehicle_name=veh_key,
                    duration_s=min(args.duration, 10.0),  # short per-combo in sweep
                    target_fps=args.fps,
                )
                all_results.append(m.to_dict())
        aggregate = {"runs": all_results, "disclaimer": SAFETY_DISCLAIMER}
        out = args.metrics_out or "/tmp/sim_all_scenarios.json"
        with open(out, "w") as f:
            json.dump(aggregate, f, indent=2)
        logger.info(f"Aggregate metrics written to {out}")
        return

    if args.synthetic:
        mode = "synthetic"
        video_path = None
    elif args.video:
        mode = "video"
        video_path = args.video
    else:
        parser.error("Specify --synthetic or --video PATH")
        return

    metrics = run_simulation(
        mode=mode,
        video_path=video_path,
        scenario_name=args.scenario,
        vehicle_name=args.vehicle,
        duration_s=args.duration,
        target_fps=args.fps,
    )

    print_report(metrics)

    if args.metrics_out:
        out_path = args.metrics_out
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        logger.info(f"Metrics written to {out_path}")


if __name__ == "__main__":
    main()
