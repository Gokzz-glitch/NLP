"""
tests/test_acoustic_ui.py

Unit tests for agents/acoustic_ui.py covering:
  - AlertPriority enum ordering
  - Alert / announce enqueueing without error
  - announce_near_miss routing
  - Worker thread is daemon and alive
  - join() completes without deadlock
  - Template lookup (English and Tamil keys present)
  - override_text takes precedence over template
  - Unknown template falls back to key as text (no crash)
  - Language fallback to English when no Tamil voice found
  - Latency tracking populated after alert
  - get_mean_latency_ms returns float after first alert, None before
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import threading
import pytest
from unittest.mock import MagicMock, patch

from agents.acoustic_ui import AcousticUI, AlertPriority, _TAMIL_TEMPLATES, _ENGLISH_TEMPLATES


@pytest.fixture
def ui():
    """AcousticUI with mocked pyttsx3 (no audio output)."""
    mock_engine = MagicMock()
    mock_engine.getProperty.return_value = []   # No voices → English fallback
    with patch("pyttsx3.init", return_value=mock_engine):
        mgr = AcousticUI(language="en")
    yield mgr
    mgr.stop()


# ---------------------------------------------------------------------------
# AlertPriority ordering
# ---------------------------------------------------------------------------

class TestAlertPriority:

    def test_critical_lower_than_high(self):
        assert AlertPriority.CRITICAL < AlertPriority.HIGH

    def test_high_lower_than_medium(self):
        assert AlertPriority.HIGH < AlertPriority.MEDIUM

    def test_medium_lower_than_low(self):
        assert AlertPriority.MEDIUM < AlertPriority.LOW

    def test_critical_is_zero(self):
        assert int(AlertPriority.CRITICAL) == 0


# ---------------------------------------------------------------------------
# Enqueueing
# ---------------------------------------------------------------------------

class TestEnqueue:

    def test_alert_no_error(self, ui):
        ui.alert("POTHOLE", AlertPriority.MEDIUM)

    def test_announce_no_error(self, ui):
        ui.announce("Test message", AlertPriority.HIGH)

    def test_announce_near_miss_critical(self, ui):
        ui.announce_near_miss("CRITICAL")

    def test_announce_near_miss_high(self, ui):
        ui.announce_near_miss("HIGH")

    def test_announce_near_miss_medium(self, ui):
        ui.announce_near_miss("MEDIUM")


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class TestWorkerThread:

    def test_worker_is_daemon(self, ui):
        assert ui._worker_thread.daemon

    def test_worker_is_alive(self, ui):
        assert ui._worker_thread.is_alive()

    def test_join_completes_without_deadlock(self, ui):
        ui.announce("quick test")
        done = threading.Event()

        def do_join():
            ui.join()
            done.set()

        t = threading.Thread(target=do_join, daemon=True)
        t.start()
        t.join(timeout=5.0)
        assert done.is_set(), "join() deadlocked"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TestTemplates:

    def test_english_templates_not_empty(self):
        for key in ["CRITICAL_NEAR_MISS", "HIGH_SWERVE", "SPEED_TRAP", "POTHOLE"]:
            assert key in _ENGLISH_TEMPLATES
            assert len(_ENGLISH_TEMPLATES[key]) > 0

    def test_tamil_templates_not_empty(self):
        for key in ["CRITICAL_NEAR_MISS", "HIGH_SWERVE", "SPEED_TRAP", "POTHOLE"]:
            assert key in _TAMIL_TEMPLATES
            assert len(_TAMIL_TEMPLATES[key]) > 0

    def test_override_text_takes_precedence(self, ui):
        ui.alert("POTHOLE", override_text="Custom override")
        ui.join()
        ui._engine.say.assert_called_with("Custom override")

    def test_unknown_template_uses_key_as_text(self, ui):
        """Unknown key must not raise — key itself is used as the speech text."""
        ui.alert("COMPLETELY_UNKNOWN_KEY_XYZ", AlertPriority.MEDIUM)
        ui.join()
        ui._engine.say.assert_called_with("COMPLETELY_UNKNOWN_KEY_XYZ")


# ---------------------------------------------------------------------------
# Language selection
# ---------------------------------------------------------------------------

class TestLanguage:

    def test_english_language_kept(self):
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            ui = AcousticUI(language="en")
        assert ui.language == "en"
        ui.stop()

    def test_tamil_falls_back_to_english_when_no_voice(self):
        """No Tamil voice available → language must be 'en' after init."""
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            ui = AcousticUI(language="ta")
        assert ui.language == "en"
        ui.stop()


# ---------------------------------------------------------------------------
# Latency tracking
# ---------------------------------------------------------------------------

class TestLatency:

    def test_latency_list_populated_after_alert(self, ui):
        ui.announce("test")
        ui.join()
        assert len(ui._latencies_ms) > 0

    def test_mean_latency_returns_float_after_alert(self, ui):
        ui.announce("test")
        ui.join()
        lat = ui.get_mean_latency_ms()
        assert lat is not None
        assert isinstance(lat, float)

    def test_mean_latency_none_before_any_alert(self):
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []
        with patch("pyttsx3.init", return_value=mock_engine):
            ui = AcousticUI(language="en")
        assert ui.get_mean_latency_ms() is None
        ui.stop()
