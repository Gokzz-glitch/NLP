"""
tests/test_zkp_envelope.py

Unit tests for core/zkp_envelope.py covering:
  - _coarsen: grid snapping, negative coords, custom grid
  - _commitment_hash: SHA3-256 format, determinism, salt sensitivity
  - wrap_event: gps_lat/gps_lon populated and coarsened, commitment attached
  - coarsen_coordinate: round-trip convenience function
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
from unittest.mock import MagicMock

from core.zkp_envelope import (
    wrap_event,
    coarsen_coordinate,
    _coarsen,
    _commitment_hash,
    _GRID_DEG,
)


def _make_event():
    evt = MagicMock()
    evt.gps_lat = None
    evt.gps_lon = None
    return evt


# ---------------------------------------------------------------------------
# _coarsen
# ---------------------------------------------------------------------------

class TestCoarsen:

    def test_snaps_to_grid(self):
        result = _coarsen(12.9245)
        expected = math.floor(12.9245 / _GRID_DEG) * _GRID_DEG
        assert abs(result - expected) < 1e-9

    def test_exact_grid_boundary_unchanged(self):
        val = 5 * _GRID_DEG
        assert abs(_coarsen(val) - val) < 1e-9

    def test_negative_coordinate(self):
        result = _coarsen(-12.9245)
        expected = math.floor(-12.9245 / _GRID_DEG) * _GRID_DEG
        assert abs(result - expected) < 1e-9

    def test_zero(self):
        assert _coarsen(0.0) == 0.0

    def test_custom_grid(self):
        result = _coarsen(1.234, grid=0.1)
        assert abs(result - 1.2) < 1e-9

    def test_large_value(self):
        result = _coarsen(80.2301)
        expected = math.floor(80.2301 / _GRID_DEG) * _GRID_DEG
        assert abs(result - expected) < 1e-9


# ---------------------------------------------------------------------------
# _commitment_hash
# ---------------------------------------------------------------------------

class TestCommitmentHash:

    def test_returns_sha3_prefix(self):
        h = _commitment_hash(12.0, 80.0, b"\x00" * 16)
        assert h.startswith("sha3:")

    def test_hexdigest_length(self):
        h = _commitment_hash(12.0, 80.0, b"\x01" * 16)
        # "sha3:" prefix (5) + 64 hex chars = 69
        assert len(h) == 69

    def test_deterministic_same_inputs(self):
        salt = b"\xAB" * 16
        assert _commitment_hash(12.9, 80.2, salt) == _commitment_hash(12.9, 80.2, salt)

    def test_different_coords_different_hash(self):
        salt = b"\x00" * 16
        h1 = _commitment_hash(12.9, 80.2, salt)
        h2 = _commitment_hash(12.9, 80.3, salt)
        assert h1 != h2

    def test_different_salt_different_hash(self):
        h1 = _commitment_hash(12.9, 80.2, b"\x00" * 16)
        h2 = _commitment_hash(12.9, 80.2, b"\xFF" * 16)
        assert h1 != h2

    def test_only_hex_chars_after_prefix(self):
        h = _commitment_hash(13.0, 80.0, b"\x42" * 16)
        hex_part = h[len("sha3:"):]
        assert all(c in "0123456789abcdef" for c in hex_part)


# ---------------------------------------------------------------------------
# wrap_event
# ---------------------------------------------------------------------------

class TestWrapEvent:

    def test_gps_lat_populated(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        assert evt.gps_lat is not None

    def test_gps_lon_populated(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        assert evt.gps_lon is not None

    def test_gps_lat_is_coarsened(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        expected_lat = round(math.floor(12.9245 / _GRID_DEG) * _GRID_DEG, 3)
        assert abs(evt.gps_lat - expected_lat) < 1e-6

    def test_gps_lon_is_coarsened(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        expected_lon = round(math.floor(80.2301 / _GRID_DEG) * _GRID_DEG, 3)
        assert abs(evt.gps_lon - expected_lon) < 1e-6

    def test_commitment_hash_attached(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        assert hasattr(evt, "_gps_commitment")
        assert evt._gps_commitment.startswith("sha3:")

    def test_device_salt_accepted(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301, device_salt=b"\x42" * 16)
        assert evt._gps_commitment.startswith("sha3:")

    def test_returns_same_event_object(self):
        evt = _make_event()
        result = wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        assert result is evt

    def test_coarsened_lat_is_3dp(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        assert round(evt.gps_lat, 3) == evt.gps_lat

    def test_coarsened_lon_is_3dp(self):
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301)
        assert round(evt.gps_lon, 3) == evt.gps_lon

    def test_random_salt_produces_valid_commitment(self):
        """Auto-generated salt (None) must produce a valid sha3: hash."""
        evt = _make_event()
        wrap_event(evt, raw_lat=12.9245, raw_lon=80.2301, device_salt=None)
        assert evt._gps_commitment.startswith("sha3:")


# ---------------------------------------------------------------------------
# coarsen_coordinate
# ---------------------------------------------------------------------------

class TestCoarsenCoordinate:

    def test_returns_tuple(self):
        result = coarsen_coordinate(12.9245, 80.2301)
        assert isinstance(result, tuple) and len(result) == 2

    def test_both_values_coarsened(self):
        lat, lon = coarsen_coordinate(12.9245, 80.2301)
        expected_lat = round(math.floor(12.9245 / _GRID_DEG) * _GRID_DEG, 3)
        expected_lon = round(math.floor(80.2301 / _GRID_DEG) * _GRID_DEG, 3)
        assert abs(lat - expected_lat) < 1e-6
        assert abs(lon - expected_lon) < 1e-6

    def test_zero_zero(self):
        lat, lon = coarsen_coordinate(0.0, 0.0)
        assert lat == 0.0 and lon == 0.0

    def test_indian_coordinates(self):
        """Chennai city centre — coarsened coordinates must be in India."""
        lat, lon = coarsen_coordinate(13.0827, 80.2707)
        assert 12.0 < lat < 14.0
        assert 79.0 < lon < 81.0
