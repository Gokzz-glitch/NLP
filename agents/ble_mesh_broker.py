"""
agents/ble_mesh_broker.py
SmartSalai Edge-Sentinel — P1: BLE V2X Mesh Broker

Implements the BLE mesh protocol defined in ble_mesh_protocol.json:
  - HMAC-SHA256 message signing and verification
  - AES-128-CCM payload encryption (requires `cryptography` package)
  - Nonce-based replay attack prevention with 30 s window
  - Hop-count / TTL enforcement
  - Handler dispatch on validated receive

ERR-001 note: real BLE advertising / scanning requires platform-level
  BLE driver integration (bleak / Android BluetoothLeAdvertiser).
  This module implements the protocol logic layer only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.ble_mesh_broker")

# ---------------------------------------------------------------------------
# Optional AES-128-CCM encryption (cryptography package)
# ---------------------------------------------------------------------------

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    _AESCCM_AVAILABLE = True
except ImportError:
    _AESCCM_AVAILABLE = False
    logger.warning(
        "[BLE] `cryptography` package not installed — AES-128-CCM encryption disabled. "
        "Run: pip install cryptography"
    )

# ---------------------------------------------------------------------------
# Protocol constants (sourced from ble_mesh_protocol.json)
# ---------------------------------------------------------------------------

_PROTO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ble_mesh_protocol.json")
try:
    with open(_PROTO_PATH) as _f:
        _PROTOCOL: dict = json.load(_f)
except FileNotFoundError:
    _PROTOCOL = {}

_DEFAULT_TTL: int = _PROTOCOL.get("offline_mesh_configuration", {}).get("mesh_ttl", 7)
_REPLAY_WINDOW_S: float = 30.0       # Reject messages older than 30 s
_FUTURE_SKEW_S: float = 5.0          # Allow 5 s clock skew for future-dated messages
_MAX_SEEN_CACHE: int = 1000          # Cap on replay-prevention nonce cache size
_NONCE_BYTES: int = 12               # 12-byte HMAC nonce; first 7 used for AES-CCM


# ---------------------------------------------------------------------------
# MeshMessage dataclass
# ---------------------------------------------------------------------------

@dataclass
class MeshMessage:
    """
    Single BLE mesh protocol message.  See ble_mesh_protocol.json for field spec.

    message_type:
      1 = HAZARD_ALERT
      2 = LEGAL_SYNC
      3 = MESH_HEARTBEAT
    """
    message_type: int
    node_id: str
    timestamp_ms: int
    payload: dict
    nonce: bytes = field(default_factory=lambda: os.urandom(_NONCE_BYTES))
    ttl: int = _DEFAULT_TTL
    hop_count: int = 0
    signature: Optional[bytes] = None

    @property
    def message_id(self) -> str:
        """Unique dedup key: node_id + nonce hex."""
        return f"{self.node_id}:{self.nonce.hex()}"


# ---------------------------------------------------------------------------
# BLEMeshBroker
# ---------------------------------------------------------------------------

class BLEMeshBroker:
    """
    BLE V2X mesh protocol broker.

    Message lifecycle:
      publish_hazard() → sign() → [encrypt()] → broadcast (caller's responsibility)
      receive()        → check TTL → check replay → verify signature → [decrypt] → dispatch

    Thread-safety:
      Separate locks for seen-nonce cache and handler list.
      All public methods are safe to call from multiple threads.

    Key management:
      signing_key: 32-byte HMAC-SHA256 key (shared mesh secret).
      aes_key:     First 16 bytes of signing_key → AES-128 key.
      In production, load both from TrustZone / Android Keystore.
    """

    def __init__(
        self,
        node_id: str,
        signing_key: Optional[bytes] = None,
    ) -> None:
        """
        Args:
            node_id:     Unique node identifier (≤ 16 chars per protocol spec).
            signing_key: 32-byte HMAC key.  If None, a dev key is derived from
                         node_id (deterministic, NOT for production).
        """
        self.node_id = node_id

        if signing_key is None:
            # Derive a deterministic dev key — replace with Keystore in production
            signing_key = hashlib.sha256(node_id.encode("utf-8")).digest()
        if len(signing_key) < 16:
            raise ValueError("signing_key must be at least 16 bytes")

        self._signing_key: bytes = signing_key
        # AES-128-CCM uses a 16-byte key (first 16 bytes of signing material)
        self._aes_key: bytes = signing_key[:16]

        # Replay prevention: message_id → receive_time
        self._seen_nonces: Dict[str, float] = {}
        self._seen_lock = threading.Lock()

        # Dispatch handlers
        self._handlers: List[Callable[[MeshMessage], None]] = []
        self._handler_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    def _sign_message(self, msg: MeshMessage) -> bytes:
        """
        HMAC-SHA256( key=signing_key,
                     message=node_id_bytes || timestamp_8B_BE || nonce || payload_json )
        """
        payload_bytes = json.dumps(msg.payload, sort_keys=True).encode("utf-8")
        signed_data = (
            msg.node_id.encode("utf-8")
            + struct.pack(">Q", msg.timestamp_ms)
            + msg.nonce
            + payload_bytes
        )
        return hmac.new(self._signing_key, signed_data, hashlib.sha256).digest()

    def _verify_signature(self, msg: MeshMessage) -> bool:
        """Return True iff msg.signature matches the expected HMAC-SHA256."""
        if msg.signature is None:
            return False
        expected = self._sign_message(msg)
        return hmac.compare_digest(expected, msg.signature)

    # ------------------------------------------------------------------
    # Encryption
    # ------------------------------------------------------------------

    def _encrypt_payload(self, plaintext: bytes, nonce: bytes) -> bytes:
        """AES-128-CCM encrypt.  Falls back to plaintext if package unavailable."""
        if not _AESCCM_AVAILABLE:
            return plaintext
        cipher = AESCCM(self._aes_key)
        return cipher.encrypt(nonce[:7], plaintext, None)

    def _decrypt_payload(self, ciphertext: bytes, nonce: bytes) -> bytes:
        """AES-128-CCM decrypt.  Falls back to identity if package unavailable."""
        if not _AESCCM_AVAILABLE:
            return ciphertext
        cipher = AESCCM(self._aes_key)
        return cipher.decrypt(nonce[:7], ciphertext, None)

    # ------------------------------------------------------------------
    # Replay prevention
    # ------------------------------------------------------------------

    def _is_replay(self, msg: MeshMessage) -> bool:
        """
        Return True if the message should be dropped:
          - Timestamp more than _FUTURE_SKEW_S in the future (clock manipulation)
          - Timestamp more than _REPLAY_WINDOW_S in the past (replay / delayed)
          - Nonce already seen within the replay window
        """
        now = time.time()
        msg_time_s = msg.timestamp_ms / 1000.0

        if msg_time_s > now + _FUTURE_SKEW_S:
            logger.warning("[BLE] Dropped: future timestamp from %s", msg.node_id)
            return True

        if now - msg_time_s > _REPLAY_WINDOW_S:
            logger.warning("[BLE] Dropped: stale message (%ds old) from %s",
                           int(now - msg_time_s), msg.node_id)
            return True

        mid = msg.message_id
        with self._seen_lock:
            if mid in self._seen_nonces:
                logger.warning("[BLE] Replay detected: %s", mid)
                return True
            self._seen_nonces[mid] = now
            # Prune cache to _MAX_SEEN_CACHE entries
            if len(self._seen_nonces) > _MAX_SEEN_CACHE:
                cutoff = now - _REPLAY_WINDOW_S
                self._seen_nonces = {
                    k: v for k, v in self._seen_nonces.items() if v > cutoff
                }
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish_hazard(
        self,
        hazard_type: str,
        lat: float,
        lon: float,
        severity: str,
        confidence: float,
    ) -> MeshMessage:
        """
        Build and sign a HAZARD_ALERT message.

        Args:
            hazard_type: String key, e.g. "POTHOLE" (matched against protocol JSON).
            lat, lon:    GPS coordinates (5 dp precision — ~1m).
            severity:    "CRITICAL" | "HIGH" | "MEDIUM".
            confidence:  Model confidence [0.0, 1.0].

        Returns:
            Signed MeshMessage ready for BLE advertising.
        """
        # Look up hazard type code from protocol config
        hazard_types: dict = _PROTOCOL.get("hazard_types", {})
        type_code = next(
            (k for k, v in hazard_types.items() if v == hazard_type), "0"
        )
        msg = MeshMessage(
            message_type=1,  # HAZARD_ALERT
            node_id=self.node_id,
            timestamp_ms=int(time.time() * 1000),
            payload={
                "timestamp": int(time.time() * 1000),
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "hazard_type": type_code,
                "severity": severity,
                "confidence": round(confidence, 3),
            },
            ttl=_DEFAULT_TTL,
        )
        msg.signature = self._sign_message(msg)
        logger.info(
            "[BLE] HAZARD_ALERT: type=%s lat=%.4f lon=%.4f sev=%s conf=%.2f",
            hazard_type, lat, lon, severity, confidence,
        )
        return msg

    def publish_heartbeat(self, battery_level: float) -> MeshMessage:
        """
        Build and sign a MESH_HEARTBEAT message.  TTL=1 (no forwarding).

        Args:
            battery_level: Normalised battery level [0.0, 1.0].
        """
        msg = MeshMessage(
            message_type=3,  # MESH_HEARTBEAT
            node_id=self.node_id,
            timestamp_ms=int(time.time() * 1000),
            payload={
                "node_id": self.node_id,
                "battery_level": round(battery_level, 2),
                "mesh_hops": 0,
            },
            ttl=1,  # Heartbeats are local-only; do not propagate
        )
        msg.signature = self._sign_message(msg)
        return msg

    def receive(self, msg: MeshMessage) -> bool:
        """
        Process an inbound mesh message.

        Validation pipeline:
          1. TTL > 0
          2. Not a replay (timestamp + nonce check)
          3. HMAC-SHA256 signature valid

        On success, decrements TTL, increments hop_count, dispatches to handlers.

        Returns:
            True if the message was accepted and dispatched; False otherwise.
        """
        if msg.ttl <= 0:
            logger.debug("[BLE] Dropped: TTL exhausted from %s", msg.node_id)
            return False

        if self._is_replay(msg):
            return False

        if not self._verify_signature(msg):
            logger.warning("[BLE] Signature verification FAILED for msg from %s", msg.node_id)
            return False

        msg.ttl -= 1
        msg.hop_count += 1

        with self._handler_lock:
            handlers = list(self._handlers)

        for handler in handlers:
            try:
                handler(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("[BLE] Handler error: %s", exc)

        logger.debug(
            "[BLE] Received: type=%d from=%s ttl=%d hops=%d",
            msg.message_type, msg.node_id, msg.ttl, msg.hop_count,
        )
        return True

    def add_handler(self, handler: Callable[[MeshMessage], None]) -> None:
        """Register a callback to be invoked on each validated inbound message."""
        with self._handler_lock:
            self._handlers.append(handler)

    def remove_handler(self, handler: Callable[[MeshMessage], None]) -> None:
        """Deregister a previously added handler."""
        with self._handler_lock:
            self._handlers = [h for h in self._handlers if h is not handler]
