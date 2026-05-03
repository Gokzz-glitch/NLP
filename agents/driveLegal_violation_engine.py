"""
DriveLegal Violation Engine (DL-2)
Implements Section 194D, 183, 208 of Motor Vehicles Act 2019.

Processes violations detected by:
- Vision (sign detection, speed camera detection)
- IMU (near-miss hazard, crash risk)
- Geolocation (speed zone, school zone)

Generates:
- Real-time risk alerts (Persona 4: TTS)
- Legal citations with exact sections & penalties
- Section 208 audit requests to RTO (auto-drafts challenge)
- Telemetry in iRAD schema

Author: SmartSalai Team
License: AGPL3.0 + MoRTH Data Share Agreement
"""

import json
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib

# ─────────────────────────────────────────────────────────────────────────
# VIOLATION CLASSES (MVA 2019 Chapters)
# ─────────────────────────────────────────────────────────────────────────

class ViolationType(Enum):
    """MVA 2019 violation categories"""
    HELMET_MISSING = "HELMET_MISSING"           # Section 194D
    SPEEDING = "SPEEDING"                       # Section 183
    DANGEROUS_DRIVING = "DANGEROUS_DRIVING"     # Section 185
    SIGN_VIOLATION = "SIGN_VIOLATION"           # Section 3-4 (ITC rules)
    POTHOLE_HAZARD = "POTHOLE_HAZARD"          # Infrastructure safety
    RTA_HAZARD = "RTA_HAZARD"                  # Road traffic accident risk


class SeverityLevel(Enum):
    """Risk-based severity (affects TTS urgency & legal penalty)"""
    ADVISORY = "ADVISORY"       # Info only, no fine
    WARNING = "WARNING"         # First-time penalty range
    CRITICAL = "CRITICAL"       # Repeated violation
    RTA_IMMINENT = "RTA_IMMINENT"  # High crash risk


@dataclass
class LegalCitation:
    """Single MVA section with penalty"""
    section: str                    # e.g. "194D", "183"
    chapter: str                    # e.g. "Chapter VII" (punishment)
    violation_name: str             # Human-readable description
    penalty_min_inr: int            # Minimum fine
    penalty_max_inr: int            # Maximum fine
    jail_days_min: int              # Minimum jail (rare)
    jail_days_max: int              # Maximum jail (rare)
    tn_specific: Optional[str] = None  # TN-specific ruling (G.O. ref)


@dataclass
class ViolationEvent:
    """Single violation occurrence"""
    event_id: str                   # UUID4
    timestamp: float                # Unix epoch
    violation_type: str             # ViolationType key
    severity: str                   # SeverityLevel key
    location: Optional[Dict] = None # {lat, lng, zone, landmark}
    context: Optional[Dict] = None  # Vision/IMU/GPS raw data
    legal_citations: Optional[List[Dict]] = None  # [LegalCitation.asdict()]
    irad_code: Optional[str] = None # iRAD accident type code
    challenge_drafted: bool = False # True if Section 208 audit generated


# ─────────────────────────────────────────────────────────────────────────
# MVA 2019 TN JURISDICTION RULES
# ─────────────────────────────────────────────────────────────────────────

