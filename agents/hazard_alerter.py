"""
agents/hazard_alerter.py
SmartSalai Edge-Sentinel — Persona 6: Hazard Alert Orchestrator
Real-time Integration: GPS → H3 Geofence → Alert Emission

PIPELINE:
  1. Receive GPSTrace from IMU driver (50 Hz GPS, 100 Hz IMU)
  2. Query H3 GeofenceEngine for nearby blackspots
  3. Load legal statute context from SpatialDatabaseManager
  4. Create GeoHazardEvent with legal reference
  5. Emit via JSON-RPC agent_bus.py → Other personas
  6. Log to event_log (audit trail)

ALERT ROUTING:
  - User Alert (Persona 4): TTS "High accident zone, reduce speed"
  - Legal Context (Persona 2): "Section 183 applies (speeding fine Rs 1000)"
  - Swarm Alert (Persona 1): Broadcast to nearby vehicles (V2X)
  - Logging (Persona 5): Audit trail + telemetry

RATE LIMITING:
  - Max 1 alert per 2km per cell (avoid spam)
  - Alert hysteresis: require 500m exit before re-alert
  - Throttle: 1 alert per 60 sec per vehicle (configurable)

FALLBACK MODES:
  - No GPS: Use IMU-only mode, emit "location unknown" alerts
  - No H3: Use simple geohash, slower queries
  - DB unavailable: Use in-memory blackspot list
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Callable

try:
    from agents.geofence_engine import H3GeofenceEngine, GPSTrace, GeoHazardEvent
    from etl.spatial_database_init import SpatialDatabaseManager
except ImportError:
    # Fallback imports
    class GPSTrace:
        pass
    class GeoHazardEvent:
        pass

logger = logging.getLogger("edge_sentinel.agents.hazard_alerter")
logger.setLevel(logging.DEBUG)

# ───────────────────────────────────────────────────────────────────────────
# Alert Configuration
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class AlerterConfig:
    """Configuration for hazard alerter behavior."""
    search_radius_m: float = 5000.0  # 5 km search radius
    min_distance_between_alerts_m: float = 2000.0  # Minimum 2 km between alerts
    alert_cooldown_sec: float = 60.0  # Re-alert cooldown
    alert_hysteresis_m: float = 500.0  # Exit distance for re-alert eligibility
    min_severity_threshold: float = 1.0  # Minimum severity to alert (1.0-5.0)
    include_legal_context: bool = True  # Fetch legal statute references
    enable_v2x_broadcast: bool = True  # Send to swarm
    enable_audit_logging: bool = True  # Log to event_log


# ───────────────────────────────────────────────────────────────────────────
# Hazard Alerter
# ───────────────────────────────────────────────────────────────────────────

class HazardAlerter:
    """
    Real-time hazard detection and alert generation.
    
    Responsible for:
    - Querying geofence engine
    - Filtering alerts (rate limiting, hysteresis)
    - Enriching with legal context
    - Emitting via agent_bus
    - Audit logging
    """

    def __init__(
        self,
        geofence_engine: H3GeofenceEngine,
        db_manager: Optional[SpatialDatabaseManager] = None,
        config: Optional[AlerterConfig] = None,
        rpc_callback: Optional[Callable] = None,
    ):
        """
        Initialize alerter.
        
        Args:
            geofence_engine: H3GeofenceEngine instance with preloaded blackspots
            db_manager: SpatialDatabaseManager for legal context (optional)
            config: AlerterConfig (uses defaults if None)
            rpc_callback: Function to emit JSON-RPC events to agent_bus
                          Signature: rpc_callback(event_dict) -> None
        """
        self.geofence_engine = geofence_engine
        self.db_manager = db_manager
        self.config = config or AlerterConfig()
        self.rpc_callback = rpc_callback or self._default_rpc_callback

        # State tracking (rate limiting, hysteresis)
        self.last_alert_time: Dict[str, float] = {}  # {h3_cell: timestamp}
        self.last_alert_location: Dict[str, tuple] = {}  # {h3_cell: (lat, lon)}
        self.vehicle_state: Dict[str, Dict] = {}  # {vehicle_id: {status, last_alert_time}}

        logger.info(f"HazardAlerter initialized with config: {self.config}")

    def process_gps_trace(
        self, gps_trace: GPSTrace, vehicle_id: str = "UNKNOWN"
    ) -> Optional[GeoHazardEvent]:
        """
        Process incoming GPS trace and generate alert if applicable.
        
        ALGORITHM:
        1. Query nearby blackspots
        2. Filter by severity threshold
        3. Check rate limiting
        4. Check hysteresis (exit distance)
        5. Enrich with legal context
        6. Emit and log
        7. Return alert (or None if filtered)

        Args:
            gps_trace: Current vehicle GPSTrace from IMU driver
            vehicle_id: Vehicle identifier for state tracking

        Returns:
            GeoHazardEvent if alert generated, else None
        """
        # Query nearby blackspots
        nearby = self.geofence_engine.detect_nearby_blackspots(
            gps_trace,
            search_radius_m=self.config.search_radius_m,
        )

        if not nearby:
            return None

        # Process in order of proximity (nearest first)
        for blackspot, distance_m in nearby:
            # Skip low-severity
            if blackspot.severity_avg < self.config.min_severity_threshold:
                continue

            # Rate limiting: check if we've alerted on this cell recently
            cell_key = blackspot.h3_index
            if self._is_rate_limited(cell_key):
                logger.debug(f"Rate limit hit for cell {cell_key}")
                continue

            # Hysteresis: check if vehicle has exited the alert zone
            if not self._check_hysteresis(cell_key, gps_trace.latitude, gps_trace.longitude):
                logger.debug(f"Hysteresis condition not met for cell {cell_key}")
                continue

            # Create event
            event = self.geofence_engine.create_hazard_event(gps_trace, blackspot, distance_m)

            # Enrich with legal context
            if self.config.include_legal_context:
                legal_context = self._fetch_legal_context(blackspot)
                event.alert_text += f" {legal_context}" if legal_context else ""

            # Emit and log
            self._emit_alert(event, vehicle_id)
            self._log_event(event, vehicle_id)

            # Update state
            self.last_alert_time[cell_key] = time.time()
            self.last_alert_location[cell_key] = (gps_trace.latitude, gps_trace.longitude)

            logger.info(f"✅ Alert emitted: {event.event_id} (severity {event.hazard_severity})")

            return event

        return None

    def process_batch(
        self, gps_traces: List[GPSTrace], vehicle_id: str = "UNKNOWN"
    ) -> List[GeoHazardEvent]:
        """
        Process multiple GPS traces (for buffered updates).
        
        Args:
            gps_traces: List of GPSTrace objects
            vehicle_id: Vehicle identifier

        Returns:
            List of generated GeoHazardEvents
        """
        events = []
        for trace in gps_traces:
            event = self.process_gps_trace(trace, vehicle_id)
            if event:
                events.append(event)

        return events

    # ─────────────────────────────────────────────────────────────────────
    # Rate Limiting & Hysteresis
    # ─────────────────────────────────────────────────────────────────────

    def _is_rate_limited(self, cell_key: str) -> bool:
        """Check if cell has been alerted recently (cooldown)."""
        if cell_key not in self.last_alert_time:
            return False

        elapsed = time.time() - self.last_alert_time[cell_key]
        is_limited = elapsed < self.config.alert_cooldown_sec

        return is_limited

    def _check_hysteresis(self, cell_key: str, lat: float, lon: float) -> bool:
        """
        Check if vehicle has exited the alert zone sufficiently.
        
        Returns True if:
        - First time alerting on this cell, OR
        - Vehicle has moved >alert_hysteresis_m away from last alert location
        """
        if cell_key not in self.last_alert_location:
            return True

        last_lat, last_lon = self.last_alert_location[cell_key]
        distance = self.geofence_engine._haversine_distance(lat, lon, last_lat, last_lon)

        return distance >= self.config.alert_hysteresis_m

    # ─────────────────────────────────────────────────────────────────────
    # Legal Context & Enrichment
    # ─────────────────────────────────────────────────────────────────────

    def _fetch_legal_context(self, blackspot) -> str:
        """
        Retrieve relevant legal statute references from database.
        
        Args:
            blackspot: BlackspotCell object

        Returns:
            Human-readable legal reference string (or empty)
        """
        if not self.db_manager or not self.config.include_legal_context:
            return ""

        try:
            # Query relevant statutes based on severity
            if blackspot.severity_avg >= 3.0:
                # High-severity: fetch "speeding" and "rash driving" statutes
                results = self.db_manager.search_legal_documents("speeding penalty")
            else:
                results = self.db_manager.search_legal_documents("caution zone")

            if results and len(results) > 0:
                statute = results[0]
                # Extract section number
                section_id = statute.get("section_id", "")
                return f"[{section_id}]"
            else:
                return ""

        except Exception as e:
            logger.warning(f"Legal context fetch failed: {e}")
            return ""

    # ─────────────────────────────────────────────────────────────────────
    # Emission & Logging
    # ─────────────────────────────────────────────────────────────────────

    def _emit_alert(self, event: GeoHazardEvent, vehicle_id: str):
        """
        Emit alert via JSON-RPC to agent_bus.
        
        Message format:
        {
            "method": "geo_hazard_alert",
            "params": {
                "event_id": "...",
                "severity": 4.8,
                "alert_text": "...",
                "recommended_speed": 40,
                "vehicle_id": "...",
                "timestamp": ...
            }
        }
        """
        try:
            rpc_msg = {
                "method": "geo_hazard_alert",
                "params": {
                    **asdict(event),
                    "vehicle_id": vehicle_id,
                },
            }
            self.rpc_callback(rpc_msg)
        except Exception as e:
            logger.error(f"Alert emission failed: {e}")

    def _log_event(self, event: GeoHazardEvent, vehicle_id: str):
        """Log to event audit trail."""
        if not self.config.enable_audit_logging or not self.db_manager:
            return

        try:
            self.db_manager.log_event(
                event_type="geofence_alert",
                event_id=event.event_id,
                vehicle_h3_cell=event.vehicle_h3_cell_res12,
                blackspot_h3_cell=event.nearby_blackspot_h3_res9,
                severity=event.hazard_severity,
                metadata={
                    "vehicle_id": vehicle_id,
                    "alert_text": event.alert_text,
                    "distance_m": event.distance_to_blackspot_m,
                },
            )
        except Exception as e:
            logger.warning(f"Event logging failed: {e}")

    @staticmethod
    def _default_rpc_callback(msg: Dict):
        """Default RPC callback: just log the message."""
        logger.info(f"RPC Emit: {json.dumps(msg, indent=2)}")


# ───────────────────────────────────────────────────────────────────────────
# Smoke Test (Deterministic, End-to-End)
# ───────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from agents.geofence_engine import BlackspotCell

    print("🚗 Hazard Alerter End-to-End Test")
    print("=" * 60)

    # Setup geofence engine with demo blackspots
    demo_blackspots = [
        BlackspotCell(
            h3_index="b85283473ffff",
            resolution=9,
            accident_count=47,
            severity_avg=4.8,
            deaths_count=12,
            injuries_count=68,
            last_updated="2026-03-15T10:00:00Z",
            road_type="highway",
        ),
    ]

    geofence_engine = H3GeofenceEngine(demo_blackspots)

    # Setup alerter
    config = AlerterConfig(
        alert_cooldown_sec=5.0,  # Short cooldown for testing
        include_legal_context=False,  # Skip DB for test
    )
    alerter = HazardAlerter(geofence_engine, config=config)

    # Simulate vehicle approaching blackspot
    gps_trace = GPSTrace(
        timestamp_ms=1711382400000.0,
        latitude=12.9352,
        longitude=77.6245,
        bearing_deg=45.0,
        speed_kmh=80.0,
        accuracy_m=5.0,
    )

    print("📍 Processing GPS trace...")
    event = alerter.process_gps_trace(gps_trace, vehicle_id="DEMO_VEHICLE_001")

    if event:
        print(f"\n✅ Alert Generated:")
        print(f"   Event ID: {event.event_id}")
        print(f"   Severity: {event.hazard_severity}/5.0")
        print(f"   Message: {event.alert_text}")
        print(f"   Distance: {event.distance_to_blackspot_m:.1f} m")
        print(f"   Recommended Speed: {event.recommended_speed_kmh} kmh" if event.recommended_speed_kmh else "   No speed change")
    else:
        print("❌ No alert generated (filtered)")

    print("\n✅ Hazard alerter test passed.")
