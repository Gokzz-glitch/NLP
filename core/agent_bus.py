"""
core/agent_bus.py
SmartSalai Edge-Sentinel — P1: JSON-RPC Inter-Agent Event Bus

Thread-safe publish/subscribe bus for inter-agent communication.
All agents register, emit events, and subscribe to events via this bus.
A background watchdog detects agents that have stopped sending heartbeats.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.core.agent_bus")


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass
class AgentMessage:
    """Immutable event envelope passed between agents."""
    event_type: str
    payload: Any
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    source_agent: Optional[str] = None


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------

class AgentBus:
    """
    Thread-safe publish/subscribe event bus.

    Usage:
        bus = AgentBus()
        bus.start()
        bus.register_agent("imu_detector")

        bus.subscribe("NEAR_MISS_DETECTED", handle_near_miss)
        bus.emit("NEAR_MISS_DETECTED", event, source_agent="imu_detector")

        # In acquisition loop:
        bus.heartbeat("imu_detector")
    """

    #: How long (in multiples of heartbeat_interval) before an agent is
    #: declared stale by the watchdog.
    STALE_MULTIPLIER: int = 3

    def __init__(self, heartbeat_interval_s: float = 5.0) -> None:
        self._heartbeat_interval = heartbeat_interval_s
        # event_type → list of handler callables
        self._subscribers: Dict[str, List[Callable[[AgentMessage], None]]] = {}
        self._sub_lock = threading.RLock()

        # agent_id → last heartbeat timestamp
        self._agent_registry: Dict[str, float] = {}
        self._reg_lock = threading.RLock()

        self._watchdog_thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the watchdog background thread."""
        self._running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="agent_bus_watchdog"
        )
        self._watchdog_thread.start()
        logger.info("[AgentBus] Started. Heartbeat interval: %.1fs", self._heartbeat_interval)

    def stop(self) -> None:
        """Stop the watchdog thread."""
        self._running = False
        logger.info("[AgentBus] Stopped.")

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: Callable[[AgentMessage], None]) -> None:
        """Register *handler* to be called whenever *event_type* is emitted."""
        with self._sub_lock:
            self._subscribers.setdefault(event_type, []).append(handler)
        logger.debug("[AgentBus] subscribe: %s", event_type)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Remove *handler* from *event_type*.  No-op if not registered."""
        with self._sub_lock:
            if event_type in self._subscribers:
                self._subscribers[event_type] = [
                    h for h in self._subscribers[event_type] if h is not handler
                ]

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        payload: Any,
        source_agent: Optional[str] = None,
    ) -> None:
        """
        Emit an event to all subscribers.  Handler exceptions are caught and
        logged so that one bad handler never blocks the others.
        """
        msg = AgentMessage(
            event_type=event_type, payload=payload, source_agent=source_agent
        )
        with self._sub_lock:
            handlers = list(self._subscribers.get(event_type, []))

        for handler in handlers:
            try:
                handler(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("[AgentBus] Handler error for %s: %s", event_type, exc)

    # ------------------------------------------------------------------
    # Heartbeat / Watchdog
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str) -> None:
        """Register an agent with the watchdog.  Call once at startup."""
        with self._reg_lock:
            self._agent_registry[agent_id] = time.time()
        logger.info("[AgentBus] Agent registered: %s", agent_id)

    def heartbeat(self, agent_id: str) -> None:
        """Record a heartbeat for *agent_id*.  Call periodically from each agent."""
        with self._reg_lock:
            self._agent_registry[agent_id] = time.time()

    def get_agent_status(self) -> Dict[str, Any]:
        """Return a dict of {agent_id: {"last_heartbeat_s_ago": float}}."""
        now = time.time()
        with self._reg_lock:
            return {
                aid: {"last_heartbeat_s_ago": round(now - ts, 1)}
                for aid, ts in self._agent_registry.items()
            }

    def _watchdog_loop(self) -> None:
        stale_threshold = self._heartbeat_interval * self.STALE_MULTIPLIER
        while self._running:
            time.sleep(self._heartbeat_interval)
            now = time.time()
            with self._reg_lock:
                stale = [
                    aid
                    for aid, ts in self._agent_registry.items()
                    if now - ts > stale_threshold
                ]
            for aid in stale:
                logger.warning("[AgentBus] WATCHDOG: Agent '%s' missed %d heartbeats — stale!",
                               aid, self.STALE_MULTIPLIER)
                self.emit("AGENT_STALE", {"agent_id": aid})


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_bus: Optional[AgentBus] = None


def get_bus() -> AgentBus:
    """Return (and lazily create) the process-level default AgentBus."""
    global _default_bus
    if _default_bus is None:
        _default_bus = AgentBus()
    return _default_bus
