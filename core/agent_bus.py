"""
core/agent_bus.py  (T-013)
SmartSalai Edge-Sentinel — JSON-RPC 2.0 Inter-Agent Message Bus

Topic-based publish/subscribe event bus connecting all 5 persona-agents.
Thread-safe, fully offline, zero external dependencies.

JSON-RPC 2.0 envelope:
  { "jsonrpc": "2.0", "method": "<topic>", "params": {...}, "id": "<uuid4>" }
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.core.agent_bus")

JSONRPC_VERSION = "2.0"
HandlerFn = Callable[["BusMessage"], None]


class Topics:
    """Central registry of all well-known bus topics."""
    IMU_NEAR_MISS       = "imu.near_miss"
    VISION_DETECTION    = "vision.detection"
    LEGAL_CHALLENGE     = "legal.challenge"
    BLE_HAZARD          = "ble.hazard_broadcast"
    BLE_HEARTBEAT       = "ble.mesh_heartbeat"
    TTS_ANNOUNCE        = "tts.announce"
    RAG_QUERY           = "rag.query"
    RAG_RESPONSE        = "rag.response"
    BLACKSPOT_ALERT     = "geo.blackspot_alert"
    IRAD_EMIT           = "telemetry.irad_emit"
    ORCHESTRATOR_STATUS = "orchestrator.status"


@dataclass
class BusMessage:
    topic: str
    params: Dict[str, Any]
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_jsonrpc(self) -> str:
        return json.dumps({
            "jsonrpc": JSONRPC_VERSION,
            "method": self.topic,
            "params": self.params,
            "id": self.message_id,
        })

    @classmethod
    def from_jsonrpc(cls, raw: str) -> "BusMessage":
        obj = json.loads(raw)
        return cls(
            topic=obj["method"],
            params=obj.get("params", {}),
            message_id=obj.get("id", str(uuid.uuid4())),
        )


class _SubscriptionRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: Dict[str, List[HandlerFn]] = {}
        self._wildcards: List[HandlerFn] = []

    def subscribe(self, topic: str, handler: HandlerFn) -> None:
        with self._lock:
            if topic == "*":
                if handler not in self._wildcards:
                    self._wildcards.append(handler)
            else:
                self._handlers.setdefault(topic, [])
                if handler not in self._handlers[topic]:
                    self._handlers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: HandlerFn) -> None:
        with self._lock:
            if topic == "*":
                self._wildcards = [h for h in self._wildcards if h is not handler]
            elif topic in self._handlers:
                self._handlers[topic] = [h for h in self._handlers[topic] if h is not handler]

    def get_handlers(self, topic: str) -> List[HandlerFn]:
        with self._lock:
            return list(self._handlers.get(topic, [])) + list(self._wildcards)

    def subscriber_count(self, topic: str) -> int:
        return len(self.get_handlers(topic))


class AgentBus:
    """
    JSON-RPC 2.0 inter-agent pub/sub message bus.

    Usage (producer):
        bus = AgentBus(); bus.start()
        bus.publish("imu.near_miss", {"severity": "CRITICAL"})

    Usage (consumer):
        bus.subscribe("imu.near_miss", lambda msg: print(msg.params))
    """

    def __init__(self, queue_maxsize: int = 256) -> None:
        self._registry = _SubscriptionRegistry()
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._stats = {"published": 0, "dispatched": 0, "errors": 0}
        self._stats_lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._dispatch_loop, name="agent-bus-worker", daemon=True)
        self._worker.start()

    def stop(self, drain_timeout_s: float = 2.0) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker:
            self._worker.join(timeout=drain_timeout_s)

    def subscribe(self, topic: str, handler: HandlerFn) -> None:
        self._registry.subscribe(topic, handler)

    def unsubscribe(self, topic: str, handler: HandlerFn) -> None:
        self._registry.unsubscribe(topic, handler)

    def publish(self, topic: str, params: Dict[str, Any], message_id: Optional[str] = None) -> str:
        msg = BusMessage(topic=topic, params=params, message_id=message_id or str(uuid.uuid4()))
        self._queue.put_nowait(msg)
        with self._stats_lock:
            self._stats["published"] += 1
        return msg.message_id

    def publish_sync(self, topic: str, params: Dict[str, Any], timeout_s: float = 0.5) -> str:
        msg = BusMessage(topic=topic, params=params)
        self._queue.put(msg, timeout=timeout_s)
        with self._stats_lock:
            self._stats["published"] += 1
        return msg.message_id

    def stats(self) -> Dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    def subscriber_count(self, topic: str) -> int:
        return self._registry.subscriber_count(topic)

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                msg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if msg is None:
                break
            self._dispatch(msg)
            self._queue.task_done()

    def _dispatch(self, msg: BusMessage) -> None:
        for handler in self._registry.get_handlers(msg.topic):
            try:
                handler(msg)
                with self._stats_lock:
                    self._stats["dispatched"] += 1
            except Exception as exc:
                with self._stats_lock:
                    self._stats["errors"] += 1
                logger.error(f"[AgentBus] Handler error topic={msg.topic!r} handler={handler.__name__!r}: {exc}", exc_info=True)


# Module-level singleton
_bus: Optional[AgentBus] = None


def get_bus() -> AgentBus:
    global _bus
    if _bus is None:
        _bus = AgentBus()
        _bus.start()
    return _bus


def reset_bus() -> None:
    global _bus
    if _bus is not None:
        _bus.stop()
        _bus = None
