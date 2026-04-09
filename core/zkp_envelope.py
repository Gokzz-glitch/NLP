"""
core/zkp_envelope.py  (T-014)
SmartSalai Edge-Sentinel — ZKP GPS Envelope & Pedersen Commitment Telemetry Envelope

Two complementary APIs:

1. Coordinate Coarsening + SHA3 Commitment (GPS privacy stub, used by pipeline):
     from core.zkp_envelope import wrap_event, coarsen_coordinate
     event = wrap_event(event, raw_lat=12.9245, raw_lon=80.2301)

2. Pedersen Commitment + AES-256-GCM Telemetry Envelope (full cryptographic sealing):
     from core.zkp_envelope import ZKPEnvelopeBuilder, get_builder
     env = get_builder().seal(payload_dict, "NearMissEvent")

CURRENT STATUS:
  GPS ZKP: STUB — coordinate coarsening (≈500m grid) + SHA3 commitment.
  Telemetry envelope: Pedersen Commitment over MODP-1536 prime + AES-256-GCM.

COORDINATE COARSENING:
  Grid resolution: 0.005° ≈ 500m at Indian latitudes.
  Example: (12.9245, 80.2301) → (12.920, 80.230)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

if TYPE_CHECKING:
    from agents.imu_near_miss_detector import NearMissEvent

logger = logging.getLogger("edge_sentinel.core.zkp_envelope")

ENVELOPE_VERSION = "ZKP-1.0"

# ---------------------------------------------------------------------------
# Part 1: GPS coordinate coarsening (pipeline stub, T-014 backlog for Groth16)
# ---------------------------------------------------------------------------

# Grid cell size: 0.005° ≈ 500m at 13°N latitude
_GRID_DEG: float = 0.005
_SALT_BYTES: int = 16


def _coarsen(coord: float, grid: float = _GRID_DEG) -> float:
    """Snap a coordinate to the nearest grid cell centre."""
    return math.floor(coord / grid) * grid


def _commitment_hash(raw_lat: float, raw_lon: float, salt: bytes) -> str:
    """SHA3-256(salt || lat_str || ',' || lon_str) — verifiable by regulator."""
    payload = salt + f"{raw_lat:.6f},{raw_lon:.6f}".encode("utf-8")
    return "sha3:" + hashlib.sha3_256(payload).hexdigest()


def wrap_event(
    event: "NearMissEvent",
    raw_lat: float,
    raw_lon: float,
    device_salt: Optional[bytes] = None,
) -> "NearMissEvent":
    """
    Populate gps_lat / gps_lon on a NearMissEvent with coarsened coordinates.
    Attaches a SHA3-256 commitment to ``event._gps_commitment`` for audit.
    """
    if device_salt is None:
        device_salt = os.urandom(_SALT_BYTES)
    event.gps_lat = round(_coarsen(raw_lat), 3)
    event.gps_lon = round(_coarsen(raw_lon), 3)
    event._gps_commitment = _commitment_hash(raw_lat, raw_lon, device_salt)  # type: ignore[attr-defined]
    logger.debug(
        f"[T-014] ZKP envelope applied: "
        f"raw=({raw_lat:.4f},{raw_lon:.4f}) → coarsened=({event.gps_lat},{event.gps_lon})"
    )
    return event


def coarsen_coordinate(lat: float, lon: float) -> tuple:
    """Returns (coarsened_lat, coarsened_lon). Used by fleet telemetry uplink (T-018)."""
    return round(_coarsen(lat), 3), round(_coarsen(lon), 3)


# ---------------------------------------------------------------------------
# Part 2: Pedersen Commitment + AES-256-GCM telemetry envelope
# ---------------------------------------------------------------------------

# Prime-field Pedersen parameters (MODP-1536, RFC 3526 group 5)
_FIELD_PRIME = int(
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFC90FDAA2"
    "2168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A"
    "08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A89"
    "9FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA4831"
    "73F0BF8175C8A9B7", 16
)
_G = 2
_H = int.from_bytes(hashlib.sha3_256(b"SmartSalai_H_generator_v1").digest(), "big") % _FIELD_PRIME


def _sha3_256_hex(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def _pedersen_commit(value: int, blinding: int) -> int:
    return (pow(_G, blinding, _FIELD_PRIME) * pow(_H, value, _FIELD_PRIME)) % _FIELD_PRIME


def _derive_aes_key(blinding_bytes: bytes) -> bytes:
    """HKDF-like 256-bit key from blinding bytes."""
    return hmac.new(b"SmartSalai-ZKP-AES-KEY-v1", blinding_bytes, "sha3_256").digest()[:32]


def _aes_gcm_encrypt(plaintext: bytes, key: bytes) -> Tuple[bytes, bytes]:
    nonce = secrets.token_bytes(12)
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise RuntimeError(
            "cryptography package is required for AES-GCM. "
            "Install with: pip install cryptography"
        )
    return AESGCM(key).encrypt(nonce, plaintext, None), nonce


def _aes_gcm_decrypt(ciphertext: bytes, key: bytes, nonce: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise RuntimeError(
            "cryptography package is required for AES-GCM. "
            "Install with: pip install cryptography"
        )
    # Let AESGCM.decrypt raise InvalidTag on tamper — do NOT catch it
    return AESGCM(key).decrypt(nonce, ciphertext, None)


class TamperDetectedError(Exception):
    """Raised when an opened ZKP envelope fails commitment or evidence-hash verification."""


@dataclass
class ZKPEnvelope:
    envelope_version: str
    payload_type: str
    commitment_hex: str
    blinding_factor_hash: str
    evidence_hash: str
    timestamp_epoch_ms: int
    payload_ciphertext: str    # hex
    nonce_hex: str
    auditor_key_hint: str = ""
    # In-memory only — never serialised
    _blinding_bytes: Optional[bytes] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_version": self.envelope_version,
            "payload_type": self.payload_type,
            "commitment": self.commitment_hex,
            "blinding_factor_hash": self.blinding_factor_hash,
            "evidence_hash": self.evidence_hash,
            "timestamp_epoch_ms": self.timestamp_epoch_ms,
            "payload_ciphertext": self.payload_ciphertext,
            "nonce": self.nonce_hex,
            "auditor_key_hint": self.auditor_key_hint,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ZKPEnvelope":
        return cls(
            envelope_version=d["envelope_version"],
            payload_type=d["payload_type"],
            commitment_hex=d["commitment"],
            blinding_factor_hash=d["blinding_factor_hash"],
            evidence_hash=d["evidence_hash"],
            timestamp_epoch_ms=d["timestamp_epoch_ms"],
            payload_ciphertext=d["payload_ciphertext"],
            nonce_hex=d["nonce"],
            auditor_key_hint=d.get("auditor_key_hint", ""),
        )


@dataclass
class OpenedEnvelope:
    payload: Dict[str, Any]
    payload_type: str
    commitment_verified: bool
    evidence_hash_verified: bool
    timestamp_epoch_ms: int


class ZKPEnvelopeBuilder:
    """
    Seals/opens ZKP envelopes for telemetry payloads.

    Usage:
        builder = ZKPEnvelopeBuilder()
        env = builder.seal({"gps_lat": 12.924, "speed_kmh": 65.0}, "NearMissEvent")
        opened = builder.open(env, env._blinding_bytes)  # raises TamperDetectedError on tamper
    """

    def seal(self, payload: Dict[str, Any], payload_type: str, auditor_key_hint: str = "") -> ZKPEnvelope:
        ts = int(time.time() * 1000)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        evidence_hash = _sha3_256_hex(canonical.encode())

        if "gps_lat" in payload:
            value_int = abs(round(float(payload["gps_lat"]) * 1_000_000)) % _FIELD_PRIME
        else:
            value_int = int.from_bytes(bytes.fromhex(evidence_hash[:16]), "big") % _FIELD_PRIME

        blinding_bytes = secrets.token_bytes(32)
        blinding_int = int.from_bytes(blinding_bytes, "big") % _FIELD_PRIME

        commitment = _pedersen_commit(value_int, blinding_int)
        commitment_hex = commitment.to_bytes((commitment.bit_length() + 7) // 8 or 1, "big").hex()
        blinding_factor_hash = _sha3_256_hex(blinding_bytes)

        aes_key = _derive_aes_key(blinding_bytes)
        ciphertext, nonce = _aes_gcm_encrypt(canonical.encode(), aes_key)

        return ZKPEnvelope(
            envelope_version=ENVELOPE_VERSION,
            payload_type=payload_type,
            commitment_hex=commitment_hex,
            blinding_factor_hash=blinding_factor_hash,
            evidence_hash=evidence_hash,
            timestamp_epoch_ms=ts,
            payload_ciphertext=ciphertext.hex(),
            nonce_hex=nonce.hex(),
            auditor_key_hint=auditor_key_hint,
            _blinding_bytes=blinding_bytes,
        )

    def open(self, envelope: ZKPEnvelope, blinding_bytes: bytes) -> OpenedEnvelope:
        """
        Decrypt and verify a ZKP envelope.

        Raises:
            TamperDetectedError: if commitment or evidence hash verification fails.
            cryptography.exceptions.InvalidTag: if AES-GCM authentication fails (ciphertext tampered).
        """
        aes_key = _derive_aes_key(blinding_bytes)
        nonce = bytes.fromhex(envelope.nonce_hex)
        ciphertext = bytes.fromhex(envelope.payload_ciphertext)
        # _aes_gcm_decrypt raises InvalidTag on tamper — not caught here
        plaintext = _aes_gcm_decrypt(ciphertext, aes_key, nonce)
        payload = json.loads(plaintext.decode())

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        recomputed_eh = _sha3_256_hex(canonical.encode())
        evidence_ok = hmac.compare_digest(recomputed_eh, envelope.evidence_hash)

        if "gps_lat" in payload:
            value_int = abs(round(float(payload["gps_lat"]) * 1_000_000)) % _FIELD_PRIME
        else:
            value_int = int.from_bytes(bytes.fromhex(recomputed_eh[:16]), "big") % _FIELD_PRIME

        blinding_int = int.from_bytes(blinding_bytes, "big") % _FIELD_PRIME
        commitment_int = int.from_bytes(bytes.fromhex(envelope.commitment_hex), "big")
        expected = _pedersen_commit(value_int, blinding_int)
        commitment_ok = hmac.compare_digest(
            commitment_int.to_bytes(max((commitment_int.bit_length() + 7) // 8, 1), "big"),
            expected.to_bytes(max((expected.bit_length() + 7) // 8, 1), "big"),
        )

        if not commitment_ok or not evidence_ok:
            raise TamperDetectedError(
                f"ZKP envelope verification failed — "
                f"commitment_ok={commitment_ok}, evidence_hash_ok={evidence_ok}"
            )

        return OpenedEnvelope(
            payload=payload,
            payload_type=envelope.payload_type,
            commitment_verified=commitment_ok,
            evidence_hash_verified=evidence_ok,
            timestamp_epoch_ms=envelope.timestamp_epoch_ms,
        )

    def seal_telemetry(self, event_dict: Dict[str, Any], payload_type: str = "TelemetryEvent") -> Dict[str, Any]:
        """Convenience: seal and return as dict (for iRAD record embedding)."""
        return self.seal(event_dict, payload_type).to_dict()


_builder: Optional[ZKPEnvelopeBuilder] = None


def get_builder() -> ZKPEnvelopeBuilder:
    global _builder
    if _builder is None:
        _builder = ZKPEnvelopeBuilder()
    return _builder