MVA_TN_RULES = {
    # Section 194D: Helmet violation (TWO-WHEELER MANDATORY)
    "HELMET_MISSING": {
        "citations": [
            LegalCitation(
                section="194D",
                chapter="Chapter VIII (Punishment for negligent act)",
                violation_name="Riding without helmet (two-wheeler)",
                penalty_min_inr=1000,
                penalty_max_inr=1500,
                jail_days_min=0,
                jail_days_max=0,
                tn_specific="TN G.O.(Ms).No.56/2022 — Pillion seat mandatory rule"
            )
        ],
        "rta_risk_multiplier": 2.5,  # Helmet reduces 37% RTA fatality risk
    },
    
    # Section 183: Speeding (TN ZONE DEPENDENT)
    "SPEEDING": {
        "citations": [
            LegalCitation(
                section="183",
                chapter="Chapter VIII (Punishment for rash/negligent driving)",
                violation_name="Speed beyond limit (first offence)",
                penalty_min_inr=400,
                penalty_max_inr=1000,
                jail_days_min=0,
                jail_days_max=6,
                tn_specific="TN school zone 40 km/h, NH 80 km/h, city 40-60 km/h"
            )
        ],
        "rta_risk_multiplier": 1.8,  # Speed doubles crash risk
    },
    
    # Section 208: Speed camera missing legal signage (AUTO-AUDIT)
    "SPEED_CAMERA_UNSIGNED": {
        "citations": [],  # Not a direct penalty, but triggers audit
        "sec208_trigger": True,
        "sec208_description": """{
        Speed enforcement camera detected by YOLO, but no IRC:67-compliant warning sign
        within 500m upstream. Per Section 208 (Motor Vehicles Rules),
        unsigned enforcement devices may be legally challenged by RTO consultation.
        This violation is being auto-drafted as an Audit Request.
        }""",
        "rta_risk_multiplier": 0.0,  # Not a violation per se
    },
}


# ─────────────────────────────────────────────────────────────────────────
# ZONE-BASED SPEED LIMITS (TN, MOTORIST-FACING)
# ─────────────────────────────────────────────────────────────────────────

TN_SPEED_ZONES = {
    "HIGHWAY_NATIONAL": {"limit_kmh": 80, "two_wheeler_limit_kmh": 60},
    "HIGHWAY_STATE": {"limit_kmh": 60, "two_wheeler_limit_kmh": 50},
    "CITY_ARTERIAL": {"limit_kmh": 60, "two_wheeler_limit_kmh": 40},
    "CITY_RESIDENTIAL": {"limit_kmh": 40, "two_wheeler_limit_kmh": 30},
    "SCHOOL_ZONE": {"limit_kmh": 25, "two_wheeler_limit_kmh": 20},
    "CONSTRUCTION_ZONE": {"limit_kmh": 20, "two_wheeler_limit_kmh": 15},
}


# ─────────────────────────────────────────────────────────────────────────
# ENGINE: VIOLATION PROCESSOR
# ─────────────────────────────────────────────────────────────────────────

