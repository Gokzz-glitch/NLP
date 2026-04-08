"""
agents/blackspot_geofence.py
SmartSalai Edge-Sentinel — Chennai Blackspot Geofencing

Parses chennai-road-crashes-1998-2025.csv to identify accident hotspots
and triggers geofence alerts when the vehicle is within radius of a zone.

The CSV has yearly aggregate data (no GPS coordinates per row), so the agent:
  1. Computes risk index from historical accident rate per year
  2. Maps to a fixed set of well-known Chennai road crash blackspot coordinates
     (from published TN traffic police data)
  3. Triggers BUS alerts when rider enters a zone
"""

from __future__ import annotations

import csv
import logging
import math
import os
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.agents.blackspot_geofence")

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_DEFAULT_CSV = str(_REPO_ROOT / "raw_data" / "chennai-road-crashes-1998-2025.csv")

GEOFENCE_RADIUS_M = 300.0
ALERT_COOLDOWN_S  = 60.0


# ---------------------------------------------------------------------------
# Known Chennai blackspot coordinates (from TN Traffic Police published data)
# ---------------------------------------------------------------------------
_KNOWN_BLACKSPOTS: List[Dict[str, Any]] = [
    {"zone_name": "Kathipara Junction",         "lat": 13.0102, "lon": 80.2069, "base_risk": 0.75},
    {"zone_name": "Maduravoyal Bypass",         "lat": 13.0674, "lon": 80.1589, "base_risk": 0.70},
    {"zone_name": "Poonamallee High Road",      "lat": 13.0478, "lon": 80.1910, "base_risk": 0.65},
    {"zone_name": "OMR Perungudi Signal",       "lat": 12.9481, "lon": 80.2357, "base_risk": 0.60},
    {"zone_name": "Vandalur Roundabout",        "lat": 12.8876, "lon": 80.0789, "base_risk": 0.62},
    {"zone_name": "Tambaram Bypass",            "lat": 12.9249, "lon": 80.1000, "base_risk": 0.58},
    {"zone_name": "Meenambakkam Flyover",       "lat": 12.9941, "lon": 80.1617, "base_risk": 0.55},
    {"zone_name": "Koyambedu Signal",           "lat": 13.0694, "lon": 80.1948, "base_risk": 0.68},
    {"zone_name": "Anna Salai–Nandanam",        "lat": 13.0339, "lon": 80.2490, "base_risk": 0.57},
    {"zone_name": "ECR Sholinganallur",         "lat": 12.9010, "lon": 80.2279, "base_risk": 0.61},
]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# CSV parser — extracts trend data
# ---------------------------------------------------------------------------
def _parse_csv(csv_path: str) -> Dict[str, Any]:
    """Parse yearly aggregate CSV and return trend summary."""
    rows = []
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    year = int(row.get("YEAR", 0))
                    total = int(row.get("Total Accidents", 0) or 0)
                    fatal_killed = int(row.get("Fatal Killed", 0) or 0)
                    rows.append({"year": year, "total": total, "fatal_killed": fatal_killed})
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        logger.warning(f"[Blackspot] CSV not found: {csv_path}")
        return {}

    if not rows:
        return {}

    rows.sort(key=lambda r: r["year"])
    latest = rows[-1]
    peak = max(rows, key=lambda r: r["total"])
    first_total = rows[0]["total"] if rows else 1
    latest_total = latest["total"] if latest["total"] else 1
    risk_index = min(1.0, latest_total / max(r["total"] for r in rows))

    return {
        "data_years": f"{rows[0]['year']}–{rows[-1]['year']}",
        "latest_year": latest["year"],
        "latest_total_accidents": latest["total"],
        "latest_fatal_killed": latest["fatal_killed"],
        "peak_year": peak["year"],
        "peak_total_accidents": peak["total"],
        "latest_risk_index": round(risk_index, 2),
        "blackspot_count": len(_KNOWN_BLACKSPOTS),
    }


# ---------------------------------------------------------------------------
# Geofence agent
# ---------------------------------------------------------------------------
@dataclass
class BlackspotZone:
    zone_name: str
    lat: float
    lon: float
    risk_index: float
    radius_m: float = GEOFENCE_RADIUS_M
    last_alert_ts: float = 0.0

    def distance_to(self, lat: float, lon: float) -> float:
        return _haversine_m(self.lat, self.lon, lat, lon)

    def is_inside(self, lat: float, lon: float) -> bool:
        return self.distance_to(lat, lon) <= self.radius_m


class BlackspotGeofenceAgent:
    """
    Geofence alerting agent for Chennai road crash blackspots.

    Usage:
        agent = BlackspotGeofenceAgent()
        agent.load()
        alert = agent.check_position(lat=13.0102, lon=80.2069)
    """

    def __init__(self, csv_path: Optional[str] = None) -> None:
        self._csv_path = csv_path or _DEFAULT_CSV
        self._zones: List[BlackspotZone] = []
        self._trend: Dict[str, Any] = {}
        self._bus = None

    def attach_bus(self, bus) -> None:
        self._bus = bus

    def load(self) -> bool:
        self._trend = _parse_csv(self._csv_path)
        # Build zones from known blackspot list + risk index from CSV trend
        risk_scale = self._trend.get("latest_risk_index", 1.0)
        self._zones = [
            BlackspotZone(
                zone_name=bs["zone_name"],
                lat=bs["lat"],
                lon=bs["lon"],
                risk_index=round(bs["base_risk"] * risk_scale / 0.5, 2),  # scale by trend
            )
            for bs in _KNOWN_BLACKSPOTS
        ]
        logger.info(f"[Blackspot] Loaded {len(self._zones)} zones. Trend: {self._trend}")
        return bool(self._zones)

    def check_position(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """Check if position is inside any blackspot zone. Returns alert dict or None."""
        now = time.time()
        for zone in self._zones:
            dist = zone.distance_to(lat, lon)
            if dist <= zone.radius_m:
                if now - zone.last_alert_ts < ALERT_COOLDOWN_S:
                    return None  # Cooldown active
                zone.last_alert_ts = now
                alert = {
                    "zone_name": zone.zone_name,
                    "lat": lat,
                    "lon": lon,
                    "zone_lat": zone.lat,
                    "zone_lon": zone.lon,
                    "distance_m": round(dist),
                    "risk_index": zone.risk_index,
                }
                logger.info(
                    f"[Blackspot] ZONE ENTERED: {zone.zone_name} | "
                    f"dist={round(dist)}m risk={zone.risk_index}"
                )
                if self._bus:
                    from core.agent_bus import Topics
                    self._bus.publish(Topics.BLACKSPOT_ALERT, alert)
                return alert
        return None

    def get_trend(self) -> Dict[str, Any]:
        return dict(self._trend)

    def get_zones(self) -> List[Dict[str, Any]]:
        return [
            {
                "zone_name": z.zone_name,
                "lat": z.lat,
                "lon": z.lon,
                "risk_index": z.risk_index,
                "radius_m": z.radius_m,
            }
            for z in self._zones
        ]


_agent: Optional[BlackspotGeofenceAgent] = None


def get_agent() -> BlackspotGeofenceAgent:
    global _agent
    if _agent is None:
        _agent = BlackspotGeofenceAgent()
        _agent.load()
    return _agent
