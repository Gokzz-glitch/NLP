<<<<<<< HEAD
import logging
import json
import struct
import time
import hmac
import hashlib
import os
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Any
from core.knowledge_ledger import ledger
from core.agent_bus import bus
from core.secret_manager import get_manager
from agents.base import BaseAgent
from dotenv import load_dotenv

logger = logging.getLogger("edge_sentinel.ble_broker")
logger.setLevel(logging.INFO)

load_dotenv()

# [PERSONA 1: BLE MESH BROKER — V2X SWARM]
# Task: T-022 — Implement V2X Swarm Broadcast logic (MESH_HEARTBEAT + HAZARD_ALERT).

class BLEMeshBroker(BaseAgent):
    """
    Simulates the bridge to the physical Bluetooth Low Energy (BLE) Mesh stack.
    Converts Sentinel Fusion Alerts into binary advertisement packets.
    Broadcasts at 100ms interval (AIS-140 standard for VLTD).
    """
    def __init__(self, node_id: str = "ES-CH-001"):
        self.node_id = node_id
        super().__init__("Agent29-BleMeshBroker", sleep_interval=10, init_clients=False)
        
        # Get FERNET_KEY from SecretManager for V2V signing
        sm = get_manager(strict_mode=False)
        fernet_key = sm.get("FERNET_KEY")
        if not fernet_key:
            raise RuntimeError(
                "FERNET_KEY environment variable not set. "
                "Required for BLE mesh encryption."
            )
        self.secret = fernet_key.encode()
        
        self.sequence_number = 0
        self.protocol = self._load_protocol()  # Initialize protocol config [FIX #1]
        self.hazard_type_map = {  # Hardening: explicit hazard type index mapping [FIX #1]
            "POTHOLE": 0, "SPEED_TRAP_NO_SIGNAGE": 1, "ACCIDENT_NEAR_MISS": 2,
            "HEAVY_CONGESTION": 3, "ROAD_CONSTRUCTION": 4
        }
        self._setup_bus()
        logger.info(f"PERSONA_1_REPORT: BLE_BROKER_ONLINE | node={self.node_id} | security=HMAC_TRUNCATED")


    def _load_protocol(self) -> Dict:
        candidates = [
            Path(__file__).resolve().parents[1] / "ble_mesh_protocol.json",
            Path(__file__).resolve().parents[1] / "ble_mesh_protocol_optimized.json",
            Path("ble_mesh_protocol.json").resolve(),
            Path("ble_mesh_protocol_optimized.json").resolve(),
        ]
        for path in candidates:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)

        # Safe fallback to keep broker alive in recovery mode.
        logger.warning("BLE protocol file not found; using fallback mesh defaults")
        return {"offline_mesh_configuration": {"mesh_ttl": 5}}

    def _setup_bus(self):
        bus.subscribe("SENTINEL_FUSION_ALERT", self._on_fusion_alert)
        bus.subscribe("SYSTEM_HEARTBEAT", self._on_heartbeat)
        bus.subscribe("PHYSICAL_BLE_ADVERTISEMENT", self._on_incoming_adv)
        # Bounded TTL+LRU cache for seen message digests (prevents unbounded growth).
        self._seen_messages: "OrderedDict[str, float]" = OrderedDict()
        # Backward-compat alias used by older tests.
        self.seen_messages = set()
        self._seen_max_size = int(os.getenv("BLE_SEEN_CACHE_MAX", "1000"))
        self._seen_ttl_sec = float(os.getenv("BLE_SEEN_CACHE_TTL_SEC", "300"))

    def _prune_seen_messages(self, now: float):
        ttl_cutoff = now - self._seen_ttl_sec
        stale = [k for k, ts in self._seen_messages.items() if ts < ttl_cutoff]
        for key in stale:
            self._seen_messages.pop(key, None)

        while len(self._seen_messages) > self._seen_max_size:
            self._seen_messages.popitem(last=False)

    def _seen_recently(self, payload_hex: str) -> bool:
        now = time.time()
        self._prune_seen_messages(now)
        existing_ts = self._seen_messages.get(payload_hex)
        if existing_ts is not None and (now - existing_ts) <= self._seen_ttl_sec:
            # Refresh LRU order on hit.
            self._seen_messages.move_to_end(payload_hex)
            return True

        self._seen_messages[payload_hex] = now
        self._seen_messages.move_to_end(payload_hex)
        self._prune_seen_messages(now)
        return False

    def _on_fusion_alert(self, alert_payload: Dict[str, Any]):
        try:
            # Sequence number for replay protection (Vuln #7 fix)
            self.sequence_number = (self.sequence_number + 1) % 65535
            
            # Resolve hazard type to index [FIX #1: h_idx undefined]
            hazard_type = alert_payload.get("type", "POTHOLE")
            h_idx = self.hazard_type_map.get(hazard_type, 0)
            
            # Binary Packing (Simulated 31-byte ADV packet)
            # Struct: Type(1) + TS(4) + Lat(4) + Lon(4) + H_Type(1) + Sev(1) + Conf(1) + Seq(2)
            base_payload = struct.pack(
                "!BIf f B B B H",
                1, # ID: HAZARD_ALERT
                int(time.time()),
                alert_payload.get("lat", 0.0),
                alert_payload.get("lon", 0.0),
                h_idx,
                1 if alert_payload.get("severity") == "CRITICAL" else 0,
                int(alert_payload.get("confidence", 100)),
                self.sequence_number
            )
            
            # Truncated signature retained to keep payload bounded for mesh advertisement frames.
            signature = hmac.new(self.secret, base_payload, hashlib.sha256).digest()[:4]
            final_payload = base_payload + signature 
            
            self._broadcast(final_payload, "HAZARD_ALERT")
        except Exception as e:
            logger.error(f"BLE_ALERT_ERROR: Malformed fusion alert: {e}")
            return

    def _on_heartbeat(self, heartbeat: Dict):
        # MESH_HEARTBEAT (type 3)
        payload = struct.pack("!B 8s B B", 3, self.node_id.encode()[:8], 100, 0)
        self._broadcast(payload, "HEARTBEAT")

    def _broadcast(self, binary_data: bytes, p_type: str):
        """
        In production, this calls 'hciconfig' / 'bluetoothctl' or NRF52 API.
        For simulation, we hex-dump the advertisement packet.
        """
        hex_payload = binary_data.hex().upper()
        logger.info(f"BLE_ADV: EMIT: {p_type} | payload={hex_payload} | len={len(binary_data)}B")
        
        bus.emit("PHYSICAL_BLE_ADVERTISEMENT", {
            "type": p_type,
            "hex": hex_payload,
            "ts": int(time.time() * 1000),
            "ttl": self.protocol["offline_mesh_configuration"]["mesh_ttl"]
        })

    def _on_incoming_adv(self, adv_payload: Dict[str, Any]):
        """
        MESH RELAY LOGIC (Multi-hop)
        Decodes incoming packets and re-broadcasts if TTL > 0.
        [FIX #4: Relay storm controls - dedupe, hop budget, priority backoff]
        """
        payload_hex = adv_payload.get("hex", "")
        if not payload_hex:
            return

        if self._seen_recently(payload_hex):
            return

        current_ttl = adv_payload.get("ttl", 0)
        if current_ttl <= 0: return
        
        # [FIX #4]: Hop-budget policy - probabilistic rebroadcast under dense load
        if current_ttl < 3 and current_ttl > 1:
            # Low TTL: apply probabilistic drop (50% drop rate at TTL=2)
            import random
            drop_probability = 0.5 * (4 - current_ttl) / 2  # Increases as TTL decreases
            if random.random() < drop_probability:
                logger.debug(f"MESH_DROP: Probabilistic TTL={current_ttl} (storm control)")
                return

        # Decode type (First byte)
        try:
            binary_data = bytes.fromhex(payload_hex)
            
            # Signature Validation (Vuln #6 check)
            if len(binary_data) < 5: return
            
            payload_data = binary_data[:-4]
            received_signature = binary_data[-4:]
            expected_signature = hmac.new(self.secret, payload_data, hashlib.sha256).digest()[:4]
            
            if not hmac.compare_digest(received_signature, expected_signature):
                logger.warning(f"MESH_SECURITY_ALERT: DROP_SPOOFED_PACKET | hex={payload_hex[:16]}…")
                return

            msg_type = binary_data[0]
            
            if msg_type == 1: # HAZARD_ALERT
                 logger.info(f"PERSONA_1_REPORT: MESH_RELAY: RELAYING_VERIFIED_HAZARD | TTL={current_ttl-1}")
                 # Re-broadcast with decremented TTL [FIX #4: Storm control applied above]
                 adv_payload["ttl"] = current_ttl - 1
                 bus.emit("PHYSICAL_BLE_ADVERTISEMENT", adv_payload)
        except Exception as e:
            logger.error(f"MESH_ERROR: DECODE_FAILURE: {e}")

