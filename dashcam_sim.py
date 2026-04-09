#!/usr/bin/env python3
"""
dashcam_sim.py — SmartSalai Edge-Sentinel Basic Dashcam Simulation
====================================================================

Minimal laptop-friendly simulation that:
  1. Reads config from environment / defaults (1080p / 30 fps, single front cam)
  2. Opens a video file or synthetic frame source (no camera hardware required)
  3. Runs each frame through the VisionAuditEngine (mock mode if no model)
  4. Feeds generated IMU data through the NearMissDetector
  5. Publishes events on the AgentBus (Section 208, TTS, iRAD)
  6. Prints a brief per-frame report and exits cleanly

Usage (laptop, no hardware):
    python dashcam_sim.py                          # 30 synthetic frames, mock vision
    python dashcam_sim.py --source my_drive.mp4    # real video file
    python dashcam_sim.py --frames 60 --fps 30     # custom frame count / fps

SAFETY NOTICE:
  This is a RESEARCH / SIMULATION tool.  It is NOT certified for any
  safety-critical or real-vehicle deployment.  The driver remains solely
  responsible for vehicle operation at all times.
"""

import argparse
import os
import sys
import time
import random
import math

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.dashcam_defaults import (
    DashcamConfig,
    detect_source_properties,
    PRESETS,
    DEFAULT_FPS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_bgr_frame(width: int, height: int, frame_idx: int) -> np.ndarray:
    """Generate a deterministic BGR frame (gradient + noise) — no camera needed."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = (frame_idx * 3) % 256          # B channel — slow sweep
    frame[:, :, 2] = 200                             # R channel — constant
    noise = np.random.randint(0, 30, (height, width, 3), dtype=np.uint8)
    frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return frame


def _synthetic_imu(frame_idx: int, fps: float):
    """
    Generate synthetic IMU sample (ax, ay, az in m/s²).
    Simulates normal driving with an emergency swerve near the end.
    """
    # Simulate a hard lateral swerve in the final 20 % of every 10-second cycle
    # (fps * 10 = samples per cycle; fps * 8 = 80 % mark within that cycle)
    if frame_idx % max(1, int(fps * 10)) > int(fps * 8):
        ax, ay, az = -6.5, 5.5, 9.9
    else:
        jitter = lambda s: random.gauss(0, s)
        ax, ay, az = jitter(0.3), jitter(0.1), 9.81 + jitter(0.05)
    return ax, ay, az


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def run_simulation(cfg: DashcamConfig, n_frames: int, verbose: bool = True) -> dict:
    """
    Run the basic single-dashcam simulation.

    Returns a summary dict:
      {
        "frames_processed": int,
        "near_misses": int,
        "sec208_challenges": int,
        "tts_announcements": int,
        "irad_records": int,
        "mock_vision": bool,
        "elapsed_s": float,
      }
    """
    from core.agent_bus import AgentBus, Topics, reset_bus
    from agents.imu_near_miss_detector import NearMissDetector, IMUSample
    from agents.sec208_drafter import Sec208DrafterAgent
    from agents.acoustic_ui import AcousticUIAgent
    from core.irad_serializer import IRADSerializer
    from vision_audit import VisionAuditEngine

    reset_bus()
    bus = AgentBus()
    bus.start()

    # Counters wired to the bus
    counts = {
        "near_misses": 0,
        "sec208_challenges": 0,
        "tts_announcements": 0,
        "irad_records": 0,
    }
    bus.subscribe(Topics.IMU_NEAR_MISS,   lambda m: counts.__setitem__("near_misses",       counts["near_misses"] + 1))
    bus.subscribe(Topics.LEGAL_CHALLENGE, lambda m: counts.__setitem__("sec208_challenges", counts["sec208_challenges"] + 1))
    bus.subscribe(Topics.TTS_ANNOUNCE,    lambda m: counts.__setitem__("tts_announcements", counts["tts_announcements"] + 1))
    bus.subscribe(Topics.IRAD_EMIT,       lambda m: counts.__setitem__("irad_records",       counts["irad_records"] + 1))

    cam       = cfg.primary
    engine    = VisionAuditEngine()          # auto-mock if no model
    detector  = NearMissDetector()
    detector.load()
    drafter   = Sec208DrafterAgent()
    drafter.attach_bus(bus)
    tts       = AcousticUIAgent(silent=True)
    tts.attach_bus(bus)
    tts.start()
    serializer = IRADSerializer()

    # --- optional: open real video source ---
    cap = None
    source = cam.source
    if source != "0" and os.path.isfile(source):
        try:
            import cv2
            cap = cv2.VideoCapture(source)
            if cap.isOpened() and cam.auto_detect:
                props = detect_source_properties(source)
                if props:
                    cam.width  = props["width"]
                    cam.height = props["height"]
                    cam.fps    = props["fps"]
        except ImportError:
            cap = None

    if verbose:
        print(f"\n{'='*60}")
        print(" SmartSalai Edge-Sentinel — Basic Dashcam Simulation")
        print(f"{'='*60}")
        print(cfg.summary())
        print(f"Frames     : {n_frames}")
        print(f"Vision     : {'MOCK (no model)' if engine.is_mock else 'ONNX'}")
        print(f"{'='*60}\n")

    t0     = time.time()
    t_ms   = int(t0 * 1000)
    fps    = cam.fps or DEFAULT_FPS
    dt_ms  = int(1000 / fps)

    for i in range(n_frames):
        t_ms += dt_ms

        # --- acquire frame ---
        frame = None
        if cap is not None and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                if verbose:
                    print(f"  [frame {i:04d}] video EOF — stopping early")
                break
        else:
            frame = _synthetic_bgr_frame(cam.width, cam.height, i)

        # --- vision inference ---
        detections = engine.run_inference(frame)

        # --- IMU ---
        ax, ay, az = _synthetic_imu(i, fps)
        sample = IMUSample(t_ms, ax, ay, az, 0, 0, 90.0 if i > int(n_frames * 0.8) else 0.0)
        event  = detector.push_sample(sample)

        if event:
            event_dict = {
                "severity":        event.severity.value,
                "near_miss_score": float(event.tcn_anomaly_score),
                "speed_kmh":       float(event.vehicle_speed_kmh) if event.vehicle_speed_kmh else 0.0,
                "gps_lat": None,
                "gps_lon": None,
            }
            bus.publish(Topics.IMU_NEAR_MISS, event_dict)
            record = serializer.from_near_miss(event_dict)
            record.finalise()
            bus.publish(Topics.IRAD_EMIT, record.to_dict())
            if verbose:
                print(f"  [frame {i:04d}] ⚠ NEAR-MISS severity={event.severity.value}")

        # --- Section 208 ---
        if detections or (engine.is_mock and i == int(n_frames * 0.9)):
            # In mock mode, inject a synthetic speed-camera event once
            mock_dets = detections or [{"label": "speed_camera", "confidence": 0.85, "bbox": [0.3, 0.1, 0.7, 0.6]}]
            has_sign  = any(d["label"] == "speed_limit_sign" for d in mock_dets)
            has_cam   = any(d["label"] == "speed_camera"     for d in mock_dets)
            if has_cam:
                result = drafter.evaluate(
                    camera_data={"device_id": f"CAM-{cam.label.upper()}", "lat": 13.0827, "lon": 80.2707},
                    signage_detected=has_sign,
                    vision_detections=mock_dets,
                )
                if result["status"] == "CHALLENGE_GENERATED":
                    bus.publish(Topics.LEGAL_CHALLENGE, result)
                    bus.publish(Topics.TTS_ANNOUNCE, {
                        "text": "Speed camera without signage. Section 208 challenge registered.",
                        "critical": False,
                    })
                    if verbose:
                        print(f"  [frame {i:04d}] ⚖  Section 208 challenge filed")

    elapsed = time.time() - t0
    time.sleep(0.15)   # let bus drain

    if cap is not None:
        cap.release()
    bus.stop()
    reset_bus()

    summary = {
        "frames_processed":  i + 1,
        "near_misses":       counts["near_misses"],
        "sec208_challenges": counts["sec208_challenges"],
        "tts_announcements": counts["tts_announcements"],
        "irad_records":      counts["irad_records"],
        "mock_vision":       engine.is_mock,
        "elapsed_s":         round(elapsed, 2),
    }

    if verbose:
        print(f"\n{'='*60}")
        print(" Simulation Complete")
        print(f"{'='*60}")
        for k, v in summary.items():
            print(f"  {k:<22}: {v}")
        print(f"{'='*60}\n")

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SmartSalai Basic Dashcam Simulation (laptop-friendly)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", default=None,
                        help="Video file path or device index (default: synthetic frames)")
    parser.add_argument("--frames", type=int, default=60,
                        help="Number of frames to process (default: 60)")
    parser.add_argument("--fps",    type=float, default=None,
                        help="Override FPS (default: auto-detect or 30)")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), default=None,
                        help="Resolution preset: 720p / 1080p / 4K (default: 1080p)")
    parser.add_argument("--quiet",  action="store_true",
                        help="Suppress per-frame output")
    args = parser.parse_args()

    cfg = DashcamConfig.from_env()
    if args.source:
        cfg.primary.source = args.source
    if args.fps:
        cfg.primary.fps = args.fps
    if args.preset:
        w, h = PRESETS[args.preset]
        cfg.primary.width  = w
        cfg.primary.height = h

    run_simulation(cfg, n_frames=args.frames, verbose=not args.quiet)


if __name__ == "__main__":
    main()
