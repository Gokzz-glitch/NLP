"""
<<<<<<< HEAD
Agent Bus - JSON-RPC Central Switchboard for Edge-Sentinel Personas

Coordinates multi-agent communication between:
  - Persona 1: V2X / BLE Mesh (hazard broadcast)
  - Persona 2: Legal RAG (violation analysis & legal guidance)
  - Persona 3: Vision (YOLOv8) + IMU (TCN sensor fusion)
  - Persona 4: Voice (Bhashini TTS)
  - Persona 5: Dashboard / DevOps

Thread-safe pub-sub with event history for edge debugging.

Author: SmartSalai Team
License: AGPL3.0
"""

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict
from typing import Callable, Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("edge_sentinel.agent_bus")
logger.setLevel(logging.INFO)



# ─────────────────────────────────────────────────────────────────────────
# CORE EVENT TYPES (Persona Integration Map)
# ─────────────────────────────────────────────────────────────────────────

EVENT_TYPES = {
    # Persona 1: V2X / BLE Mesh Broker
    "V2X_HAZARD_BROADCAST": "Broadcast road hazard to nearby vehicles",
    "BLE_MESH_PEER_JOINED": "New peer joined BLE swarm",
    "BLE_MESH_PEER_LEFT": "Peer left BLE swarm",
    # Persona 2: Legal RAG + DriveLegal Engine
    "LEGAL_VIOLATION_DETECTED": "Violation detected → legal sections retrieved",
    "SECTION208_AUDIT_DRAFTED": "Section 208 RTO challenge auto-drafted",
    "LEGAL_ALERT_GENERATED": "Legal + penalty + appeal info ready for TTS/HUD",
    # Persona 3: Vision (YOLO) + Sensor Fusion (TCN)
    "YOLO_DETECTION": "YOLOv8 object detection result",
    "VISION_HAZARD_DETECTED": "Vision pipeline flagged a hazard candidate",
    "IMU_NEAR_MISS": "TCN near-miss detection (accel + gyro fusion)",
    "NEAR_MISS_DETECTED": "Sensor fusion near-miss event for downstream actions",
    "POTHOLE_HAZARD": "Pothole/road defect detected",
    "HELMET_MISSING": "Helmet absence detected by vision",
    "SIGN_DETECTED": "Traffic sign detected (speed camera, yield, etc.)",
    "SENTINEL_FUSION_ALERT": "Vision+IMU consensus hazard alert for UI and voice",
    "FAST_CRITICAL_ALERT": "Low-latency critical alert lane that bypasses non-essential processing",
    "ALERT_RECEIVED_ACK": "Frontend acknowledgement emitted when acoustic warning fires",
    "REGULATORY_CONFLICT": "Legal/RAG conflict result for current driving context",
    # Persona 4: Voice + Audio Alerts (TTS)
    "TTS_ALERT_QUEUE": "Audio alert ready to play (Tanglish TTS)",
    "VOICE_ALERT_REQUEST": "Request to announce a voice alert immediately",
}

# ─────────────────────────────────────────────────────────────────────────
# Minimal MVP Agent Bus (in-memory pub/sub)
# ─────────────────────────────────────────────────────────────────────────
import threading
from collections import defaultdict
from typing import Callable, Dict, List, Any

class AgentBus:
    def __init__(self):
        self.subscribers: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)
        self.lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable[[Any], None]):
        with self.lock:
            self.subscribers[event_type].append(callback)

    def publish(self, event_type: str, data: Any):
        with self.lock:
            callbacks = list(self.subscribers[event_type])
        for cb in callbacks:
            cb(data)

# Global bus instance for agents to import
agent_bus = AgentBus()

# Example usage (for integration test)
if __name__ == "__main__":
    def on_violation(event):
        print(f"Received violation: {event}")
    agent_bus.subscribe("500m_violation", on_violation)
    agent_bus.publish("500m_violation", {"speed_camera_frame": 100, "speed_limit_frame": 50})