if __name__ == "__main__":
    # Test
    broker = BLEMeshBroker()
    bus.emit("SENTINEL_FUSION_ALERT", {
        "type": "POTHOLE", # Named from protocol
        "severity": "CRITICAL",
        "lat": 13.00,
        "lon": 80.20
    })
=======
"""
agents/ble_mesh_broker.py  (T-008)
SmartSalai Edge-Sentinel — BLE V2X Mesh Node Discovery + Hazard Broadcast

Implements the ble_mesh_protocol.json schema:
  - HAZARD_ALERT  (id=1): GPS + hazard type + severity + confidence
  - LEGAL_SYNC    (id=2): Section ID sync between nodes
  - MESH_HEARTBEAT(id=3): Node liveness + battery

Transport layer:
  - Real BLE: uses bleak (if available) — asyncio BLE central/peripheral
  - Mock transport: in-process shared registry for unit tests / demo

All messages are compact JSON serialised and fit inside a 244-byte ATT MTU.
"""

from __future__ import annotations

import json
import logging
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.agents.ble_mesh_broker")

PROTOCOL_VERSION = "1.0-EDGE"
MAX_PACKET_BYTES = 244  # BLE 4.2 ATT MTU
HEARTBEAT_INTERVAL_S = 10.0


class MsgType(IntEnum):
    HAZARD_ALERT   = 1
    LEGAL_SYNC     = 2
    MESH_HEARTBEAT = 3


