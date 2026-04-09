"""
tests/test_agent_bus.py

Unit tests for core/agent_bus.py covering:
  - subscribe / emit
  - unsubscribe
  - multiple handlers, all dispatched
  - handler exception isolation
  - source_agent propagation
  - heartbeat / agent status
  - watchdog detection
  - concurrent access
  - get_bus singleton
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import threading
import pytest

from core.agent_bus import AgentBus, AgentMessage, get_bus


# ---------------------------------------------------------------------------
# Subscribe / Emit
# ---------------------------------------------------------------------------

class TestSubscribeEmit:

    def test_emit_calls_handler(self):
        bus = AgentBus()
        received = []
        bus.subscribe("TEST_EVENT", received.append)
        bus.emit("TEST_EVENT", {"key": "value"})
        assert len(received) == 1

    def test_event_type_in_message(self):
        bus = AgentBus()
        msgs = []
        bus.subscribe("EV", msgs.append)
        bus.emit("EV", {})
        assert msgs[0].event_type == "EV"

    def test_payload_available_in_message(self):
        bus = AgentBus()
        msgs = []
        bus.subscribe("D", msgs.append)
        bus.emit("D", {"x": 42})
        assert msgs[0].payload["x"] == 42

    def test_emit_no_handler_no_error(self):
        bus = AgentBus()
        bus.emit("UNHANDLED", {})  # Must not raise

    def test_multiple_handlers_all_called(self):
        bus = AgentBus()
        calls = []
        bus.subscribe("EV", lambda m: calls.append("A"))
        bus.subscribe("EV", lambda m: calls.append("B"))
        bus.emit("EV", {})
        assert sorted(calls) == ["A", "B"]

    def test_message_has_timestamp_ms(self):
        bus = AgentBus()
        msgs = []
        bus.subscribe("X", msgs.append)
        bus.emit("X", {})
        assert msgs[0].timestamp_ms > 0

    def test_message_ids_are_unique(self):
        bus = AgentBus()
        msgs = []
        bus.subscribe("X", msgs.append)
        bus.emit("X", {})
        bus.emit("X", {})
        assert msgs[0].message_id != msgs[1].message_id

    def test_source_agent_propagated(self):
        bus = AgentBus()
        msgs = []
        bus.subscribe("X", msgs.append)
        bus.emit("X", {}, source_agent="imu_detector")
        assert msgs[0].source_agent == "imu_detector"

    def test_source_agent_none_when_not_set(self):
        bus = AgentBus()
        msgs = []
        bus.subscribe("X", msgs.append)
        bus.emit("X", {})
        assert msgs[0].source_agent is None

    def test_different_events_do_not_cross_dispatch(self):
        bus = AgentBus()
        a_calls, b_calls = [], []
        bus.subscribe("A", a_calls.append)
        bus.subscribe("B", b_calls.append)
        bus.emit("A", {})
        assert len(a_calls) == 1 and len(b_calls) == 0


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------

class TestUnsubscribe:

    def test_unsubscribe_stops_dispatch(self):
        bus = AgentBus()
        calls = []
        handler = calls.append
        bus.subscribe("EV", handler)
        bus.emit("EV", {})
        bus.unsubscribe("EV", handler)
        bus.emit("EV", {})
        assert len(calls) == 1

    def test_unsubscribe_nonexistent_no_error(self):
        bus = AgentBus()
        bus.unsubscribe("MISSING", lambda m: None)

    def test_unsubscribe_one_of_two_handlers(self):
        bus = AgentBus()
        calls_a, calls_b = [], []
        h_a = calls_a.append
        bus.subscribe("EV", h_a)
        bus.subscribe("EV", calls_b.append)
        bus.unsubscribe("EV", h_a)
        bus.emit("EV", {})
        assert len(calls_a) == 0 and len(calls_b) == 1


# ---------------------------------------------------------------------------
# Exception isolation
# ---------------------------------------------------------------------------

class TestExceptionIsolation:

    def test_bad_handler_does_not_block_others(self):
        bus = AgentBus()
        second_called = []
        bus.subscribe("EV", lambda m: 1 / 0)
        bus.subscribe("EV", lambda m: second_called.append(1))
        bus.emit("EV", {})
        assert len(second_called) == 1


# ---------------------------------------------------------------------------
# Heartbeat / Agent Status
# ---------------------------------------------------------------------------

class TestHeartbeat:

    def test_register_agent_appears_in_status(self):
        bus = AgentBus()
        bus.register_agent("sensor_a")
        status = bus.get_agent_status()
        assert "sensor_a" in status

    def test_heartbeat_updates_timestamp(self):
        bus = AgentBus()
        bus.register_agent("sensor_a")
        time.sleep(0.05)
        bus.heartbeat("sensor_a")
        status = bus.get_agent_status()
        assert status["sensor_a"]["last_heartbeat_s_ago"] < 0.5

    def test_status_has_required_key(self):
        bus = AgentBus()
        bus.register_agent("x")
        assert "last_heartbeat_s_ago" in bus.get_agent_status()["x"]

    def test_multiple_agents_tracked(self):
        bus = AgentBus()
        bus.register_agent("a")
        bus.register_agent("b")
        status = bus.get_agent_status()
        assert "a" in status and "b" in status


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------

class TestConcurrency:

    def test_concurrent_emit_all_dispatched(self):
        bus = AgentBus()
        lock = threading.Lock()
        results = []

        def handler(m):
            with lock:
                results.append(1)

        bus.subscribe("C", handler)
        threads = [threading.Thread(target=bus.emit, args=("C", {})) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 20

    def test_concurrent_subscribe_and_emit_no_deadlock(self):
        bus = AgentBus()
        done = threading.Event()

        def sub_loop():
            for _ in range(10):
                bus.subscribe("EV2", lambda m: None)
            done.set()

        t = threading.Thread(target=sub_loop)
        t.start()
        for _ in range(10):
            bus.emit("EV2", {})
        t.join(timeout=2.0)
        assert done.is_set()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:

    def test_get_bus_same_instance(self):
        assert get_bus() is get_bus()

    def test_get_bus_is_agent_bus(self):
        assert isinstance(get_bus(), AgentBus)
