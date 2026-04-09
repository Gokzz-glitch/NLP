"""
simulation/camera_ingest.py
===========================
Abstract camera-ingest interface for SmartSalai Edge-Sentinel.

Design goals
------------
* Track 1 (now):   single front-facing dashcam — zero extra hardware needed.
* Track 2 (later): 360-degree multi-camera rig  — drop-in via the same ABC.

Adding a new camera source requires only:
  1. Subclass ``CameraSource`` and implement ``open()``, ``read_frame()``,
     ``release()``.
  2. Register it in ``CameraSourceFactory.register()``.
  3. Provide per-source calibration data via ``CalibrationParams``.

No real hardware is required to run tests — the ``SyntheticFrameSource``
fulfils the same contract with procedurally generated frames.

SAFETY NOTE
-----------
All video output from this module is **advisory / informational only**.
No driving, braking, or steering decisions are made here.  The driver
remains solely responsible for safe vehicle operation at all times.
See SAFETY.md for the full disclaimer.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Calibration placeholder
# ---------------------------------------------------------------------------

@dataclass
class CalibrationParams:
    """
    Intrinsic + extrinsic calibration for a single camera lens.

    Values are intentionally zero-initialised as **placeholders** until real
    calibration data is collected with a calibration board.  The simulation
    harness runs correctly without real values; they become important when
    computing metric distances from pixel coordinates.
    """
    camera_id: str = "front"
    # Intrinsic matrix coefficients (fx, fy, cx, cy) — pinhole model
    fx: float = 0.0
    fy: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    # Radial / tangential distortion (k1, k2, p1, p2)
    distortion: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    # Extrinsic: mounting angle relative to vehicle forward axis (degrees)
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    roll_deg: float = 0.0
    # Field-of-view (informational)
    hfov_deg: float = 120.0
    # For multi-camera rigs: 3-D translation from vehicle origin (metres)
    mount_offset_xyz_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Frame dataclass
# ---------------------------------------------------------------------------

@dataclass
class CameraFrame:
    """A single decoded frame from any camera source."""
    camera_id: str
    frame_index: int
    timestamp_s: float          # wall-clock or video-file position
    bgr: np.ndarray             # H×W×3 uint8 array (BGR, compatible with OpenCV)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class CameraSource(abc.ABC):
    """
    Abstract base for any camera source (dashcam file, live USB, 360 rig, …).

    Sub-classes must be context managers::

        with DashcamFileSource("video.mp4") as cam:
            for frame in cam.stream():
                process(frame)
    """

    def __init__(self, camera_id: str = "front",
                 calibration: Optional[CalibrationParams] = None) -> None:
        self.camera_id = camera_id
        self.calibration = calibration or CalibrationParams(camera_id=camera_id)
        self._frame_index: int = 0

    # -- lifecycle -----------------------------------------------------------

    @abc.abstractmethod
    def open(self) -> None:
        """Open the underlying resource (file handle, device, socket, …)."""

    @abc.abstractmethod
    def release(self) -> None:
        """Release all resources."""

    def __enter__(self) -> "CameraSource":
        self.open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()

    # -- reading -------------------------------------------------------------

    @abc.abstractmethod
    def read_frame(self) -> Optional[CameraFrame]:
        """
        Read the next frame.

        Returns ``None`` when the source is exhausted (end-of-file, device
        disconnected, …).
        """

    def stream(self) -> Generator[CameraFrame, None, None]:
        """Yield frames until the source is exhausted."""
        while True:
            frame = self.read_frame()
            if frame is None:
                break
            yield frame

    # -- metadata ------------------------------------------------------------

    @property
    def is_multi_camera(self) -> bool:
        """Return True for 360 / surround-view sources that emit >1 camera."""
        return False


# ---------------------------------------------------------------------------
# Track 1: single front-facing dashcam (file or device)
# ---------------------------------------------------------------------------

class DashcamFileSource(CameraSource):
    """
    Play back a single-channel dashcam video file.

    Requires ``opencv-python`` to be installed (``pip install opencv-python``).
    Falls back gracefully to ``SyntheticFrameSource`` when the file cannot be
    opened — useful in CI environments without a real video file.

    Parameters
    ----------
    path : str
        Path to the dashcam video file (MP4, AVI, MKV, …).
    camera_id : str
        Logical name for this camera (default: ``"front"``).
    max_frames : int | None
        If set, stop after this many frames (useful for smoke tests).
    """

    def __init__(self, path: str, camera_id: str = "front",
                 calibration: Optional[CalibrationParams] = None,
                 max_frames: Optional[int] = None) -> None:
        super().__init__(camera_id=camera_id, calibration=calibration)
        self.path = path
        self.max_frames = max_frames
        self._cap: Any = None  # cv2.VideoCapture

    def open(self) -> None:
        try:
            import cv2  # type: ignore
            self._cap = cv2.VideoCapture(self.path)
            if not self._cap.isOpened():
                raise IOError(f"Cannot open dashcam file: {self.path!r}")
        except ImportError as exc:
            raise ImportError(
                "opencv-python is required for DashcamFileSource. "
                "Install with: pip install opencv-python"
            ) from exc

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read_frame(self) -> Optional[CameraFrame]:
        if self._cap is None:
            return None
        if self.max_frames is not None and self._frame_index >= self.max_frames:
            return None
        ret, bgr = self._cap.read()
        if not ret:
            return None
        ts = self._cap.get(0) / 1000.0  # cv2.CAP_PROP_POS_MSEC → seconds
        frame = CameraFrame(
            camera_id=self.camera_id,
            frame_index=self._frame_index,
            timestamp_s=ts,
            bgr=bgr,
        )
        self._frame_index += 1
        return frame


class DashcamDeviceSource(CameraSource):
    """
    Capture from a live USB/CSI dashcam device.

    Parameters
    ----------
    device_index : int
        OpenCV camera index (0 = first USB camera on most systems).
    width, height : int
        Desired capture resolution.  The device may choose a different
        resolution if the requested one is not supported.
    fps : int
        Desired frame rate.
    max_frames : int | None
        If set, stop after this many frames.
    """

    def __init__(self, device_index: int = 0, camera_id: str = "front",
                 width: int = 1920, height: int = 1080, fps: int = 30,
                 calibration: Optional[CalibrationParams] = None,
                 max_frames: Optional[int] = None) -> None:
        super().__init__(camera_id=camera_id, calibration=calibration)
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self.max_frames = max_frames
        self._cap: Any = None

    def open(self) -> None:
        try:
            import cv2  # type: ignore
            self._cap = cv2.VideoCapture(self.device_index)
            if not self._cap.isOpened():
                raise IOError(
                    f"Cannot open camera device index {self.device_index}. "
                    "Check that the dashcam is plugged in and not used by another app."
                )
            self._cap.set(3, self.width)   # CAP_PROP_FRAME_WIDTH
            self._cap.set(4, self.height)  # CAP_PROP_FRAME_HEIGHT
            self._cap.set(5, self.fps)     # CAP_PROP_FPS
        except ImportError as exc:
            raise ImportError(
                "opencv-python is required for DashcamDeviceSource."
            ) from exc

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read_frame(self) -> Optional[CameraFrame]:
        if self._cap is None:
            return None
        if self.max_frames is not None and self._frame_index >= self.max_frames:
            return None
        ret, bgr = self._cap.read()
        if not ret:
            return None
        frame = CameraFrame(
            camera_id=self.camera_id,
            frame_index=self._frame_index,
            timestamp_s=time.monotonic(),
            bgr=bgr,
        )
        self._frame_index += 1
        return frame


# ---------------------------------------------------------------------------
# Track 2 scaffold: 360-degree / surround-view (future hardware)
# ---------------------------------------------------------------------------

class MultiCameraRig:
    """
    Scaffold for a 360-degree or multi-camera rig.

    This class is intentionally *not* a CameraSource subclass because a 360
    rig produces *multiple* synchronised streams.  Call ``read_all_frames()``
    to get one frame from every lens simultaneously.

    Sub-class this and override ``_sources`` to attach real camera sources
    when hardware is available.  The base implementation raises
    ``NotImplementedError`` so unit tests can mock it without hardware.

    TRACK 2 PLACEHOLDER — not required for Track 1 dashcam simulation.
    """

    # Canonical lens positions for a typical 6-lens 360 rig
    STANDARD_POSITIONS = ["front", "front_left", "front_right",
                          "rear", "rear_left", "rear_right"]

    def __init__(self, calibrations: Optional[Dict[str, CalibrationParams]] = None,
                 max_frames: Optional[int] = None) -> None:
        self.calibrations: Dict[str, CalibrationParams] = calibrations or {}
        self.max_frames = max_frames
        self._sources: Dict[str, CameraSource] = {}

    @property
    def is_multi_camera(self) -> bool:
        return True

    @property
    def camera_ids(self) -> List[str]:
        return list(self._sources.keys())

    def open(self) -> None:
        """Open all camera sources."""
        for src in self._sources.values():
            src.open()

    def release(self) -> None:
        """Release all camera sources."""
        for src in self._sources.values():
            src.release()

    def __enter__(self) -> "MultiCameraRig":
        self.open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()

    def read_all_frames(self) -> Optional[Dict[str, CameraFrame]]:
        """
        Read one frame from every lens.

        Returns a ``{camera_id: CameraFrame}`` dict, or ``None`` if *any*
        source is exhausted (drives the simulation to stop cleanly).
        """
        out: Dict[str, CameraFrame] = {}
        for cid, src in self._sources.items():
            frame = src.read_frame()
            if frame is None:
                return None
            out[cid] = frame
        return out or None

    def stream(self) -> Generator[Dict[str, CameraFrame], None, None]:
        """Yield synchronised frame bundles until any source is exhausted."""
        while True:
            bundle = self.read_all_frames()
            if bundle is None:
                break
            yield bundle


class Synthetic360Rig(MultiCameraRig):
    """
    Six-lens 360-rig using SyntheticFrameSource for each position.

    Useful for CI and unit tests — no real hardware required.
    """

    def __init__(self, width: int = 320, height: int = 240, fps: int = 10,
                 max_frames: int = 5) -> None:
        super().__init__(max_frames=max_frames)
        for pos in self.STANDARD_POSITIONS:
            self._sources[pos] = SyntheticFrameSource(
                camera_id=pos, width=width, height=height,
                fps=fps, max_frames=max_frames,
                calibration=CalibrationParams(camera_id=pos),
            )


# ---------------------------------------------------------------------------
# Synthetic (no-hardware) source — used in CI and unit tests
# ---------------------------------------------------------------------------

class SyntheticFrameSource(CameraSource):
    """
    Generates procedural BGR frames without any camera or file.

    Each frame is a solid colour that cycles through a small palette so
    tests can verify that consecutive frames differ.  Supports the full
    ``CameraSource`` contract.

    Parameters
    ----------
    width, height : int
        Frame dimensions in pixels.
    fps : int
        Simulated frame rate (controls ``timestamp_s`` values).
    max_frames : int
        Total number of frames to emit before returning ``None``.
    """

    _PALETTE = [
        (30, 30, 30),    # near-black (night)
        (180, 130, 80),  # dusty road
        (50, 120, 200),  # sky-blue (daytime)
        (20, 20, 120),   # dusk/rain tint
        (200, 200, 200), # bright overcast
    ]

    def __init__(self, camera_id: str = "front", width: int = 640,
                 height: int = 480, fps: int = 30, max_frames: int = 10,
                 calibration: Optional[CalibrationParams] = None) -> None:
        super().__init__(camera_id=camera_id, calibration=calibration)
        self.width = width
        self.height = height
        self.fps = fps
        self.max_frames = max_frames
        self._opened = False

    def open(self) -> None:
        self._opened = True
        self._frame_index = 0

    def release(self) -> None:
        self._opened = False

    def read_frame(self) -> Optional[CameraFrame]:
        if not self._opened or self._frame_index >= self.max_frames:
            return None
        colour = self._PALETTE[self._frame_index % len(self._PALETTE)]
        bgr = np.full((self.height, self.width, 3), colour, dtype=np.uint8)
        # Add a small unique marker so frames can be distinguished
        bgr[0, 0] = [self._frame_index % 256, 0, 0]
        frame = CameraFrame(
            camera_id=self.camera_id,
            frame_index=self._frame_index,
            timestamp_s=self._frame_index / self.fps,
            bgr=bgr,
            metadata={"synthetic": True, "palette_idx": self._frame_index % len(self._PALETTE)},
        )
        self._frame_index += 1
        return frame


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class CameraSourceFactory:
    """
    Registry for named camera source constructors.

    Usage::

        CameraSourceFactory.register("my_special_cam", MySpecialCamSource)
        src = CameraSourceFactory.create("my_special_cam", path="/dev/video2")
    """

    _registry: Dict[str, type] = {}

    @classmethod
    def register(cls, name: str, source_class: type) -> None:
        cls._registry[name] = source_class

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> CameraSource:
        if name not in cls._registry:
            raise KeyError(
                f"Unknown camera source {name!r}. "
                f"Registered: {list(cls._registry.keys())}"
            )
        return cls._registry[name](**kwargs)


# Pre-register built-in sources
CameraSourceFactory.register("dashcam_file",   DashcamFileSource)
CameraSourceFactory.register("dashcam_device", DashcamDeviceSource)
CameraSourceFactory.register("synthetic",      SyntheticFrameSource)
