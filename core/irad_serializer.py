"""
core/irad_serializer.py  (T-015)
SmartSalai Edge-Sentinel — MoRTH iRAD Schema Serializer

Formats sensor + legal events into the official Integrated Road Accident
Database (iRAD) schema for MoRTH submission/audit.

iRAD Record Schema (simplified MoRTH 2022 mapping):
  - accident_id         : UUID
  - timestamp_utc       : ISO-8601
  - gps_lat/lon         : decimal degrees (privacy-gated via ZKP)
  - state_code          : "TN" (Tamil Nadu)
  - severity_code       : 1=Fatal, 2=Grievous, 3=Simple, 4=Near-miss
  - road_user_type      : 1=Two-wheeler, 2=Car, 3=Bus, ...
  - vehicle_involved    : list
  - cause_code          : MoRTH cause taxonomy
  - irad_category_code  : from ULS offence_registry
  - legal_sections      : list of MVA sections triggered
  - evidence_chain      : ZKP envelope dicts
  - near_miss_score     : float 0–1
  - speed_kmh           : from IMU
  - blackspot_flag      : bool
  - section_208_flag    : bool
  - zkp_sealed          : bool
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.core.irad_serializer")

IRAD_SCHEMA_VERSION = "MORTH-iRAD-2022-v1"
DEFAULT_STATE_CODE = "TN"
DEFAULT_ROAD_USER_TYPE = 1  # Two-wheeler


@dataclass
class IRADRecord:
    """Single iRAD submission record."""
    accident_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = IRAD_SCHEMA_VERSION
    timestamp_utc: str = field(default_factory=lambda: _iso_now())
    timestamp_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    state_code: str = DEFAULT_STATE_CODE
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    severity_code: int = 4          # 4 = Near-miss by default
    road_user_type: int = DEFAULT_ROAD_USER_TYPE
    vehicles_involved: List[str] = field(default_factory=list)
    cause_code: str = "UNKNOWN"
    irad_category_code: str = ""
    legal_sections: List[str] = field(default_factory=list)
    evidence_chain: List[Dict[str, Any]] = field(default_factory=list)
    near_miss_score: float = 0.0
    speed_kmh: float = 0.0
    blackspot_flag: bool = False
    section_208_flag: bool = False
    zkp_sealed: bool = False
    raw_event_type: str = ""
    annexure_a_fields: Dict[str, Any] = field(default_factory=dict)
    record_sha3: str = ""           # Computed on finalise()

    def finalise(self) -> "IRADRecord":
        """Compute SHA3-256 over canonical record JSON and store in record_sha3."""
        canonical = json.dumps(self._as_dict_without_hash(), sort_keys=True, separators=(",", ":"))
        self.record_sha3 = hashlib.sha3_256(canonical.encode()).hexdigest()
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = self._as_dict_without_hash()
        d["record_sha3"] = self.record_sha3
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    def _as_dict_without_hash(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "accident_id": self.accident_id,
            "timestamp_utc": self.timestamp_utc,
            "timestamp_epoch_ms": self.timestamp_epoch_ms,
            "state_code": self.state_code,
            "gps_lat": self.gps_lat,
            "gps_lon": self.gps_lon,
            "severity_code": self.severity_code,
            "road_user_type": self.road_user_type,
            "vehicles_involved": self.vehicles_involved,
            "cause_code": self.cause_code,
            "irad_category_code": self.irad_category_code,
            "legal_sections": self.legal_sections,
            "evidence_chain": self.evidence_chain,
            "near_miss_score": self.near_miss_score,
            "speed_kmh": self.speed_kmh,
            "blackspot_flag": self.blackspot_flag,
            "section_208_flag": self.section_208_flag,
            "zkp_sealed": self.zkp_sealed,
            "raw_event_type": self.raw_event_type,
            "annexure_a_fields": self.annexure_a_fields,
        }


def _iso_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class IRADSerializer:
    """
    Converts near-miss events + legal events into iRAD records.

    Usage:
        ser = IRADSerializer()
        record = ser.from_near_miss(near_miss_event_dict)
        ser.append_legal_evidence(record, sec208_result_dict)
        record.finalise()
    """

    def from_near_miss(self, event: Dict[str, Any]) -> IRADRecord:
        """Build an IRADRecord from a NearMissDetector event dict."""
        severity = event.get("severity", "")
        severity_map = {"CRITICAL": 2, "HIGH": 3, "MODERATE": 3, "LOW": 4}
        severity_code = severity_map.get(severity, 4)

        rec = IRADRecord(
            raw_event_type="NearMissEvent",
            severity_code=severity_code,
            gps_lat=event.get("gps_lat"),
            gps_lon=event.get("gps_lon"),
            near_miss_score=float(event.get("near_miss_score", 0.0)),
            speed_kmh=float(event.get("speed_kmh", 0.0)),
            cause_code="NEAR_MISS_KINETIC",
            irad_category_code=event.get("irad_category_code", "NM_TWOWHEELER"),
            vehicles_involved=event.get("vehicles_involved", ["TWO_WHEELER"]),
        )
        # Attach ZKP envelope if present
        if "zkp_envelope" in event:
            rec.evidence_chain.append(event["zkp_envelope"])
            rec.zkp_sealed = True
        return rec

    def append_legal_evidence(self, record: IRADRecord, legal_event: Dict[str, Any]) -> None:
        """Merge a legal challenge/RAG result into an existing IRADRecord."""
        sections = legal_event.get("legal_sections", [])
        for s in sections:
            if s not in record.legal_sections:
                record.legal_sections.append(s)
        if legal_event.get("section_208_flag"):
            record.section_208_flag = True
            record.annexure_a_fields.update(legal_event.get("annexure_a", {}))
        if legal_event.get("irad_category_code"):
            record.irad_category_code = legal_event["irad_category_code"]
        if legal_event.get("zkp_envelope"):
            record.evidence_chain.append(legal_event["zkp_envelope"])
            record.zkp_sealed = True

    def append_vision_evidence(self, record: IRADRecord, detection: Dict[str, Any]) -> None:
        """Merge a SignAuditor detection into an existing IRADRecord."""
        if detection.get("sec208_trigger"):
            record.section_208_flag = True
        for section in detection.get("legal_sections", []):
            if section not in record.legal_sections:
                record.legal_sections.append(section)
        record.evidence_chain.append({
            "source": "vision_detection",
            "label": detection.get("label", ""),
            "confidence": detection.get("confidence", 0.0),
            "bbox": detection.get("bbox"),
        })

    def append_blackspot_evidence(self, record: IRADRecord, blackspot: Dict[str, Any]) -> None:
        record.blackspot_flag = True
        record.annexure_a_fields["blackspot"] = {
            "zone_name": blackspot.get("zone_name", ""),
            "risk_index": blackspot.get("risk_index", 0.0),
        }

    def export_csv_row(self, record: IRADRecord) -> Dict[str, str]:
        """Returns a flat dict suitable for csv.DictWriter."""
        return {
            "accident_id": record.accident_id,
            "schema_version": record.schema_version,
            "timestamp_utc": record.timestamp_utc,
            "state_code": record.state_code,
            "gps_lat": str(record.gps_lat or ""),
            "gps_lon": str(record.gps_lon or ""),
            "severity_code": str(record.severity_code),
            "cause_code": record.cause_code,
            "irad_category_code": record.irad_category_code,
            "legal_sections": "|".join(record.legal_sections),
            "near_miss_score": str(round(record.near_miss_score, 4)),
            "speed_kmh": str(round(record.speed_kmh, 2)),
            "blackspot_flag": str(record.blackspot_flag),
            "section_208_flag": str(record.section_208_flag),
            "zkp_sealed": str(record.zkp_sealed),
            "evidence_count": str(len(record.evidence_chain)),
            "record_sha3": record.record_sha3,
        }


_serializer: Optional[IRADSerializer] = None


def get_serializer() -> IRADSerializer:
    global _serializer
    if _serializer is None:
        _serializer = IRADSerializer()
    return _serializer