class AgentBus:
    """
    Central JSON-RPC event bus for Edge-Sentinel.
    
    Provides:
    - Thread-safe pub-sub with callbacks
    - Event history for debugging
    - Payload validation (basic)
    - Per-event metrics (latency, subscriber count)
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AgentBus, cls).__new__(cls)
                cls._instance._init_bus()
        return cls._instance
    
    def _init_bus(self):
        """Initialize bus state"""
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Dict] = []
        self._metrics: Dict[str, Dict] = defaultdict(lambda: {
            "emit_count": 0,
            "subscriber_count": 0,
            "last_emitted_at": 0,
            "total_latency_ms": 0,
        })
        self.max_history = 500  # Keep last N events for debugging
        # [REMEDIATION #5]: Managed ThreadPool for sync callbacks [CWE-400]
        self._executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="BusWorker")
    
    def shutdown(self):
        """Cleanly shutdown the thread pool"""
        self._executor.shutdown(wait=False)
    
    def subscribe(self, event_type: str, callback: Callable[[Any], None], name: str = None):
        """
        Register callback for event type.
        
        Args:
            event_type: One of EVENT_TYPES keys
            callback: Function(payload) to execute on event
            name: Optional name for this subscription (for debugging)
        """
        if event_type not in EVENT_TYPES and not event_type.startswith("CUSTOM_"):
            logger.warning(f"BUS_SUBSCRIBE: Unknown event type '{event_type}'")
        
        with self._lock:
            self._subscribers[event_type].append(callback)
            self._metrics[event_type]["subscriber_count"] = len(self._subscribers[event_type])
            logger.info(f"BUS_SUBSCRIBE: {event_type} ({name or 'anonymous'})")
    
    def emit(self, event_type: str, payload: Any):
        """
        Dispatch event to all subscribers.
        
        Args:
            event_type: One of EVENT_TYPES keys
            payload: Event data (dict or object with .to_dict())
        """
        emit_time = time.time()
        
        with self._lock:
            callbacks = self._subscribers.get(event_type, []).copy()
            self._metrics[event_type]["emit_count"] += 1
            self._metrics[event_type]["last_emitted_at"] = emit_time
        
        # Log event
        payload_str = json.dumps(payload, default=str) if isinstance(payload, dict) else str(payload)
        logger.info(f"BUS_EMIT: {event_type} | {len(callbacks)} subscribers")
        
        # Record in history
        with self._lock:
            self._history.append({
                "event_type": event_type,
                "timestamp": emit_time,
                "payload_type": type(payload).__name__,
                "subscriber_count": len(callbacks),
            })
            if len(self._history) > self.max_history:
                self._history = self._history[-self.max_history:]
        
        # 4. Execute callbacks asynchronously to prevent deadlocks [CWE-662]
        for callback in callbacks:
            try:
                # Wrap in task so slow agents don't block the emitter
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(self._safe_callback(callback, payload, event_type))
                else:
                    # [REMEDIATION #5]: Offload to managed pool instead of raw Thread().start()
                    self._executor.submit(self._safe_sync_callback, callback, payload, event_type)
            except Exception as e:
                logger.error(f"BUS_DISPATCH_ERROR: {event_type} | {e}")

    async def _safe_callback(self, callback, payload, event_type):
        """Async wrapper for metric tracking"""
        # [REMEDIATION #27]: Use monotonic perf_counter for latency [CWE-114]
        start = time.perf_counter()
        try:
            await callback(payload)
            latency = (time.perf_counter() - start) * 1000
            with self._lock:
                self._metrics[event_type]["total_latency_ms"] += latency
            if latency > 200:
                logger.warning(f"BUS_SLOW_ASYNC: {event_type} took {latency:.1f}ms")
        except Exception as e:
            logger.error(f"BUS_CALLBACK_ERROR: {event_type} | {e}")

    def _safe_sync_callback(self, callback, payload, event_type):
        """Sync wrapper for threadpool metrics"""
        # [REMEDIATION #27]: Use monotonic perf_counter for latency [CWE-114]
        start = time.perf_counter()
        try:
            callback(payload)
            latency = (time.perf_counter() - start) * 1000
            with self._lock:
                self._metrics[event_type]["total_latency_ms"] += latency
        except Exception as e:
            logger.error(f"BUS_SYNC_ERROR: {event_type} | {e}")
    
    def get_event_types(self) -> List[str]:
        """Return all registered event types"""
        with self._lock:
            return sorted(list(self._subscribers.keys()))
    
    def get_subscribers_for(self, event_type: str) -> int:
        """Get subscriber count for an event type"""
        with self._lock:
            return len(self._subscribers.get(event_type, []))
    
    def get_history(self, event_type: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """
        Get event history (for debugging).
        
        Args:
            event_type: Filter to specific event, or None for all
            limit: Number of events to return
        
        Returns:
            List of event records with timestamp, type, subscriber count
        """
        with self._lock:
            history = self._history if not event_type else [
                h for h in self._history if h["event_type"] == event_type
            ]
            return history[-limit:]
    
    def get_metrics(self) -> Dict[str, Dict]:
        """Get per-event metrics (emit count, latency, subscriber count)"""
        with self._lock:
            return dict(self._metrics)
    
    def clear_history(self):
        """Clear event history (use for testing)"""
        with self._lock:
            self._history.clear()


# Global singleton instance
bus = AgentBus()


# ─────────────────────────────────────────────────────────────────────────
# HELPER: Create standard legal violation event
# ─────────────────────────────────────────────────────────────────────────

def emit_legal_violation(violation_type: str, severity: str, location: Dict, context: Dict):
    """
    Convenience function: detect violation → emit to bus.
    
    Chain: Persona 3 (vision/IMU) → DriveLegal (DL-2) → RAG (Persona 2) → TTS (Persona 4)
    """
    bus.emit("LEGAL_VIOLATION_DETECTED", {
        "violation_type": violation_type,
        "severity": severity,
        "location": location,
        "context": context,
        "timestamp": time.time(),
    })


# ─────────────────────────────────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    
    # Test 1: Basic pub-sub
    def hazard_handler(data):
        print(f"  ✓ Hazard handler: {data.get('type')}")
    
    def legal_handler(data):
        print(f"  ✓ Legal handler: {data.get('violation_type')} | Severity: {data.get('severity')}")
    
    bus.subscribe("YOLO_DETECTION", hazard_handler, "hazard_detector")
    bus.subscribe("LEGAL_VIOLATION_DETECTED", legal_handler, "legal_rag")
    
    print("✅ Test 1: Emit YOLO detection")
    bus.emit("YOLO_DETECTION", {"type": "POTHOLE", "lat": 13.0827, "lng": 80.2707})
    
    print("\n✅ Test 2: Emit legal violation (helmet)")
    emit_legal_violation(
        violation_type="HELMET_MISSING",
        severity="CRITICAL",
        location={"zone": "SCHOOL_ZONE"},
        context={"source": "YOLO", "confidence": 0.94}
    )
    
    print("\n✅ Test 3: Bus metrics")
    metrics = bus.get_metrics()
    for event_type, stats in metrics.items():
        print(f"  {event_type}: {stats['emit_count']} emits, {stats['subscriber_count']} subscribers")
    
    print("\n✅ Test 4: Event history")
    history = bus.get_history(limit=5)
    for h in history:
        print(f"  {h['event_type']} @ {h['timestamp']:.1f} ({h['subscriber_count']} subs)")
    
    print("\n✅ Agent Bus smoke test PASSED")
=======
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
        # Send sentinel first so the dispatch loop drains all pending messages
        # before exiting, then signal the loop to stop after it sees the sentinel.
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._running = False
        if self._worker:
            self._worker.join(timeout=drain_timeout_s)

    def subscribe(self, topic: str, handler: HandlerFn) -> None:
        self._registry.subscribe(topic, handler)

    def unsubscribe(self, topic: str, handler: HandlerFn) -> None:
        self._registry.unsubscribe(topic, handler)

    def publish(self, topic: str, params: Dict[str, Any], message_id: Optional[str] = None) -> str:
        msg = BusMessage(topic=topic, params=params, message_id=message_id or str(uuid.uuid4()))
        try:
            self._queue.put_nowait(msg)
        except queue.Full:
            logger.warning(f"[AgentBus] Queue full — dropping message on topic={topic!r}")
            return msg.message_id
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
        while True:
            try:
                msg = self._queue.get(timeout=0.5)
            except queue.Empty:
                if not self._running:
                    # No more messages and bus is stopped — exit cleanly
                    break
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
                logger.error(f"[AgentBus] Handler error topic={msg.topic!r} handler={getattr(handler, '__name__', repr(handler))!r}: {exc}", exc_info=True)


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
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e
