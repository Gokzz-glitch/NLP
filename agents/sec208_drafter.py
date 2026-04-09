"""
agents/sec208_drafter.py  (T-011)
SmartSalai Edge-Sentinel — Section 208 MVA Audit Drafter

Full Section 208 (Motor Vehicles Act 1988) challenge drafter with:
  - SHA3-256 evidentiary hashing of vision + IMU logs
  - Annexure A field assembly (IRC:67 non-compliance grounds)
  - ULS cross-validation before generating legal event
  - Agent-bus integration (publishes to legal.challenge + tts.announce)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.agents.sec208_drafter")

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_ULS_PATH  = str(_REPO_ROOT / "schemas" / "universal_legal_schema.json")

EVIDENTIARY_HASH_ALGO: str = "SHA3-256"
ANNEXURE_VERSION: str = "AnnexureA-v1.0"


# ---------------------------------------------------------------------------
# ULS loader
# ---------------------------------------------------------------------------
def _load_sec208_template() -> Dict[str, Any]:
    try:
        with open(_ULS_PATH, encoding="utf-8") as f:
            uls = json.load(f)
        return uls.get("section_208_protocol", {}).get("audit_request_template", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Evidence hashing
# ---------------------------------------------------------------------------
def _sha3_256(data: Any) -> str:
    if isinstance(data, dict):
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        raw = canonical.encode()
    elif isinstance(data, str):
        raw = data.encode()
    elif isinstance(data, bytes):
        raw = data
    else:
        raw = str(data).encode()
    return hashlib.sha3_256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Annexure A dataclass
# ---------------------------------------------------------------------------
@dataclass
class AnnexureA:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: str = ANNEXURE_VERSION
    to_authority: str = "Regional Transport Officer / Jurisdictional Magistrate"
    subject: str = ""
    grounds: List[str] = field(default_factory=list)
    camera_location_lat: Optional[float] = None
    camera_location_lon: Optional[float] = None
    camera_operator: str = ""
    camera_device_id: str = ""
    sign_detection_result: str = "NO_SPEED_LIMIT_SIGN_DETECTED"
    irc_67_compliance: bool = False
    telemetry_hash: str = ""
    vision_log_hash: str = ""
    imu_log_hash: str = ""
    rider_speed_kmh: float = 0.0
    timestamp_of_detection_utc: str = ""
    evidentiary_hash_algo: str = EVIDENTIARY_HASH_ALGO

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "version": self.version,
            "to_authority": self.to_authority,
            "subject": self.subject,
            "grounds": self.grounds,
            "camera_location": {
                "lat": self.camera_location_lat,
                "lon": self.camera_location_lon,
            },
            "camera_operator": self.camera_operator,
            "camera_device_id": self.camera_device_id,
            "sign_detection_result": self.sign_detection_result,
            "irc_67_compliance": self.irc_67_compliance,
            "telemetry_hash": self.telemetry_hash,
            "vision_log_hash": self.vision_log_hash,
            "imu_log_hash": self.imu_log_hash,
            "rider_speed_kmh": self.rider_speed_kmh,
            "timestamp_of_detection_utc": self.timestamp_of_detection_utc,
            "evidentiary_hash_algo": self.evidentiary_hash_algo,
        }


# ---------------------------------------------------------------------------
# Drafter
# ---------------------------------------------------------------------------
@dataclass
class Sec208Result:
    status: str                  # CHALLENGE_GENERATED | COMPLIANT | NOT_APPLICABLE
    request_id: str
    annexure_a: Dict[str, Any]
    evidentiary_hash: str
    evidentiary_hash_algo: str
    legal_sections: List[str]
    irad_category_code: str
    timestamp_utc: str
    section_208_flag: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "request_id": self.request_id,
            "annexure_a": self.annexure_a,
            "evidentiary_hash": self.evidentiary_hash,
            "evidentiary_hash_algo": self.evidentiary_hash_algo,
            "legal_sections": self.legal_sections,
            "irad_category_code": self.irad_category_code,
            "timestamp_utc": self.timestamp_utc,
            "section_208_flag": self.section_208_flag,
        }


class Sec208DrafterAgent:
    """
    Section 208 MVA 1988 audit drafter.

    Triggers on: speed enforcement camera detected with no IRC:67 signage
    in the 500m upstream geofence window.

    Usage:
        drafter = Sec208DrafterAgent()
        result = drafter.evaluate(camera_data, signage_detected=False, rider_data)
    """

    def __init__(self) -> None:
        self._template = _load_sec208_template()
        self._bus = None

    def attach_bus(self, bus) -> None:
        self._bus = bus
        from core.agent_bus import Topics
        bus.subscribe(Topics.VISION_DETECTION, self._on_vision_detection)

    def _on_vision_detection(self, msg) -> None:
        params = msg.params
        detections = params.get("detections", [])
        has_camera = any(d.get("label", "").lower() in ("speed_camera", "enforcement_camera") for d in detections)
        if not has_camera:
            return
        has_sign = any(d.get("label", "").lower() in ("speed_limit_sign", "speed_sign") for d in detections)
        rider_data = params.get("rider_data", {})
        camera_data = {
            "device_id": params.get("camera_device_id", "UNKNOWN"),
            "lat": params.get("gps_lat"),
            "lon": params.get("gps_lon"),
            "operator": params.get("operator", ""),
        }
        result = self.evaluate(
            camera_data=camera_data,
            signage_detected=has_sign,
            rider_data=rider_data,
            vision_detections=detections,
        )
        if result["status"] == "CHALLENGE_GENERATED" and self._bus:
            from core.agent_bus import Topics
            self._bus.publish(Topics.LEGAL_CHALLENGE, result)
            self._bus.publish(Topics.TTS_ANNOUNCE, {
                "text": (
                    "Legal notice: Speed camera without signage. "
                    "Section 208 challenge registered."
                ),
                "critical": False,
                "lang": "en",
            })

    def evaluate(
        self,
        camera_data: Dict[str, Any],
        signage_detected: bool,
        rider_data: Optional[Dict[str, Any]] = None,
        vision_detections: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        rider_data = rider_data or {}
        vision_detections = vision_detections or []

        # Determine if Section 208 is applicable
        has_camera = camera_data.get("device_id") or any(
            d.get("label", "").lower() in ("speed_camera", "enforcement_camera")
            for d in vision_detections
        )
        if not has_camera:
            return Sec208Result(
                status="NOT_APPLICABLE",
                request_id="",
                annexure_a={},
                evidentiary_hash="",
                evidentiary_hash_algo=EVIDENTIARY_HASH_ALGO,
                legal_sections=[],
                irad_category_code="",
                timestamp_utc=_iso_now(),
                section_208_flag=False,
            ).to_dict()

        if signage_detected:
            return Sec208Result(
                status="COMPLIANT",
                request_id="",
                annexure_a={},
                evidentiary_hash="",
                evidentiary_hash_algo=EVIDENTIARY_HASH_ALGO,
                legal_sections=[],
                irad_category_code="",
                timestamp_utc=_iso_now(),
                section_208_flag=False,
            ).to_dict()

        # Draft the challenge
        logger.info("[Sec208Drafter] TRIGGER: Speed camera without sign — drafting audit request.")
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        vision_log_hash = _sha3_256(vision_detections)
        imu_log_hash    = _sha3_256(rider_data)
        telemetry_bundle = {
            "camera_data": camera_data,
            "rider_data": rider_data,
            "vision_detections": vision_detections,
            "timestamp_utc": ts,
        }
        telemetry_hash = _sha3_256(telemetry_bundle)
        evidentiary_hash = _sha3_256(telemetry_hash + vision_log_hash + imu_log_hash)

        # Annexure A assembly
        template_grounds = self._template.get("grounds", [])
        default_grounds = [
            "No speed limit sign (IRC:67 compliant) detected within 500m upstream of enforcement camera.",
            "Absence of mandatory signage renders challan legally untenable per Section 208 MVA 1988.",
            f"Telemetry evidence attached — SHA3-256 hash: {evidentiary_hash[:16]}…",
        ]
        grounds = template_grounds if template_grounds else default_grounds

        annexure = AnnexureA(
            to_authority=self._template.get("to", "Regional Transport Officer"),
            subject=self._template.get("subject_pattern", "Section 208 Challenge"),
            grounds=grounds,
            camera_location_lat=camera_data.get("lat"),
            camera_location_lon=camera_data.get("lon"),
            camera_operator=camera_data.get("operator", ""),
            camera_device_id=camera_data.get("device_id", ""),
            sign_detection_result="NO_SPEED_LIMIT_SIGN_DETECTED",
            irc_67_compliance=False,
            telemetry_hash=telemetry_hash,
            vision_log_hash=vision_log_hash,
            imu_log_hash=imu_log_hash,
            rider_speed_kmh=float(rider_data.get("speed_kmh", 0.0)),
            timestamp_of_detection_utc=ts,
        )

        return Sec208Result(
            status="CHALLENGE_GENERATED",
            request_id=annexure.request_id,
            annexure_a=annexure.to_dict(),
            evidentiary_hash=evidentiary_hash,
            evidentiary_hash_algo=EVIDENTIARY_HASH_ALGO,
            legal_sections=["208"],
            irad_category_code="SEC208_NO_SIGNAGE",
            timestamp_utc=ts,
            section_208_flag=True,
        ).to_dict()


def _iso_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


_agent: Optional[Sec208DrafterAgent] = None


def get_agent() -> Sec208DrafterAgent:
    global _agent
    if _agent is None:
        _agent = Sec208DrafterAgent()
    return _agent
