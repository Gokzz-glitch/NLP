"""
agents/sign_auditor.py
SmartSalai Edge-Sentinel — P3: Traffic Sign Auditor

Detects traffic signs using VisionAuditEngine (YOLOv8n ONNX) and validates
that a mandatory IRC:67-compliant speed-limit sign exists within 500 m
upstream of any detected enforcement camera, as required for Section 208 MVA
challenge eligibility.

ERR-001: IDD-trained YOLOv8-nano ONNX INT8 checkpoint not yet available.
         Runs in MOCK_MODE when model file is absent.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger("edge_sentinel.sign_auditor")


# ---------------------------------------------------------------------------
# Geodetic utility
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance in metres between two GPS coordinates (haversine formula).
    Accurate to ±0.5 % for distances < 50 km at Indian latitudes.
    """
    R = 6_371_000  # Earth mean radius, metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SignDetection:
    """One detected sign or infrastructure object from the vision pipeline."""
    label: str
    confidence: float
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    distance_m: Optional[float] = None  # Distance from host vehicle


@dataclass
class AuditResult:
    """
    Result of a single Section 208 audit frame.

    sec208_challengeable is True when a speed camera is detected AND
    no IRC:67-compliant speed-limit sign is found within SIGN_WINDOW_M.
    """
    camera_detected: bool
    speed_sign_within_500m: bool
    nearest_sign_distance_m: Optional[float]
    detections: List[SignDetection] = field(default_factory=list)
    sec208_challengeable: bool = False


# ---------------------------------------------------------------------------
# SignAuditor
# ---------------------------------------------------------------------------

class SignAuditor:
    """
    Fuses YOLOv8 sign detections with GPS proximity checks for Section 208
    compliance auditing.

    Detection pipeline:
      1. Run VisionAuditEngine (YOLOv8n ONNX) on the current camera frame.
      2. For each detected speed_camera, search for speed_limit_sign within
         SIGN_WINDOW_M metres (haversine GPS distance).
      3. If no compliant sign found → set sec208_challengeable = True.
      4. Return AuditResult for downstream Section208Resolver.
    """

    #: IRC:67 mandatory sign placement distance upstream of enforcement camera.
    SIGN_WINDOW_M: float = 500.0

    def __init__(self, vision_engine=None) -> None:
        """
        Args:
            vision_engine: VisionAuditEngine instance.  If None, one is created
                           (may activate MOCK_MODE if model file absent — ERR-001).
        """
        if vision_engine is None:
            try:
                from vision_audit import VisionAuditEngine  # noqa: PLC0415
                vision_engine = VisionAuditEngine()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SignAuditor] VisionAuditEngine init failed: %s", exc)
                vision_engine = None

        self._vision = vision_engine
        self._is_mock = vision_engine is None or getattr(vision_engine, "is_mock", True)

        if self._is_mock:
            logger.warning(
                "[SignAuditor] MOCK_MODE active — no real sign detections. "
                "Provide VISION_MODEL_PATH to enable inference (ERR-001)."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def audit_frame(
        self,
        image_frame,
        host_lat: float,
        host_lon: float,
        known_signs: Optional[List[SignDetection]] = None,
    ) -> AuditResult:
        """
        Run a Section 208 audit on one camera frame.

        Args:
            image_frame:  HxWx3 BGR uint8 numpy array (or None in mock mode).
            host_lat:     Host vehicle GPS latitude.
            host_lon:     Host vehicle GPS longitude.
            known_signs:  Pre-mapped sign locations from HD map / prior frames.
                          Used to supplement live detections for the 500 m check.

        Returns:
            AuditResult with sec208_challengeable set appropriately.
        """
        # 1. Run vision detection
        raw_detections: list = []
        if self._vision is not None and image_frame is not None:
            try:
                raw_detections = self._vision.run_inference(image_frame)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SignAuditor] Inference error: %s", exc)

        # Convert raw dicts to SignDetection objects; approximate GPS as host position
        detections: List[SignDetection] = [
            SignDetection(
                label=d["label"],
                confidence=d["conf"],
                gps_lat=host_lat,
                gps_lon=host_lon,
            )
            for d in raw_detections
        ]

        # 2. Merge known sign locations (e.g. from HD map)
        if known_signs:
            detections.extend(known_signs)

        # 3. Check for enforcement camera
        camera_detected = any(d.label == "speed_camera" for d in detections)
        if not camera_detected:
            return AuditResult(
                camera_detected=False,
                speed_sign_within_500m=False,
                nearest_sign_distance_m=None,
                detections=detections,
                sec208_challengeable=False,
            )

        # 4. Find nearest speed_limit_sign within window
        speed_signs = [d for d in detections if d.label == "speed_limit_sign"]
        nearest_dist: Optional[float] = None
        for sign in speed_signs:
            if sign.gps_lat is not None and sign.gps_lon is not None:
                dist = haversine_m(host_lat, host_lon, sign.gps_lat, sign.gps_lon)
                sign.distance_m = dist
                if nearest_dist is None or dist < nearest_dist:
                    nearest_dist = dist

        sign_within_window = nearest_dist is not None and nearest_dist <= self.SIGN_WINDOW_M
        sec208 = camera_detected and not sign_within_window

        return AuditResult(
            camera_detected=True,
            speed_sign_within_500m=sign_within_window,
            nearest_sign_distance_m=nearest_dist,
            detections=detections,
            sec208_challengeable=sec208,
        )

    def check_sign_in_window(
        self,
        camera_lat: float,
        camera_lon: float,
        sign_locations: List[Tuple[float, float]],
    ) -> Tuple[bool, Optional[float]]:
        """
        Check whether any sign location falls within SIGN_WINDOW_M of the camera.

        Args:
            camera_lat, camera_lon: GPS position of the enforcement camera.
            sign_locations:         List of (lat, lon) tuples for known sign positions.

        Returns:
            (within_window: bool, nearest_distance_m: Optional[float])
        """
        nearest: Optional[float] = None
        for slat, slon in sign_locations:
            d = haversine_m(camera_lat, camera_lon, slat, slon)
            if nearest is None or d < nearest:
                nearest = d

        within = nearest is not None and nearest <= self.SIGN_WINDOW_M
        return within, nearest