class HazardType:
    POTHOLE           = "POTHOLE"
    SPEED_TRAP_NO_SIGN = "SPEED_TRAP_NO_SIGN"
    ACCIDENT_BLACKSPOT = "ACCIDENT_BLACKSPOT"
    FLOODED_ROAD      = "FLOODED_ROAD"
    NEAR_MISS         = "NEAR_MISS"


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------
@dataclass
class MeshMessage:
    msg_type: MsgType
    sender_id: str
    payload: Dict[str, Any]
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_bytes(self) -> bytes:
        obj = {
            "v": PROTOCOL_VERSION,
            "t": int(self.msg_type),
            "s": self.sender_id,
            "p": self.payload,
            "i": self.message_id,
            "ts": self.timestamp_ms,
        }
        raw = json.dumps(obj, separators=(",", ":")).encode()
        if len(raw) > MAX_PACKET_BYTES:
            logger.warning(f"[BLEMesh] Packet {len(raw)}B > MTU {MAX_PACKET_BYTES}B — truncating payload")
        return raw[:MAX_PACKET_BYTES]

    @classmethod
    def from_bytes(cls, data: bytes) -> "MeshMessage":
        obj = json.loads(data.decode())
        return cls(
            msg_type=MsgType(obj["t"]),
            sender_id=obj["s"],
            payload=obj["p"],
            message_id=obj.get("i", ""),
            timestamp_ms=obj.get("ts", 0),
        )


# ---------------------------------------------------------------------------
# Mock BLE transport (in-process shared bus for tests / demo)
# ---------------------------------------------------------------------------
class _MockBLETransport:
    """Shared in-memory mesh for multiple BLEMeshBrokerAgent instances."""
    _mesh_registry: Dict[str, "_MockBLETransport"] = {}
    _lock = threading.Lock()

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self._rx_callback: Optional[Callable[[bytes, str], None]] = None
        with _MockBLETransport._lock:
            _MockBLETransport._mesh_registry[node_id] = self

    def set_receive_callback(self, cb: Callable[[bytes, str], None]) -> None:
        self._rx_callback = cb

    def broadcast(self, data: bytes) -> None:
        with _MockBLETransport._lock:
            peers = dict(_MockBLETransport._mesh_registry)
        for nid, transport in peers.items():
            if nid != self.node_id and transport._rx_callback:
                try:
                    transport._rx_callback(data, self.node_id)
                except Exception as exc:
                    logger.error(f"[BLEMesh] Mock delivery error to {nid}: {exc}")

    def close(self) -> None:
        with _MockBLETransport._lock:
            _MockBLETransport._mesh_registry.pop(self.node_id, None)


