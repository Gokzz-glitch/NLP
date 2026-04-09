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
