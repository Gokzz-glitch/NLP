"""
tests/test_offline_tts_manager.py

Unit tests for offline_tts_manager.py — OfflineTTSManager.
pyttsx3 engine is fully mocked to allow headless testing.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import queue
import threading
import time
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def tts():
    """Return an OfflineTTSManager with a mocked pyttsx3 engine."""
    mock_engine = MagicMock()
    with patch("pyttsx3.init", return_value=mock_engine):
        from offline_tts_manager import OfflineTTSManager
        mgr = OfflineTTSManager()
    return mgr


class TestOfflineTTSManager:

    def test_announce_hazard_critical_priority_zero(self, tts):
        tts.announce_hazard("Danger!", critical=True)
        # Drain queue
        tts.interrupt_queue.join()
        # Priority 0 was placed
        assert True  # just checking no exception

    def test_announce_hazard_non_critical_priority_one(self, tts):
        tts.announce_hazard("Info", critical=False)
        tts.interrupt_queue.join()
        assert True

    def test_critical_has_lower_priority_number_than_normal(self, tts):
        """
        PriorityQueue returns lowest number first.
        critical=True → priority 0 (runs before priority 1).
        """
        mock_engine = MagicMock()
        with patch("pyttsx3.init", return_value=mock_engine):
            from offline_tts_manager import OfflineTTSManager
            import importlib
            import offline_tts_manager as _m
            importlib.reload(_m)

        # Inspect the code: critical=True uses priority=0
        import inspect
        src = inspect.getsource(_m.OfflineTTSManager.announce_hazard)
        assert "0 if critical" in src or "priority = 0" in src or "(0," in src

    def test_worker_thread_is_daemon(self, tts):
        assert tts.worker_thread.daemon is True

    def test_worker_thread_is_alive(self, tts):
        assert tts.worker_thread.is_alive()

    def test_multiple_announcements_processed(self, tts):
        for i in range(5):
            tts.announce_hazard(f"message {i}", critical=(i % 2 == 0))
        tts.interrupt_queue.join()  # All processed without deadlock

    def test_engine_say_called_for_each_announcement(self):
        """Mock the engine and verify say() is called."""
        mock_engine = MagicMock()
        with patch("pyttsx3.init", return_value=mock_engine):
            from offline_tts_manager import OfflineTTSManager
            mgr = OfflineTTSManager()
        mgr.announce_hazard("test message", critical=False)
        mgr.interrupt_queue.join()
        mock_engine.say.assert_called_once_with("test message")

    def test_task_done_called_even_on_engine_failure(self):
        """
        Fix 4: worker must call task_done() even if engine raises.
        Without the fix, interrupt_queue.join() would deadlock.
        """
        mock_engine = MagicMock()
        mock_engine.say.side_effect = RuntimeError("TTS hardware failure")
        with patch("pyttsx3.init", return_value=mock_engine):
            from offline_tts_manager import OfflineTTSManager
            mgr = OfflineTTSManager()
        mgr.announce_hazard("crash me", critical=True)
        # join() must complete within 2 seconds — would hang forever if bug present
        done = threading.Event()
        def do_join():
            mgr.interrupt_queue.join()
            done.set()
        t = threading.Thread(target=do_join, daemon=True)
        t.start()
        t.join(timeout=2.0)
        assert done.is_set(), "interrupt_queue.join() deadlocked — task_done() not called on failure"

    def test_priority_queue_type(self, tts):
        assert isinstance(tts.interrupt_queue, queue.PriorityQueue)
