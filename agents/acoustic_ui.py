<<<<<<< HEAD
import logging
import time
import threading
import queue
import json
import pyttsx3
import winsound
from itertools import count
from pathlib import Path
from typing import Dict, Any
from core.agent_bus import bus
from agents.driver_companion_agent import driver_companion

# [PERSONA 4: ACOUSTIC UI - VOICE BRIDGE]
# Task: T-021 — Bhashini-to-Bus bridge for Tanglish alerts (Upgraded with Generative Memory).

logger = logging.getLogger("edge_sentinel.acoustic_ui")
logger.setLevel(logging.INFO)

class AcousticUIAgent:
    """
    Consumes Sentinel Fusion Alerts and triggers local audio playback.
    Uses Driver Companion Agent to generate friendly but direct alerts.
    """
    def __init__(self, mode: str = "OFFLINE"):
        self.mode = mode
        self.engine_name = "pyttsx3"
        self.cache_dir = Path("mobile/assets/audio")
        self.cache_index_path = self.cache_dir / "index.json"
        self.audio_cache = self._load_audio_cache()
        self.speak_queue = queue.PriorityQueue()
        self._seq = count()
        self._setup_bus()
        self._setup_worker()
        logger.info(f"PERSONA_4_REPORT: ACOUSTIC_UI_ONLINE | mode={self.mode} | engine={self.engine_name}")

    def _load_audio_cache(self) -> Dict[str, Dict[str, str]]:
        if not self.cache_index_path.exists():
            logger.warning("AUDIO_CACHE: index.json not found; using real-time TTS only")
            return {}
        try:
            with self.cache_index_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info(f"AUDIO_CACHE: Loaded {len(data)} cached phrases")
            return data
        except Exception as e:
            logger.error(f"AUDIO_CACHE_LOAD_ERROR: {e}")
            return {}

    @staticmethod
    def _normalize_phrase(phrase: str) -> str:
        return " ".join((phrase or "").strip().lower().split())

    def _play_from_cache(self, phrase: str) -> bool:
        cache_key = self._normalize_phrase(phrase)
        cache_meta = self.audio_cache.get(cache_key)
        if not cache_meta:
            return False

        audio_file = self.cache_dir / cache_meta.get("file", "")
        if not audio_file.exists():
            logger.warning(f"AUDIO_CACHE_MISS_FILE: {audio_file}")
            return False

        try:
            # Async playback avoids blocking the main event flow.
            winsound.PlaySound(str(audio_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
            logger.info(f"AUDIO_CACHE_HIT: {audio_file.name}")
            return True
        except Exception as e:
            logger.error(f"AUDIO_CACHE_PLAY_ERROR: {e}")
            return False

    def _setup_worker(self):
        def worker():
            try:
                # Initialize COM/pyttsx3 once inside the thread
                engine = pyttsx3.init()
                engine.setProperty('rate', 150)
                while True:
                    priority, _, phrase = self.speak_queue.get()
                    if phrase is None:
                        break
                    try:
                        logger.info(f"TTS_DEQUEUE: priority={priority} text={phrase[:80]}")
                        engine.say(phrase)
                        engine.runAndWait()
                    except Exception as e:
                        logger.error(f"TTS_WORKER_ERROR: {e}")
                    self.speak_queue.task_done()
            except Exception as e:
                logger.error(f"TTS_INIT_ERROR: {e}")
                
        threading.Thread(target=worker, daemon=True).start()

    def _setup_bus(self):

        bus.subscribe("FAST_CRITICAL_ALERT", self._on_fast_critical_alert)
        bus.subscribe("SENTINEL_FUSION_ALERT", self._on_fusion_alert)
        bus.subscribe("REGULATORY_CONFLICT", self._on_regulatory_conflict)

    def _on_fast_critical_alert(self, alert_payload: Dict[str, Any]):
        phrase = alert_payload.get("phrase") or "Critical pothole ahead. Slow down now."
        self._playback(phrase, "CRITICAL")

    def _on_fusion_alert(self, alert_payload: Dict[str, Any]):
        """
        Receives: { 'fusion_id', 'type', 'severity', 'timestamp_epoch_ms' }
        """
        severity = alert_payload.get("severity", "MEDIUM")
        alert_type = alert_payload.get("type", "GENERAL")
        
        # 1. Generate a friendly but direct message (no sugar-coating).
        phrase = driver_companion.generate_message(alert_type, severity)
        
        # 2. Trigger Synthesis / Playback
        self._playback(phrase, severity)

    def _on_regulatory_conflict(self, conflict_payload: Dict[str, Any]):
        # "Macha, look at the sign board"
        phrase = driver_companion.generate_message("LEGAL_SIGN_MISSING", "HIGH")
        self._playback(phrase, "HIGH")

    def _playback(self, phrase: str, severity: str):
        """
        In production, this calls the Bhashini Offline TTS engine via subprocess or local lib.
        For immediate offline demo, we use `pyttsx3` natively on Windows.
        """
        log_level = logging.WARNING if severity == "CRITICAL" else logging.INFO
        logger.log(log_level, f"TTS_ENGINE: SPEAK: '{phrase}' [priority={severity}]")

        # SYSTEM DIRECTIVE: STRIKE COMMAND - ACOUSTIC PRE-CACHING
        # Cache-first playback to eliminate real-time TTS latency for common critical alerts.
        if self._play_from_cache(phrase):
            return
        
        # Critical alerts preempt normal voice traffic.
        priority = 0 if severity == "CRITICAL" else 1
        self.speak_queue.put((priority, next(self._seq), phrase))
        
        # Simulated Bhashini Synthesis Payload for Shadow Mode
        bhashini_req = {
            "text": phrase,
            "persona": "SENTINEL_MACHA",
            "dialect": "CHENNAI_TAMIL_ANGLO",
            "offline": True
        }
        bus.emit("TTS_SYNTHESIS_REQUEST", bhashini_req)

if __name__ == "__main__":
    # Test
    ui_agent = AcousticUIAgent()
    bus.emit("SENTINEL_FUSION_ALERT", {
        "type": "CONFIRMED_POTHOLE_STRIKE",
        "severity": "CRITICAL"
    })
=======
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

    def stop(self, join_timeout_s: float = 1.0) -> None:
        self._running = False
        with self._lock:
            self._queue.clear()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=join_timeout_s)

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
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e
