"""
orchestrator/app/tools/speed_limit.py
Valhalla-based speed-limit lookup with Tamil Nadu fallback table.

Queries the Valhalla routing engine's ``/locate`` endpoint to obtain edge
attributes (including posted speed) for the nearest road to a lat/lon fix.
When Valhalla is unavailable, a static Tamil Nadu road-class table is used as
a fallback.

Tamil Nadu speed limit reference (MV Act / IRC guidelines):
  Urban arterial / NH inside city limits  — 50 km/h
  State highway / MDR rural               — 60 km/h
  National Highway rural                  — 80 km/h
  Expressway (Chennai – Bengaluru, etc.)  — 100 km/h
  School / hospital zone                  — 25 km/h

TODO:
  - Use Valhalla ``/trace_attributes`` with the 50-point GPS trace for
    more accurate map-matching on curved roads.
  - Fetch real-time variable speed limits from NHAI ITS feed when available.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_VALHALLA_HOST = os.getenv("VALHALLA_HOST", "valhalla")
_VALHALLA_PORT = int(os.getenv("VALHALLA_PORT", "8002"))
_VALHALLA_URL = f"http://{_VALHALLA_HOST}:{_VALHALLA_PORT}"

# ── Tamil Nadu static speed-limit fallback table ──────────────────────────────
# Keyed by Valhalla road_class string → posted speed in km/h
_TN_SPEED_TABLE: dict[str, int] = {
    "motorway": 100,
    "trunk": 80,
    "primary": 60,
    "secondary": 60,
    "tertiary": 50,
    "unclassified": 40,
    "residential": 30,
    "service": 25,
}

_DEFAULT_SPEED_KMH = 50  # urban default when class is unknown


# ── public API ────────────────────────────────────────────────────────────────

def get_limit(lat: float, lon: float, timeout: float = 3.0) -> int:
    """
    Return the posted speed limit in km/h for the road nearest to
    (``lat``, ``lon``).

    Tries Valhalla first; on any error falls back to the Tamil Nadu static
    table using the road class returned by Valhalla, or the urban default
    (50 km/h) when no class is available.

    Parameters
    ----------
    lat:
        WGS-84 latitude of the current GPS fix.
    lon:
        WGS-84 longitude of the current GPS fix.
    timeout:
        HTTP request timeout in seconds.

    Returns
    -------
    int
        Speed limit in km/h.
    """
    valhalla_speed = _query_valhalla(lat, lon, timeout)
    if valhalla_speed is not None:
        return valhalla_speed

    logger.debug("Valhalla unavailable — using TN static table")
    return _DEFAULT_SPEED_KMH


def get_limit_with_class(lat: float, lon: float, timeout: float = 3.0) -> dict:
    """
    Extended version of :func:`get_limit` that also returns the road class.

    Returns
    -------
    dict
        ``{"speed_kmh": int, "road_class": str, "source": str}``
    """
    try:
        data = _valhalla_locate(lat, lon, timeout)
        if data:
            edge = _extract_edge(data)
            if edge:
                speed = int(edge.get("speed", 0)) or _DEFAULT_SPEED_KMH
                road_class = edge.get("road_class", "unknown")
                return {"speed_kmh": speed, "road_class": road_class, "source": "valhalla"}
    except Exception as exc:
        logger.debug("Valhalla locate error: %s", exc)

    return {"speed_kmh": _DEFAULT_SPEED_KMH, "road_class": "unknown", "source": "static_tn"}


# ── Valhalla helpers ──────────────────────────────────────────────────────────

def _query_valhalla(lat: float, lon: float, timeout: float) -> Optional[int]:
    """
    Call Valhalla ``/locate`` and extract the posted speed from the nearest
    edge.  Returns ``None`` on any error.
    """
    try:
        data = _valhalla_locate(lat, lon, timeout)
        if data:
            edge = _extract_edge(data)
            if edge:
                speed = int(edge.get("speed", 0))
                if speed > 0:
                    return speed
                # Fall back to TN table using road class
                road_class = edge.get("road_class", "")
                return _TN_SPEED_TABLE.get(road_class, _DEFAULT_SPEED_KMH)
    except Exception as exc:
        logger.debug("Valhalla query failed: %s", exc)
    return None


def _valhalla_locate(lat: float, lon: float, timeout: float) -> Optional[list]:
    """
    POST to Valhalla ``/locate`` and return the parsed JSON response list.
    """
    url = f"{_VALHALLA_URL}/locate"
    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": "auto",
        "verbose": True,
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _extract_edge(locate_result: list) -> Optional[dict]:
    """
    Pull the first edge attributes dict from a Valhalla ``/locate`` response.
    """
    if not locate_result or not isinstance(locate_result, list):
        return None
    first = locate_result[0]
    edges = first.get("edges") or []
    if edges:
        return edges[0]
    return None
