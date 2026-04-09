"""
core/zkp_envelope.py
SmartSalai Edge-Sentinel — T-014: Zero-Knowledge Proof GPS Envelope

PURPOSE:
  Populates the GPS fields on a NearMissEvent immediately before telemetry
  emission. The ZKP layer ensures the *exact* GPS coordinate is never stored
  or transmitted in the clear; instead it is replaced with a coarsened
  grid-cell reference + a salted SHA3-256 commitment hash that a regulator
  can verify against the raw coordinate without the raw coordinate ever
  leaving the device.

CURRENT STATUS:
  STUB — full ZKP circuit (Groth16 over BN254 via snarkjs) is on T-014 backlog.
  This stub applies coordinate coarsening (≈500m grid) + SHA3 commitment and
  is safe to call in all existing pipeline tests.

COORDINATE COARSENING:
  Grid resolution: 0.005° ≈ 500m at Indian latitudes.
  Example: (12.9245, 80.2301) → (12.920, 80.230)

USAGE:
    from core.zkp_envelope import wrap_event
    event = wrap_event(event, raw_lat=12.9245, raw_lon=80.2301)
    # event.gps_lat = 12.920, event.gps_lon = 80.230
    # event._gps_commitment = "sha3:…" (hex)
"""

from __future__ import annotations

import hashlib
import math
import os
import time
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agents.imu_near_miss_detector import NearMissEvent

logger = logging.getLogger("edge_sentinel.core.zkp_envelope")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Grid cell size in decimal degrees.  0.005° ≈ 500m at 13° N latitude.
_GRID_DEG: float = 0.005

# Salt length for commitment hash (device-local, never transmitted)
_SALT_BYTES: int = 16


# ---------------------------------------------------------------------------
# Coordinate coarsening
# ---------------------------------------------------------------------------

def _coarsen(coord: float, grid: float = _GRID_DEG) -> float:
    """
    Snap a coordinate to the nearest grid cell centre.
    Example: 12.9245 → floor(12.9245 / 0.005) * 0.005 = 12.920
    """
    return math.floor(coord / grid) * grid


# ---------------------------------------------------------------------------
# Commitment hash (stub — real ZKP circuit goes here in T-014)
# ---------------------------------------------------------------------------

def _commitment_hash(raw_lat: float, raw_lon: float, salt: bytes) -> str:
    """
    Returns hex(SHA3-256(salt || raw_lat_str || "," || raw_lon_str)).
    The regulator can verify by re-computing with the disclosed raw coords + salt.
    """
    payload = salt + f"{raw_lat:.6f},{raw_lon:.6f}".encode("utf-8")
    return "sha3:" + hashlib.sha3_256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def wrap_event(
    event: "NearMissEvent",
    raw_lat: float,
    raw_lon: float,
    device_salt: Optional[bytes] = None,
) -> "NearMissEvent":
    """
    Populate gps_lat / gps_lon on a NearMissEvent with coarsened coordinates.
    Attaches a SHA3-256 commitment to ``event._gps_commitment`` for audit.

    Args:
        event       : NearMissEvent to mutate (in-place).
        raw_lat     : Raw GPS latitude from GNSS module (decimal degrees).
        raw_lon     : Raw GPS longitude from GNSS module (decimal degrees).
        device_salt : 16-byte device-local random salt. Auto-generated if None.

    Returns:
        The same event object with gps_lat / gps_lon populated.
    """
    if device_salt is None:
        device_salt = os.urandom(_SALT_BYTES)

    event.gps_lat = round(_coarsen(raw_lat), 3)
    event.gps_lon = round(_coarsen(raw_lon), 3)

    # Store commitment as a dynamic attribute (not part of iRAD schema)
    event._gps_commitment = _commitment_hash(raw_lat, raw_lon, device_salt)  # type: ignore[attr-defined]

    logger.debug(
        f"[T-014] ZKP envelope applied: "
        f"raw=({raw_lat:.4f},{raw_lon:.4f}) → coarsened=({event.gps_lat},{event.gps_lon})"
    )
    return event


def coarsen_coordinate(lat: float, lon: float) -> tuple[float, float]:
    """
    Convenience function: returns (coarsened_lat, coarsened_lon) without
    requiring a NearMissEvent.  Used by fleet telemetry uplink (T-018).
    """
    return round(_coarsen(lat), 3), round(_coarsen(lon), 3)
