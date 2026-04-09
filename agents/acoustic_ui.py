"""
agents/acoustic_ui.py
SmartSalai Edge-Sentinel — P4: Acoustic Voice UI

Bhashini-compatible TTS interface for driver hazard alerts.

Language: Tamil (primary), English (fallback).
Target latency: <100ms from event to engine.say() call.

ERR-002: Bhashini offline TTS model package not yet available.
         Falls back to pyttsx3 with Tamil voice selection if installed.
         Install a Tamil system voice (e.g. espeak-ng Tamil) to activate.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from enum import IntEnum
from typing import List, Optional

logger = logging.getLogger("edge_sentinel.acoustic_ui")

try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except ImportError:
    _PYTTSX3_AVAILABLE = False
    logger.warning("[P4] pyttsx3 not installed — TTS will be silent.")


# ---------------------------------------------------------------------------
# Priority levels
# ---------------------------------------------------------------------------

class AlertPriority(IntEnum):
    CRITICAL = 0   # Imminent collision / rollover — preempts everything
    HIGH     = 1   # Aggressive manoeuvre / unlawful speed trap
    MEDIUM   = 2   # Informational hazard alert
    LOW      = 3   # Navigation / ambient info


# ---------------------------------------------------------------------------
# Alert templates
# ---------------------------------------------------------------------------

_TAMIL_TEMPLATES: dict = {
    "CRITICAL_NEAR_MISS": "எச்சரிக்கை! மிகவும் ஆபத்தான நிலை!",
    "HIGH_SWERVE":        "எச்சரிக்கை! தீவிர திசை மாற்றம் கண்டறியப்பட்டது!",
    "SPEED_TRAP":         "வேக கட்டுப்பாடு கேமரா கண்டறியப்பட்டது!",
    "POTHOLE":            "முன்னால் குழி உள்ளது!",
    "LEGAL_CHALLENGE":    "சட்ட சவாலுக்கான ஆவணம் உருவாக்கப்பட்டது!",
}

_ENGLISH_TEMPLATES: dict = {
    "CRITICAL_NEAR_MISS": "CRITICAL: Near-miss detected. Immediate caution required.",
    "HIGH_SWERVE":        "Warning: Aggressive swerve detected.",
    "SPEED_TRAP":         "Speed enforcement camera detected ahead.",
    "POTHOLE":            "Caution: Pothole detected ahead.",
    "LEGAL_CHALLENGE":    "Legal challenge document generated.",
}


# ---------------------------------------------------------------------------
# AcousticUI
# ---------------------------------------------------------------------------

class AcousticUI:
    """
    Edge-native priority-queue voice alert system for two-wheeler safety.

    Priority queue guarantees CRITICAL alerts preempt in-progress lower-priority
    speech on the next sentence boundary (pyttsx3 runAndWait is blocking per item).

    Latency tracking:
      Time from enqueue() to engine.say() call is measured and logged.
      SLA target: <100ms.  Violations are logged at WARNING level.

    Thread safety:
      Worker thread is a daemon; safe to call alert()/announce() from any thread.
    """

    _SLA_MS: float = 100.0  # Latency SLA in milliseconds

    def __init__(self, language: str = "ta", speech_rate: int = 175) -> None:
        """
        Args:
            language:    ISO 639-1 code. 'ta' = Tamil, 'en' = English.
            speech_rate: Words per minute.  175 wpm ≈ urgent but clear speech.
        """
        self.language = language
        self._speech_rate = speech_rate
        # PriorityQueue entries: (int_priority, enqueue_perf_counter, text)
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._engine = None
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._latencies_ms: List[float] = []  # Rolling window of last 100 latencies

        self._init_engine()
        self._start_worker()

    # ------------------------------------------------------------------
    # Engine initialisation
    # ------------------------------------------------------------------

    def _init_engine(self) -> None:
        if not _PYTTSX3_AVAILABLE:
            logger.warning("[P4] pyttsx3 unavailable — all alerts will be silent.")
            return
        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self._speech_rate)

            if self.language == "ta":
                voices = self._engine.getProperty("voices") or []
                tamil_voice = next(
                    (
                        v for v in voices
                        if "tamil" in v.name.lower()
                        or "ta" in getattr(v, "languages", [])
                    ),
                    None,
                )
                if tamil_voice:
                    self._engine.setProperty("voice", tamil_voice.id)
                    logger.info("[P4] Tamil voice selected: %s", tamil_voice.name)
                else:
                    logger.warning(
                        "[P4] No Tamil voice found — falling back to English. "
                        "Install espeak-ng Tamil or Bhashini TTS to resolve ERR-002."
                    )
                    self.language = "en"
        except Exception as exc:  # noqa: BLE001
            logger.error("[P4] TTS engine init failed: %s", exc)
            self._engine = None

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _start_worker(self) -> None:
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="acoustic_ui_worker"
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        while self._running:
            try:
                priority, enqueue_t, text = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            latency_ms = (time.perf_counter() - enqueue_t) * 1000.0
            self._latencies_ms.append(latency_ms)
            if len(self._latencies_ms) > 100:
                self._latencies_ms = self._latencies_ms[-100:]

            if latency_ms > self._SLA_MS:
                logger.warning(
                    "[P4] TTS latency %.1f ms exceeds %.0f ms SLA (priority=%d)",
                    latency_ms, self._SLA_MS, priority,
                )

            try:
                if self._engine is not None:
                    self._engine.say(text)
                    self._engine.runAndWait()
                else:
                    logger.info("[P4] (SILENT) %s", text)
            except Exception as exc:  # noqa: BLE001
                logger.error("[P4] TTS engine error: %s", exc)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def alert(
        self,
        template_key: str,
        priority: AlertPriority = AlertPriority.MEDIUM,
        override_text: Optional[str] = None,
    ) -> None:
        """
        Enqueue a voice alert using a template key.

        Args:
            template_key:  Key from _TAMIL_TEMPLATES / _ENGLISH_TEMPLATES.
            priority:      Alert priority (lower number = higher urgency).
            override_text: If set, overrides template lookup.
        """
        if override_text:
            text = override_text
        elif self.language == "ta" and template_key in _TAMIL_TEMPLATES:
            text = _TAMIL_TEMPLATES[template_key]
        else:
            text = _ENGLISH_TEMPLATES.get(template_key, template_key)

        self._queue.put((int(priority), time.perf_counter(), text))
        logger.debug("[P4] Alert queued: %s priority=%s", template_key, priority.name)

    def announce(self, text: str, priority: AlertPriority = AlertPriority.MEDIUM) -> None:
        """Enqueue an arbitrary text announcement."""
        self._queue.put((int(priority), time.perf_counter(), text))

    def announce_near_miss(self, severity: str) -> None:
        """
        Route a NearMissSeverity value to the correct template and priority.

        Args:
            severity: "CRITICAL" | "HIGH" | "MEDIUM" (from NearMissSeverity.value).
        """
        if severity == "CRITICAL":
            self.alert("CRITICAL_NEAR_MISS", AlertPriority.CRITICAL)
        elif severity == "HIGH":
            self.alert("HIGH_SWERVE", AlertPriority.HIGH)
        else:
            self.alert("HIGH_SWERVE", AlertPriority.MEDIUM)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_mean_latency_ms(self) -> Optional[float]:
        """Return mean dispatch latency in ms over the last 100 alerts (None if empty)."""
        if not self._latencies_ms:
            return None
        return sum(self._latencies_ms) / len(self._latencies_ms)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def join(self, timeout: Optional[float] = None) -> None:
        """Block until all queued alerts have been spoken."""
        self._queue.join()

    def stop(self) -> None:
        """Drain the queue and stop the worker thread."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
