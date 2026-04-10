"""
orchestrator/app/wake.py
Wyoming openwakeword client stub.

Connects to the openwakeword Wyoming service and checks whether any of the
accumulated PCM audio contains the configured wake-word ("hey_jarvis").

TODO: replace the stub logic with a real Wyoming protocol exchange once the
      openwakeword container is reachable from the orchestrator network.
"""

from __future__ import annotations

import logging
import os
import socket
import struct

logger = logging.getLogger(__name__)

_WAKE_HOST = os.getenv("WAKE_HOST", "openwakeword")
_WAKE_PORT = int(os.getenv("WAKE_PORT", "10400"))

# Wyoming protocol magic byte for AudioChunk event
_EVENT_AUDIO_CHUNK = b"audio-chunk\n"
_EVENT_DETECTION = "detection"

# Minimum audio length before bothering to check (0.5 s × 16 000 Hz × 2 bytes/sample)
_MIN_BYTES = 16000


def detect_wake_word(pcm_bytes: bytes) -> bool:
    """
    Send *pcm_bytes* to the openwakeword Wyoming service and return ``True``
    if a wake-word detection event is received back.

    Falls back to ``False`` on any connection or protocol error so the
    orchestrator can keep running without the wake-word service.

    Parameters
    ----------
    pcm_bytes:
        Raw 16 kHz / 16-bit / mono PCM audio bytes to check.
    """
    if len(pcm_bytes) < _MIN_BYTES:
        return False

    try:
        with socket.create_connection((_WAKE_HOST, _WAKE_PORT), timeout=2.0) as sock:
            # ── Send AudioChunk Wyoming event ────────────────────────────
            # Header: "audio-chunk\n" + JSON metadata line + blank line + payload
            rate = 16000
            width = 2  # bytes per sample (16-bit)
            channels = 1
            num_samples = len(pcm_bytes) // width

            header_json = (
                f'{{"type":"audio-chunk","data":{{'
                f'"rate":{rate},"width":{width},"channels":{channels},'
                f'"timestamp":0}},'
                f'"data_length":{len(pcm_bytes)}}}\n\n'
            ).encode()

            sock.sendall(header_json + pcm_bytes)

            # ── Read response ────────────────────────────────────────────
            # Wyoming server responds with a JSON line per event.
            response = b""
            sock.settimeout(1.0)
            try:
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
            except socket.timeout:
                pass

            if _EVENT_DETECTION in response.decode(errors="ignore"):
                logger.info("Wake-word detected by openwakeword service")
                return True

    except (OSError, ConnectionRefusedError) as exc:
        # Service not reachable — silently continue (stub / offline mode)
        logger.debug("openwakeword not reachable: %s", exc)

    return False
