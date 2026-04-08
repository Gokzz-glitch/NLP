"""
agents/acoustic_ui.py  (T-012)
SmartSalai Edge-Sentinel — Bhashini/IndicTrans2 Tanglish TTS Voice UI

Handles Tamil-English (Tanglish) voice output for edge-device alerts.

Backend priority:
  1. Bhashini offline API (if BHASHINI_API_KEY set or local model present)
  2. pyttsx3 with Tamil voice (if available)
  3. pyttsx3 English fallback
  4. Silent mode (logs only) — for testing / headless environments

Tanglish phrase map covers the 10 most critical safety alerts used in demo.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.agents.acoustic_ui")

# ---------------------------------------------------------------------------
# Tanglish phrase map (Tamil transliteration with English key terms)
# ---------------------------------------------------------------------------
TANGLISH_PHRASES: Dict[str, str] = {
    "near_miss_critical":
        "Kavanam! Payanam abaayamaagirukku. Neenga safe-aa slow pannunga!",
    "near_miss_high":
        "Uyarndha speed — slow pannunga please.",
    "speed_trap_no_sign":
        "Speed camera irukku, sign illai. Section 208 challenge possible.",
    "blackspot_alert":
        "Kavanam! Ippodhu accident blackspot la irukkeengal. Slow pannunga!",
    "ble_hazard_received":
        "Arugil irukkira vehicle hazard alert anuppeechchu. Careful!",
    "legal_challenge_generated":
        "Legal notice ready. Speed camera without signage — challenge filed.",
    "irad_submitted":
        "Accident data MoRTH-kku submit aagirukku.",
    "system_ready":
        "SmartSalai Edge Sentinel ready. Nallavagai poonga!",
    "battery_low":
        "Battery kuraivaagirukku. Charge pannunga.",
    "gps_lost":
        "GPS signal illai. Location tracking nilachchu.",
}


# ---------------------------------------------------------------------------
# TTS backend
# ---------------------------------------------------------------------------
def _build_tts_engine():
    """Returns (kind, engine) — tries Bhashini → pyttsx3 → silent."""
    bhashini_key = os.environ.get("BHASHINI_API_KEY", "")
    if bhashini_key:
        try:
            from bhashini_tts import BhashiniTTS  # type: ignore
            engine = BhashiniTTS(api_key=bhashini_key, language="ta", script="tanglish")
            return ("bhashini", engine)
        except Exception:
            pass

    try:
        import pyttsx3
        engine = pyttsx3.init()
        # Try to set Tamil voice
        for voice in engine.getProperty("voices"):
            if "tamil" in voice.name.lower() or "ta" in voice.id.lower():
                engine.setProperty("voice", voice.id)
                logger.info(f"[AcousticUI] pyttsx3 Tamil voice: {voice.name}")
                return ("pyttsx3_ta", engine)
        engine.setProperty("rate", 160)
        return ("pyttsx3_en", engine)
    except Exception:
        pass

    return ("silent", None)


class AcousticUIAgent:
    """
    Tanglish TTS voice UI agent.

    Usage:
        agent = AcousticUIAgent()
        agent.start()
        agent.speak("near_miss_critical")
        agent.speak_raw("Slow down!")
    """

    def __init__(self, silent: bool = False) -> None:
        self._silent = silent
        self._tts_kind: str = "silent"
        self._tts_engine = None
        self._bus = None
        self._queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._running = False

    def attach_bus(self, bus) -> None:
        self._bus = bus
        from core.agent_bus import Topics
        bus.subscribe(Topics.TTS_ANNOUNCE, self._on_tts_announce)

    def _on_tts_announce(self, msg) -> None:
        params = msg.params
        text = params.get("text", "")
        phrase_key = params.get("phrase_key", "")
        if phrase_key:
            self.speak(phrase_key)
        elif text:
            self.speak_raw(text, lang=params.get("lang", "en"))

    def start(self) -> None:
        if not self._silent:
            self._tts_kind, self._tts_engine = _build_tts_engine()
            logger.info(f"[AcousticUI] Backend: {self._tts_kind}")
        else:
            self._tts_kind = "silent"
        self._running = True
        self._worker = threading.Thread(target=self._speak_loop, name="acoustic-ui", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._running = False

    def speak(self, phrase_key: str) -> None:
        """Enqueue a Tanglish phrase by key."""
        text = TANGLISH_PHRASES.get(phrase_key, phrase_key)
        self._enqueue(text, phrase_key)

    def speak_raw(self, text: str, lang: str = "en") -> None:
        """Enqueue arbitrary text."""
        self._enqueue(text, None)

    def _enqueue(self, text: str, key: Optional[str]) -> None:
        with self._lock:
            self._queue.append({"text": text, "key": key, "ts": time.time()})

    def _speak_loop(self) -> None:
        while self._running:
            item = None
            with self._lock:
                if self._queue:
                    item = self._queue.pop(0)
            if item:
                self._do_speak(item["text"], item["key"])
            time.sleep(0.05)

    def _do_speak(self, text: str, key: Optional[str]) -> None:
        logger.info(f"[AcousticUI] TTS [{self._tts_kind}] key={key!r}: {text!r}")
        if self._tts_kind == "silent":
            return
        try:
            if self._tts_kind == "bhashini":
                self._tts_engine.synthesize(text)
            elif self._tts_kind in ("pyttsx3_ta", "pyttsx3_en"):
                self._tts_engine.say(text)
                self._tts_engine.runAndWait()
        except Exception as exc:
            logger.error(f"[AcousticUI] TTS error: {exc}")

    def get_phrase(self, key: str) -> str:
        return TANGLISH_PHRASES.get(key, key)


_agent: Optional[AcousticUIAgent] = None


def get_agent(silent: bool = False) -> AcousticUIAgent:
    global _agent
    if _agent is None:
        _agent = AcousticUIAgent(silent=silent)
        _agent.start()
    return _agent
