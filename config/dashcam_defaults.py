"""
config/dashcam_defaults.py
SmartSalai Edge-Sentinel — Dashcam Configuration Presets

Default: single front dashcam, 1080p/30 fps.
Architecture is 360-ready: pass a list of CameraConfig objects to enable
multiple cameras; the pipeline processes each stream independently and
merges events on the agent bus.

Override via environment variables (all optional):
  DASHCAM_WIDTH       — frame width  in pixels  (default: 1920)
  DASHCAM_HEIGHT      — frame height in pixels  (default: 1080)
  DASHCAM_FPS         — target frames per second (default: 30)
  DASHCAM_SOURCE      — path to video file, or device index (default: "0")
  DASHCAM_CAMERA_MODE — "single" or "360"        (default: "single")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Resolution presets (width × height)
# ---------------------------------------------------------------------------
PRESETS = {
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "4K":    (3840, 2160),
}

# Default preset — laptop-friendly single dashcam baseline
DEFAULT_PRESET = "1080p"
DEFAULT_FPS    = 30


@dataclass
class CameraConfig:
    """Configuration for a single physical camera / video source."""

    #: Human-readable label, e.g. "front", "rear", "left", "right"
    label: str = "front"

    #: Video source — file path, RTSP URI, or integer device index (0 = first webcam)
    source: str = "0"

    #: Frame width in pixels.  Overridden by auto_detect if source is a file.
    width: int = 1920

    #: Frame height in pixels.  Overridden by auto_detect if source is a file.
    height: int = 1080

    #: Target capture frame rate.  Overridden by auto_detect if source is a file.
    fps: float = 30.0

    #: When True the pipeline reads actual resolution/FPS from the video file.
    auto_detect: bool = True


@dataclass
class DashcamConfig:
    """
    Top-level dashcam configuration.

    Single-camera (default) — laptop-friendly baseline:

        cfg = DashcamConfig.from_env()
        # → one CameraConfig(label="front", source="0", 1080p/30fps)

    360-camera — drop-in extension:

        cfg = DashcamConfig(
            mode="360",
            cameras=[
                CameraConfig("front",  source="front.mp4"),
                CameraConfig("rear",   source="rear.mp4"),
                CameraConfig("left",   source="left.mp4"),
                CameraConfig("right",  source="right.mp4"),
            ]
        )
    """

    #: "single" or "360"
    mode: str = "single"

    #: List of camera configurations.  Single-camera uses one entry.
    cameras: List[CameraConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cameras:
            self.cameras = [_default_front_camera()]

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "DashcamConfig":
        """Build config from environment variables with sensible defaults."""
        mode   = os.getenv("DASHCAM_CAMERA_MODE", "single")
        source = os.getenv("DASHCAM_SOURCE", "0")
        preset = PRESETS.get(DEFAULT_PRESET, PRESETS["1080p"])
        width  = int(os.getenv("DASHCAM_WIDTH",  str(preset[0])))
        height = int(os.getenv("DASHCAM_HEIGHT", str(preset[1])))
        fps    = float(os.getenv("DASHCAM_FPS",  str(DEFAULT_FPS)))

        camera = CameraConfig(
            label="front",
            source=source,
            width=width,
            height=height,
            fps=fps,
            auto_detect=True,
        )
        return cls(mode=mode, cameras=[camera])

    @property
    def primary(self) -> CameraConfig:
        """Return the primary (front) camera configuration."""
        return self.cameras[0]

    def summary(self) -> str:
        lines = [f"DashcamConfig(mode={self.mode!r}, cameras={len(self.cameras)})"]
        for cam in self.cameras:
            lines.append(
                f"  [{cam.label}] source={cam.source!r}  "
                f"{cam.width}×{cam.height} @ {cam.fps:.0f} fps  "
                f"auto_detect={cam.auto_detect}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _default_front_camera() -> CameraConfig:
    preset = PRESETS.get(DEFAULT_PRESET, PRESETS["1080p"])
    return CameraConfig(
        label="front",
        source=os.getenv("DASHCAM_SOURCE", "0"),
        width=int(os.getenv("DASHCAM_WIDTH",  str(preset[0]))),
        height=int(os.getenv("DASHCAM_HEIGHT", str(preset[1]))),
        fps=float(os.getenv("DASHCAM_FPS", str(DEFAULT_FPS))),
        auto_detect=True,
    )


def detect_source_properties(source: str) -> Optional[dict]:
    """
    Auto-detect width, height, and FPS from a video file or device.

    Returns a dict {"width": int, "height": int, "fps": float} on success,
    or None if OpenCV is unavailable or the source cannot be opened.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return None

    try:
        idx = int(source)
        cap = cv2.VideoCapture(idx)
    except ValueError:
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        return None

    props = {
        "width":  int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps":    cap.get(cv2.CAP_PROP_FPS) or DEFAULT_FPS,
    }
    cap.release()
    return props