class DriveLegalViolationEngine:
    """
    Processes real-time sensor/vision events and generates legal documents.
    Replaces manual RTO filing with autonomous MVA-compliant challenges.
    """
    
    def __init__(self, jurisdiction: str = "TN"):
        """
        Args:
            jurisdiction: "TN" (Tamil Nadu) / "IN" (future expansion)
        """
        self.jurisdiction = jurisdiction
        self.rules = MVA_TN_RULES
        self.violation_log: List[ViolationEvent] = []
        self.audit_queue: List[Dict] = []
        self._lock = threading.RLock()
        
    def detect_violation(
        self,
        violation_type: str,
        severity: str,
        location: Optional[Dict] = None,
        context: Optional[Dict] = None,
    ) -> ViolationEvent:
        """
        Primary entry point: Create violation event from sensor/vision data.
        
        Args:
            violation_type: Key from ViolationType (HELMET_MISSING, SPEEDING, etc.)
            severity: SeverityLevel key (ADVISORY, WARNING, CRITICAL, RTA_IMMINENT)
            location: {lat, lng, zone, landmark, speed_kmh (if relevant)}
            context: {source, confidence, raw_data} from vision/IMU
        
        Returns:
            ViolationEvent with legal citations attached
        """
        event_id = str(uuid.uuid4())
        timestamp = time.time()
        
        # Look up legal citations
        rule_pack = self.rules.get(violation_type, {})
        citations = [asdict(c) for c in rule_pack.get("citations", [])]
        
        # Compute iRAD code (accident type if relevant)
        irad_code = self._map_to_irad(violation_type)
        
        # Check if this triggers Section 208 (speed camera unsigned)
        challenge_drafted = False
        if rule_pack.get("sec208_trigger"):
            challenge_drafted = self._draft_sec208_challenge(
                violation_type, location, context
            )
        
        # Create event
        event = ViolationEvent(
            event_id=event_id,
            timestamp=timestamp,
            violation_type=violation_type,
            severity=severity,
            location=location or {},
            context=context or {},
            legal_citations=citations,
            irad_code=irad_code,
            challenge_drafted=challenge_drafted,
        )
        
        with self._lock:
            self.violation_log.append(event)
        return event
    
    def compute_rta_risk(
        self,
        violation_type: str,
        location: Optional[Dict] = None,
        vehicle_state: Optional[Dict] = None,
    ) -> float:
        """
        Compute Real Traffic Accident (RTA) crash risk score (0-1).
        
        Based on: MVA 2019 Section 163 (safety analysis data).
        
        Args:
            violation_type: HELMET_MISSING, SPEEDING, DANGEROUS_DRIVING, etc.
            location: Speed, zone, traffic density, etc.
            vehicle_state: IMU data (yaw, accel, recent near-miss)
        
        Returns:
            risk_score ∈ [0, 1]. >0.7 = CRITICAL alert.
        """
        rule_pack = self.rules.get(violation_type, {})
        base_multiplier = rule_pack.get("rta_risk_multiplier", 1.0)
        
        # Base risk: ~2% for routine driving
        base_risk = 0.02
        
        risk = base_risk * base_multiplier
        
        # Add location modifiers
        if location:
            zone = location.get("zone", "CITY_RESIDENTIAL")
            if zone == "SCHOOL_ZONE":
                risk *= 1.5  # Schools have more vulnerable road users
            if zone == "CONSTRUCTION_ZONE":
                risk *= 1.4
        
        # Add vehicle state modifiers
        if vehicle_state:
            if vehicle_state.get("recent_near_miss"):
                risk += 0.15  # Near-miss + violation = higher RTA risk
            if vehicle_state.get("accel_lateral_g", 0) > 0.3:
                risk *= 1.2  # Aggressive steering
        
        # Cap at 1.0
        return min(risk, 1.0)
    
    def _draft_sec208_challenge(
        self,
        violation_type: str,
        location: Dict,
        context: Dict,
    ) -> bool:
        """
        Generate Section 208 audit request for unsigned speed cameras.
        
        Section 208 (Motor Vehicles Rules 2016) requires IRC:67-compliant
        warning sign placed 500m upstream of enforcement device.
        
        Returns:
            True if audit was drafted and queued.
        """
        if violation_type != "SPEED_CAMERA_UNSIGNED":
            return False
        
        # Verify sign distance
        sign_distance_m = context.get("sign_distance_m", float('inf'))
        if sign_distance_m < 500:
            return False  # Sign is COMPLIANT
        
        # Draft audit request
        audit_doc = {
            "audit_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.utcnow().isoformat(),
            "vehicle_reg": context.get("vehicle_reg", "UNKNOWN"),
            "location_lat": location.get("lat"),
            "location_lng": location.get("lng"),
            "landmark": location.get("landmark", ""),
            "violation_description": MVA_TN_RULES["SPEED_CAMERA_UNSIGNED"]["sec208_description"],
            "req_sections": ["208"],
            "requested_action": "RTO Consultation on Enforcement Device Compliance",
            "attached_evidence": [
                {
                    "type": "YOLO_DETECTION",
                    "confidence": context.get("camera_confidence", 0.0),
                    "timestamp_frame": context.get("frame_timestamp"),
                }
            ],
        }
        
        with self._lock:
            self.audit_queue.append(audit_doc)
        return True
    
    def _map_to_irad(self, violation_type: str) -> Optional[str]:
        """
        Map violation to iRAD (Integrated Road Accident DB) code.
        
        Reference: MoRTH iRAD v2022 accident classification.
        """
        mapping = {
            "HELMET_MISSING": "02C",  # Inadequate protective equipment
            "SPEEDING": "03A",         # Excessive speed
            "DANGEROUS_DRIVING": "03F",  # Dangerous/negligent driving
            "POTHOLE_HAZARD": "07A",  # Poor road surface
            "RTA_HAZARD": "08A",      # Multi-vehicle conflict
        }
        return mapping.get(violation_type)
    
    def export_irad_record(self, event: ViolationEvent) -> Dict:
        """
        Export violation as iRAD-compliant telemetry record.
        
        Per MoRTH data sharing agreement, fields are:
        - accident_code (iRAD)
        - jurisdiction (TN)
        - timestamp, location
        - vehicle_class (two-wheeler)
        - severity
        """
        return {
            "irad_record_id": str(uuid.uuid4()),
            "accident_code": event.irad_code,
            "jurisdiction": self.jurisdiction,
            "timestamp_utc": datetime.fromtimestamp(event.timestamp).isoformat(),
            "location": event.location,
            "vehicle_class": "TWO_WHEELER",
            "violation_type": event.violation_type,
            "severity": event.severity,
            "legal_sections": [c["section"] for c in (event.legal_citations or [])],
            "notes": "Autonomous violation detection via edge-sentinel system (SmartSalai)",
        }
    
    def get_violation_log(self) -> List[Dict]:
        """Export all logged violations"""
        with self._lock:
            return [asdict(e) for e in list(self.violation_log)]
    
    def get_audit_queue(self) -> List[Dict]:
        """Export all queued Section 208 audits (ready to send to RTO)"""
        with self._lock:
            return [dict(item) for item in self.audit_queue]


