"""
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
        self._running = False

    def start(self) -> None:
        """Start (or restart) the bus — idempotent and test-safe."""
        with self._lock:
            if not self._running:
                # Refresh executor in case stop() was called previously
                try:
                    self._executor.shutdown(wait=False)
                except Exception:
                    pass
                self._executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="BusWorker")
                self._running = True

    def stop(self) -> None:
        """Shut down the bus cleanly — flushes in-flight callbacks."""
        with self._lock:
            self._running = False
        self._executor.shutdown(wait=True)

    def shutdown(self):
        """Cleanly shutdown the thread pool (alias for stop())."""
        self.stop()
    
    def subscribe(self, event_type: str, callback: Callable[[Any], None], name: str = None):
        """
        Register callback for event type.

        Supports wildcard ``"*"`` to receive every published event as a
        :class:`BusMessage`.  The callback receives a ``BusMessage`` when the
        event was dispatched via :meth:`publish`; it receives the raw payload
        when dispatched via :meth:`emit`.

        Args:
            event_type: One of EVENT_TYPES keys, a dot-notation topic, or ``"*"``
            callback: Function(payload) to execute on event
            name: Optional name for this subscription (for debugging)
        """
        # Wildcard and dot-notation topics are intentional — suppress the noise.
        is_known = event_type in EVENT_TYPES or event_type.startswith("CUSTOM_")
        is_wildcard = event_type == "*"
        has_dot = "." in event_type

        if not is_known and not is_wildcard and not has_dot:
            logger.debug(f"BUS_SUBSCRIBE: Unknown event type '{event_type}'")

        with self._lock:
            self._subscribers[event_type].append(callback)
            self._metrics[event_type]["subscriber_count"] = len(self._subscribers[event_type])
            logger.info(f"BUS_SUBSCRIBE: {event_type} ({name or 'anonymous'})")

    def emit(self, event_type: str, payload: Any):
        """
        Dispatch event to all subscribers with raw payload.

        Args:
            event_type: One of EVENT_TYPES keys
            payload: Event data (dict or object with .to_dict())
        """
        self._dispatch(event_type, payload)

    def _dispatch(self, event_type: str, payload: Any, envelope: "BusMessage" = None):
        """Internal dispatch — delivers to specific-topic and wildcard subscribers.

        When *envelope* is provided, wildcard ``"*"`` subscribers receive the
        full :class:`BusMessage`; specific-topic subscribers also receive it
        (instead of the raw dict) so that ``msg.topic`` / ``msg.params`` are
        available.  Without an envelope the raw payload is forwarded.
        """
        emit_time = time.time()

        with self._lock:
            topic_callbacks = self._subscribers.get(event_type, []).copy()
            wildcard_callbacks = self._subscribers.get("*", []).copy()
            self._metrics[event_type]["emit_count"] += 1
            self._metrics[event_type]["last_emitted_at"] = emit_time

        logger.info(
            f"BUS_EMIT: {event_type} | {len(topic_callbacks)} topic + "
            f"{len(wildcard_callbacks)} wildcard subscribers"
        )

        # Record in history
        with self._lock:
            self._history.append({
                "event_type": event_type,
                "timestamp": emit_time,
                "payload_type": type(payload).__name__,
                "subscriber_count": len(topic_callbacks) + len(wildcard_callbacks),
            })
            if len(self._history) > self.max_history:
                self._history = self._history[-self.max_history:]

        # Topic-specific subscribers get the envelope (if provided) or raw payload.
        topic_arg = envelope if envelope is not None else payload
        self._run_callbacks(topic_callbacks, topic_arg, event_type)

        # Wildcard subscribers always get the envelope (wrapping if needed).
        if wildcard_callbacks:
            wild_msg = envelope if envelope is not None else BusMessage(
                topic=event_type, params=payload if isinstance(payload, dict) else {}
            )
            self._run_callbacks(wildcard_callbacks, wild_msg, event_type)

    def _run_callbacks(self, callbacks, arg, event_type: str):
        """Dispatch a list of callbacks safely, handling both sync and async."""
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    # [CWE-662]: Don't blindly call create_task — it requires a
                    # running loop in the current thread.  Use run_coroutine_threadsafe
                    # when a loop is running, otherwise schedule via the executor.
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._safe_callback(callback, arg, event_type))
                    except RuntimeError:
                        # No running event loop in this thread; schedule it.
                        self._executor.submit(
                            asyncio.run, self._safe_callback(callback, arg, event_type)
                        )
                else:
                    self._executor.submit(self._safe_sync_callback, callback, arg, event_type)
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

    def publish(self, topic: str, params: Any) -> None:
        """Publish a :class:`BusMessage` envelope to all subscribers.

        Subscribers receive the full ``BusMessage`` (with ``.topic`` and
        ``.params`` attributes) rather than the raw dict.  Wildcard ``"*"``
        subscribers also receive the envelope.

        This is the preferred API for newer agents. Legacy code should use
        :meth:`emit` for raw payload dispatch.
        """
        envelope = BusMessage(
            topic=topic,
            params=params if isinstance(params, dict) else {},
        )
        self._dispatch(topic, params, envelope=envelope)


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


# ─────────────────────────────────────────────────────────────────────────
# COMPATIBILITY LAYER — Topics, BusMessage, publish alias, get_bus / reset_bus
# Imported by newer agents generated against the JSON-RPC 2.0 bus spec.
# ─────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field as _field
import uuid as _uuid


class Topics:
    """Central registry of all well-known bus topics (used by newer agents)."""
    IMU_NEAR_MISS       = "IMU_NEAR_MISS"
    VISION_DETECTION    = "YOLO_DETECTION"
    LEGAL_CHALLENGE     = "SECTION208_AUDIT_DRAFTED"
    BLE_HAZARD          = "V2X_HAZARD_BROADCAST"
    BLE_HEARTBEAT       = "SYSTEM_HEARTBEAT"
    TTS_ANNOUNCE        = "TTS_ALERT_QUEUE"
    RAG_QUERY           = "LEGAL_VIOLATION_DETECTED"
    RAG_RESPONSE        = "LEGAL_ALERT_GENERATED"
    BLACKSPOT_ALERT     = "POTHOLE_HAZARD"
    IRAD_EMIT           = "NEAR_MISS_DETECTED"
    ORCHESTRATOR_STATUS = "CUSTOM_ORCHESTRATOR_STATUS"


@dataclass
class BusMessage:
    """Lightweight envelope used by newer agents subscribing via attach_bus()."""
    topic: str
    params: Dict
    message_id: str = _field(default_factory=lambda: str(_uuid.uuid4()))
    timestamp_epoch_ms: int = _field(default_factory=lambda: int(time.time() * 1000))


def get_bus() -> "AgentBus":
    """Return the global singleton AgentBus instance."""
    return bus


def reset_bus() -> None:
    """Reset the singleton bus — clears all subscribers and history.

    Intended for use in test harnesses to ensure clean state between tests.
    """
    with AgentBus._lock:
        AgentBus._instance._subscribers.clear()
        AgentBus._instance._history.clear()
        AgentBus._instance._metrics.clear()
