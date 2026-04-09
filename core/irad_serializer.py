"""
core/irad_serializer.py
SmartSalai Edge-Sentinel — P3: iRAD Telemetry Serialiser

Serialises a NearMissEvent to the MoRTH Integrated Road Accident Database
(iRAD) V-NMS-01 JSON schema for regulatory submission and tamper-evident
audit trail.

Schema reference: MoRTH IRAD Technical Manual, 2022 Circular.

Integrity guarantee:
  SHA3-256 hash over the core payload fields is computed and included as
  data_integrity_sha3_256.  A regulator can reproduce the hash from the
  disclosed payload fields to detect any post-submission tampering.

Timestamp policy:
  submission_ts_ist is the current wall-clock time in IST (UTC+5:30).
  event timestamp_epoch_ms is the original detection time (from IMU loop).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from agents.imu_near_miss_detector import NearMissEvent

logger = logging.getLogger("edge_sentinel.core.irad_serializer")

# IST is UTC+5:30 — no pytz required
_IST_OFFSET = datetime.timedelta(hours=5, minutes=30)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _ist_now() -> str:
    """Returns current time as IST ISO-8601 string (e.g. 2026-04-09T07:15:30+05:30)."""
    utc = datetime.datetime.utcnow()
    ist = utc + _IST_OFFSET
    return ist.strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _sha3_256_hex(data: str) -> str:
    """SHA3-256 hex digest of a UTF-8 string."""
    return hashlib.sha3_256(data.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def serialize_near_miss(
    event: "NearMissEvent",
    device_id: str = "UNKNOWN",
    road_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Serialise a NearMissEvent to iRAD V-NMS-01 JSON schema.

    Required iRAD fields per MoRTH 2022 circular:
      schema_version, submission_ts_ist, device_id,
      event_id, irad_category_code, severity,
      timestamp_epoch_ms, gps_lat, gps_lon, road_type,
      lateral_g_peak, longitudinal_decel_ms2, yaw_rate_peak_degs,
      rms_jerk_ms3, tcn_anomaly_score,
      data_integrity_sha3_256.

    Args:
        event:     NearMissEvent from imu_near_miss_detector.py.
        device_id: AIS-140 VLTD device identifier (ERR-003 pending).
        road_type: Road classification override.  Falls back to event.road_type.

    Returns:
        Dict conforming to iRAD V-NMS-01 schema.
    """
    # Core payload — these fields are covered by the integrity hash
    core_payload: Dict[str, Any] = {
        "event_id":              event.event_id,
        "irad_category_code":    event.irad_category_code,
        "severity":              event.severity.value,
        "timestamp_epoch_ms":    event.timestamp_epoch_ms,
        "gps_lat":               event.gps_lat,
        "gps_lon":               event.gps_lon,
        "lateral_g_peak":        round(event.lateral_g_peak, 4),
        "longitudinal_decel_ms2": round(event.longitudinal_decel_ms2, 4),
        "yaw_rate_peak_degs":    round(event.yaw_rate_peak_degs, 4),
        "rms_jerk_ms3":          round(event.rms_jerk_ms3, 4),
        "tcn_anomaly_score":     round(event.tcn_anomaly_score, 4),
    }

    # SHA3-256 integrity hash — computed over the deterministically serialised core
    payload_str = json.dumps(core_payload, sort_keys=True)
    integrity_hash = _sha3_256_hex(payload_str)

    return {
        # iRAD mandatory header
        "schema_version":          "V-NMS-01",
        "submission_ts_ist":       _ist_now(),
        "device_id":               device_id,
        "data_integrity_sha3_256": integrity_hash,
        # Core event payload
        **core_payload,
        # Extended fields
        "road_type":        road_type or event.road_type,
        "vehicle_speed_kmh": event.vehicle_speed_kmh,
        "triggered_sec208": event.triggered_sec208,
        "gps_commitment":   getattr(event, "_gps_commitment", None),
    }


def serialize_to_json(event: "NearMissEvent", **kwargs: Any) -> str:
    """
    Serialise a NearMissEvent to a JSON string (iRAD V-NMS-01).

    Convenience wrapper around serialize_near_miss().
    """
    return json.dumps(serialize_near_miss(event, **kwargs), ensure_ascii=False, indent=2)