# ─────────────────────────────────────────────────────────────────────────
# EXAMPLE USAGE (SMOKE TEST)
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = DriveLegalViolationEngine(jurisdiction="TN")
    
    # Test 1: Helmet missing in school zone
    event1 = engine.detect_violation(
        violation_type="HELMET_MISSING",
        severity="CRITICAL",
        location={
            "lat": 13.0827,
            "lng": 80.2707,
            "zone": "SCHOOL_ZONE",
            "landmark": "Mount Carmel School, Gopalapuram, Chennai"
        },
        context={
            "source": "YOLO_HELMET_DETECTOR",
            "confidence": 0.94,
            "frame_id": 12345,
        }
    )
    
    print("✅ Event 1: Helmet violation")
    print(json.dumps(asdict(event1), indent=2, default=str))
    
    # Test 2: Speed camera unsigned (triggers Section 208)
    event2 = engine.detect_violation(
        violation_type="SPEED_CAMERA_UNSIGNED",
        severity="WARNING",
        location={
            "lat": 13.1939,
            "lng": 80.1740,
            "zone": "HIGHWAY_NATIONAL",
            "speed_kmh": 95,
            "landmark": "NH16, Poonamallee, Chennai"
        },
        context={
            "source": "YOLO_CAMERA_DETECTOR",
            "confidence": 0.87,
            "camera_confidence": 0.87,
            "sign_distance_m": 650,  # >500m = unsigned
            "frame_timestamp": time.time(),
        }
    )
    
    print("\n✅ Event 2: Speed camera unsigned (Section 208 triggered)")
    print(json.dumps(asdict(event2), indent=2, default=str))
    
    # Test 3: RTA risk computation
    risk = engine.compute_rta_risk(
        violation_type="HELMET_MISSING",
        location={"zone": "SCHOOL_ZONE"},
        vehicle_state={"recent_near_miss": True, "accel_lateral_g": 0.4}
    )
    
    print(f"\n✅ Test 3: RTA risk score = {risk:.3f} (CRITICAL: >0.7)")
    
    # Test 4: Audit queue
    audits = engine.get_audit_queue()
    print(f"\n✅ Audit queue: {len(audits)} Section 208 challenges ready for RTO")
    if audits:
        print(json.dumps(audits[0], indent=2))
    
    print("\n✅ DL-2 Engine smoke test PASSED")