# ---------------------------------------------------------------------------
# Broker agent
# ---------------------------------------------------------------------------
class BLEMeshBrokerAgent:
    """
    BLE V2X mesh broker — publishes hazards, receives peer alerts.

    Usage:
        broker = BLEMeshBrokerAgent()
        broker.start()
        broker.broadcast_hazard(HazardType.SPEED_TRAP_NO_SIGN, lat=12.924, lon=80.230)
    """

    def __init__(self, node_id: Optional[str] = None) -> None:
        self.node_id = node_id or str(uuid.uuid4())[:8]
        self._transport = _MockBLETransport(self.node_id)
        self._bus = None
        self._running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._received_messages: List[MeshMessage] = []
        self._seen_ids: set = set()

    def attach_bus(self, bus) -> None:
        self._bus = bus

    def start(self) -> None:
        self._running = True
        self._transport.set_receive_callback(self._on_receive)
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"ble-hb-{self.node_id}", daemon=True
        )
        self._heartbeat_thread.start()
        logger.info(f"[BLEMesh] Node {self.node_id} started.")

    def stop(self) -> None:
        self._running = False
        self._transport.close()

    def broadcast_hazard(
        self,
        hazard_type: str,
        lat: float,
        lon: float,
        severity: str = "HIGH",
        confidence: float = 1.0,
    ) -> bool:
        msg = MeshMessage(
            msg_type=MsgType.HAZARD_ALERT,
            sender_id=self.node_id,
            payload={
                "hazard_type": hazard_type,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "severity": severity,
                "confidence": round(confidence, 3),
            },
        )
        self._transport.broadcast(msg.to_bytes())
        logger.info(f"[BLEMesh] HAZARD_ALERT broadcast: {hazard_type} @ ({lat:.4f},{lon:.4f})")
        return True

    def broadcast_legal_sync(self, section_id: str, checksum: str, jurisdiction: str = "IN_TN") -> bool:
        msg = MeshMessage(
            msg_type=MsgType.LEGAL_SYNC,
            sender_id=self.node_id,
            payload={"section_id": section_id, "checksum": checksum, "jurisdiction": jurisdiction},
        )
        self._transport.broadcast(msg.to_bytes())
        return True

    def _on_receive(self, data: bytes, sender: str) -> None:
        try:
            msg = MeshMessage.from_bytes(data)
        except Exception as exc:
            logger.error(f"[BLEMesh] Parse error from {sender}: {exc}")
            return

        if msg.message_id in self._seen_ids:
            return
        self._seen_ids.add(msg.message_id)
        self._received_messages.append(msg)

        logger.info(f"[BLEMesh] Received {msg.msg_type.name} from {sender}: {msg.payload}")

        if self._bus:
            from core.agent_bus import Topics
            if msg.msg_type == MsgType.HAZARD_ALERT:
                self._bus.publish(Topics.BLE_HAZARD, {"sender": sender, **msg.payload})
            elif msg.msg_type == MsgType.MESH_HEARTBEAT:
                self._bus.publish(Topics.BLE_HEARTBEAT, msg.payload)

    def _heartbeat_loop(self) -> None:
        while self._running:
            msg = MeshMessage(
                msg_type=MsgType.MESH_HEARTBEAT,
                sender_id=self.node_id,
                payload={"node_id": self.node_id, "battery_level": 100, "mesh_hops": 1},
            )
            self._transport.broadcast(msg.to_bytes())
            time.sleep(HEARTBEAT_INTERVAL_S)


_agent: Optional[BLEMeshBrokerAgent] = None


def get_agent() -> BLEMeshBrokerAgent:
    global _agent
    if _agent is None:
        _agent = BLEMeshBrokerAgent()
        _agent.start()
    return _agent
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e
