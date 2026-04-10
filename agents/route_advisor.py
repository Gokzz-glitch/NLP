"""
agents/route_advisor.py
SmartSalai — Crowd-sourced Hazard-Aware Route Advisor

Records hazards reported from all nodes into a shared SQLite DB.
Scores route alternatives by summing weighted, time-decayed hazard
contributions within a configurable radius of each waypoint.
"""

from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HAZARD_SCAN_RADIUS_M = 100   # metres around each waypoint to look for hazards
HAZARD_DECAY_H       = 4     # hours after which a hazard contribution halves

# Per-class severity weights (higher = worse road condition)
HAZARD_WEIGHTS: dict[str, float] = {
    "pothole":          1.5,
    "road_work":        1.2,
    "debris":           1.3,
    "flooded_road":     2.0,
    "speed_limit_sign": 0.2,
    "stop_sign":        0.3,
    "traffic_light":    0.2,
}
_DEFAULT_WEIGHT = 0.8

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "hazards.db"


# ---------------------------------------------------------------------------
# Haversine helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two (lat, lon) points."""
    R = 6_371_000.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a  = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bbox(lat: float, lon: float, radius_m: float) -> Tuple[float, float, float, float]:
    """Fast bounding-box for a lat/lon + radius (pre-filter before haversine)."""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


# ---------------------------------------------------------------------------
# RouteAdvisor
# ---------------------------------------------------------------------------

class RouteAdvisor:

    def __init__(self, db_path: str | None = None) -> None:
        self._db = str(db_path or _DEFAULT_DB)
        Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hazard_reports (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id      TEXT    NOT NULL,
                    hazard_class TEXT    NOT NULL,
                    confidence   REAL    NOT NULL DEFAULT 1.0,
                    lat          REAL    NOT NULL,
                    lon          REAL    NOT NULL,
                    reported_at  REAL    NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lat ON hazard_reports(lat)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lon ON hazard_reports(lon)")
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_hazard(
        self,
        node_id: str,
        hazard_class: str,
        confidence: float,
        lat: float,
        lon: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO hazard_reports (node_id, hazard_class, confidence, lat, lon, reported_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (node_id, hazard_class, float(confidence), float(lat), float(lon), time.time()),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_hazards_near(
        self,
        lat: float,
        lon: float,
        radius_m: float = HAZARD_SCAN_RADIUS_M,
        max_age_h: float = 24.0,
    ) -> List[dict]:
        min_lat, max_lat, min_lon, max_lon = _bbox(lat, lon, radius_m)
        cutoff = time.time() - max_age_h * 3600
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hazard_reports "
                "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
                "  AND reported_at >= ? "
                "ORDER BY reported_at DESC",
                (min_lat, max_lat, min_lon, max_lon, cutoff),
            ).fetchall()
        result = []
        for row in rows:
            dist = _haversine_m(lat, lon, row["lat"], row["lon"])
            if dist <= radius_m:
                result.append({
                    "id":           row["id"],
                    "node_id":      row["node_id"],
                    "hazard_class": row["hazard_class"],
                    "confidence":   row["confidence"],
                    "lat":          row["lat"],
                    "lon":          row["lon"],
                    "reported_at":  row["reported_at"],
                    "distance_m":   round(dist, 1),
                })
        return result

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_route(
        self,
        waypoints: List[Tuple[float, float]],
        radius_m: float = HAZARD_SCAN_RADIUS_M,
        max_age_h: float = 24.0,
    ) -> float:
        """
        Score a route by summing time-decayed, confidence-weighted hazard
        contributions near each waypoint. Higher = worse (more hazardous).

        Deduplication: each hazard record is counted at most once even if
        it falls within range of multiple consecutive waypoints.
        """
        score, _ = self._score_route_with_hazards(
            waypoints, radius_m=radius_m, max_age_h=max_age_h
        )
        return score

    def _score_route_with_hazards(
        self,
        waypoints: List[Tuple[float, float]],
        radius_m: float = HAZARD_SCAN_RADIUS_M,
        max_age_h: float = 24.0,
    ):
        """
        Score a route and return both the score and the deduplicated hazard list.

        Returns:
            (score: float, hazards: list[dict])
        """
        if not waypoints:
            return 0.0, []

        seen_ids: set[int] = set()
        total_score = 0.0
        hazards = []

        for lat, lon in waypoints:
            for h in self.get_hazards_near(lat, lon, radius_m=radius_m, max_age_h=max_age_h):
                hid = h["id"]
                if hid in seen_ids:
                    continue
                seen_ids.add(hid)
                hazards.append(h)
                weight = HAZARD_WEIGHTS.get(h["hazard_class"], _DEFAULT_WEIGHT)
                # Time decay: halves every HAZARD_DECAY_H hours
                age_h = (time.time() - h["reported_at"]) / 3600.0
                decay = math.exp(-math.log(2) * age_h / HAZARD_DECAY_H)
                total_score += weight * h["confidence"] * decay

        return round(total_score, 4), hazards

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def recommend(
        self,
        alternatives: List[List[Tuple[float, float]]],
        labels: Optional[List[str]] = None,
    ) -> dict:
        """
        Given a list of route alternatives (each is a list of waypoints),
        return the safest (lowest-score) route.
        """
        if not alternatives:
            return {"error": "No routes provided."}

        labels = labels or [f"Route {i + 1}" for i in range(len(alternatives))]

        scored = []
        for i, route in enumerate(alternatives):
            s, hazards = self._score_route_with_hazards(route)
            scored.append({
                "index":   i,
                "label":   labels[i] if i < len(labels) else f"Route {i + 1}",
                "score":   s,
                "hazards": hazards,
            })

        best = min(scored, key=lambda x: x["score"])
        return {
            "recommended_index": best["index"],
            "recommended_label": best["label"],
            "scores": {r["label"]: r["score"] for r in scored},
            "routes": [{"label": r["label"], "score": r["score"], "hazards": r["hazards"]}
                       for r in scored],
        }

    # ------------------------------------------------------------------
    # Live feed
    # ------------------------------------------------------------------

    def get_live_hazard_feed(
        self,
        max_age_h: float = 2.0,
        limit: int = 100,
    ) -> List[dict]:
        cutoff = time.time() - max_age_h * 3600
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hazard_reports WHERE reported_at >= ? "
                "ORDER BY reported_at DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        now = time.time()
        return [
            {
                "id":           row["id"],
                "node_id":      row["node_id"],
                "hazard_class": row["hazard_class"],
                "confidence":   row["confidence"],
                "lat":          row["lat"],
                "lon":          row["lon"],
                "reported_at":  row["reported_at"],
                "age_min":      round((now - row["reported_at"]) / 60, 1),
            }
            for row in rows
        ]
