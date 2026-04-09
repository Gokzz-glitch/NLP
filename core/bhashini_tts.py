"""
core/bhashini_tts.py
SmartSalai Edge-Sentinel — Bhashini ULCA REST TTS Client (ERR-002 resolver)

Provides Tamil (and other Indic language) speech synthesis via the
Bhashini / ULCA (Unified Language Contribution API) inference service.

Architecture:
  BhashiniTTSClient.synthesize(text, lang) → bytes (WAV audio, 8000 Hz)

Two-step Bhashini pipeline:
  1. Pipeline discovery — POST /ulca/apis/v0/model/getModelsPipeline
     → returns service URL and serviceId for the TTS model.
  2. TTS inference     — POST <callback_url>/v1/pipeline
     → returns base64-encoded WAV audio.

Discovery results are cached for CACHE_TTL_S seconds to avoid redundant
network calls (Bhashini rate-limits discovery requests).

Environment variables (set in .env):
  BHASHINI_USER_ID   — ULCA user ID (bhashini.gov.in → My Account)
  BHASHINI_API_KEY   — ULCA API key

Offline fallback:
  If the Bhashini API is unreachable or credentials are absent, synthesize()
  raises BhashiniUnavailableError.  Callers should catch this and fall back to
  pyttsx3 or espeak.

References:
  https://bhashini.gov.in/ulca/model-exploration
  https://github.com/AI4Bharat/Bhashini-API-Integration (community samples)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("edge_sentinel.core.bhashini_tts")

# ---------------------------------------------------------------------------
# Bhashini / ULCA API constants
# ---------------------------------------------------------------------------

_PIPELINE_DISCOVERY_URL = (
    "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
)
_DEFAULT_PIPELINE_ID = "64392f96daac500b55c543cd"   # MeitY ULCA default pipeline

# Cache TTL: re-discover the callback URL no more than once per hour
_CACHE_TTL_S: float = 3600.0

# Bhashini returns 8 kHz mono WAV by default; request higher quality
_SAMPLE_RATE = "8000"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BhashiniUnavailableError(RuntimeError):
    """Raised when the Bhashini API is unreachable or credentials are missing."""


# ---------------------------------------------------------------------------
# BhashiniTTSClient
# ---------------------------------------------------------------------------


class BhashiniTTSClient:
    """
    REST client for the Bhashini ULCA TTS inference API.

    Usage:
        client = BhashiniTTSClient()
        audio_bytes = client.synthesize("எச்சரிக்கை!", lang="ta")
        # audio_bytes is PCM WAV at 8 kHz; pass to a wave/audio output driver.

    Thread safety:
        synthesize() is thread-safe; the cache lock uses a threading.Lock.

    ERR-002 status:
        Set BHASHINI_USER_ID and BHASHINI_API_KEY in the environment or .env.
        Without credentials, every call raises BhashiniUnavailableError.
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        pipeline_id: str = _DEFAULT_PIPELINE_ID,
        timeout_s: float = 5.0,
    ) -> None:
        """
        Args:
            user_id:     Bhashini / ULCA user ID.  Falls back to BHASHINI_USER_ID env var.
            api_key:     Bhashini / ULCA API key.  Falls back to BHASHINI_API_KEY env var.
            pipeline_id: MeitY ULCA pipeline ID.  Default is the official production pipeline.
            timeout_s:   Per-request HTTP timeout in seconds.
        """
        self._user_id = user_id or os.getenv("BHASHINI_USER_ID", "")
        self._api_key = api_key or os.getenv("BHASHINI_API_KEY", "")
        self._pipeline_id = pipeline_id
        self._timeout = timeout_s

        # Discovery cache: (callback_url, service_id, expire_time)
        self._cache: dict[str, tuple[str, str, float]] = {}

        import threading
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Credential check
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True if API credentials are present in the environment."""
        return bool(self._user_id and self._api_key)

    # ------------------------------------------------------------------
    # Pipeline discovery
    # ------------------------------------------------------------------

    def _discover_pipeline(self, lang: str) -> tuple[str, str]:
        """
        Query the ULCA pipeline discovery endpoint to obtain the TTS service
        callback URL and serviceId for the given language.

        Returns:
            (callback_url, service_id)

        Raises:
            BhashiniUnavailableError: on HTTP error or missing credentials.
        """
        now = time.monotonic()
        with self._cache_lock:
            if lang in self._cache:
                url, sid, exp = self._cache[lang]
                if now < exp:
                    return url, sid

        if not self.is_configured():
            raise BhashiniUnavailableError(
                "Bhashini credentials not configured. "
                "Set BHASHINI_USER_ID and BHASHINI_API_KEY in .env to resolve ERR-002."
            )

        try:
            import urllib.request  # stdlib — no extra dep  # noqa: PLC0415
        except ImportError as exc:
            raise BhashiniUnavailableError("urllib.request unavailable") from exc

        payload = json.dumps({
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": lang},
                    },
                }
            ],
            "pipelineRequestConfig": {"pipelineId": self._pipeline_id},
        }).encode("utf-8")

        req = urllib.request.Request(
            _PIPELINE_DISCOVERY_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "userID": self._user_id,
                "ulcaApiKey": self._api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise BhashiniUnavailableError(
                f"Bhashini pipeline discovery failed: {exc}"
            ) from exc

        try:
            pipe_res = data["pipelineResponseConfig"][0]
            callback_url = pipe_res["config"][0]["serviceLocation"]
            service_id   = pipe_res["config"][0]["serviceId"]
        except (KeyError, IndexError) as exc:
            raise BhashiniUnavailableError(
                f"Unexpected discovery response structure: {exc}\nResponse: {data}"
            ) from exc

        with self._cache_lock:
            self._cache[lang] = (callback_url, service_id, now + _CACHE_TTL_S)

        logger.debug("[Bhashini] Discovered TTS service for '%s': %s", lang, callback_url)
        return callback_url, service_id

    # ------------------------------------------------------------------
    # TTS inference
    # ------------------------------------------------------------------

    def synthesize(self, text: str, lang: str = "ta", gender: str = "female") -> bytes:
        """
        Synthesise *text* to WAV audio bytes using the Bhashini ULCA TTS API.

        Args:
            text: Input text in the script of *lang*.
            lang: BCP-47 / ISO 639-1 code.  'ta' = Tamil, 'en' = English, etc.

        Returns:
            Raw WAV audio bytes (8 kHz, mono, PCM 16-bit).

        Raises:
            BhashiniUnavailableError: if the API is unreachable or fails.
        """
        callback_url, service_id = self._discover_pipeline(lang)

        import urllib.request  # noqa: PLC0415

        inference_url = callback_url.rstrip("/") + "/v1/pipeline"

        payload = json.dumps({
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": lang},
                        "serviceId": service_id,
                        "gender": gender,
                        "samplingRate": int(_SAMPLE_RATE),
                    },
                }
            ],
            "inputData": {
                "input": [{"source": text}],
                "audio": [{"audioContent": None}],
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            inference_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise BhashiniUnavailableError(
                f"Bhashini TTS inference failed: {exc}"
            ) from exc

        try:
            b64_audio = result["pipelineResponse"][0]["audio"][0]["audioContent"]
            return base64.b64decode(b64_audio)
        except (KeyError, IndexError) as exc:
            raise BhashiniUnavailableError(
                f"Unexpected inference response structure: {exc}\nResponse: {result}"
            ) from exc

    def synthesize_and_play(self, text: str, lang: str = "ta", gender: str = "female") -> bool:
        """
        Synthesise *text* and play it via the system audio output.

        Args:
            gender: 'male' or 'female' — Bhashini voice selection.
        """
        audio_bytes = self.synthesize(text, lang=lang, gender=gender)

        try:
            import pyaudio  # noqa: PLC0415
            import wave     # noqa: PLC0415
            import io       # noqa: PLC0415

            wf = wave.open(io.BytesIO(audio_bytes))
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pa.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True,
            )
            chunk = 1024
            data = wf.readframes(chunk)
            while data:
                stream.write(data)
                data = wf.readframes(chunk)
            stream.stop_stream()
            stream.close()
            pa.terminate()
            return True
        except ImportError:
            pass  # pyaudio not available

        # Fallback: write to temp file and use subprocess
        import tempfile       # noqa: PLC0415
        import subprocess     # noqa: PLC0415
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            # aplay (Linux), afplay (macOS), or PowerShell (Windows)
            for cmd in [
                ["aplay", "-q", tmp_path],
                ["afplay", tmp_path],
                ["powershell", "-c", f"(New-Object Media.SoundPlayer '{tmp_path}').PlaySync()"],
            ]:
                try:
                    subprocess.run(cmd, check=True, timeout=30,
                                   capture_output=True)
                    return True
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        logger.warning("[Bhashini] Audio playback unavailable — no aplay/afplay/pyaudio found.")
        return False
