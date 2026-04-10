"""
orchestrator/app/stt.py
Wyoming Vosk STT client stub.

Sends raw PCM audio to the Vosk Wyoming service and returns the transcript
as a plain string.

TODO: replace with a full Wyoming AudioChunk → Transcript exchange once the
      Vosk container is confirmed healthy on the network.
"""

from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger(__name__)

_STT_HOST = os.getenv("STT_HOST", "vosk")
_STT_PORT = int(os.getenv("STT_PORT", "10300"))

# Minimum audio to attempt transcription (0.5 s)
_MIN_BYTES = 16000 * 2 // 2


def transcribe(pcm_bytes: bytes) -> str:
    """
    Send *pcm_bytes* (16 kHz / 16-bit / mono PCM) to the Vosk Wyoming service
    and return the recognised text.

    Returns an empty string on any error or if the audio is too short.

    Parameters
    ----------
    pcm_bytes:
        Raw audio bytes to transcribe.
    """
    if len(pcm_bytes) < _MIN_BYTES:
        logger.debug("Audio too short for STT (%d bytes)", len(pcm_bytes))
        return ""

    try:
        with socket.create_connection((_STT_HOST, _STT_PORT), timeout=5.0) as sock:
            rate = 16000
            width = 2
            channels = 1

            # Wyoming AudioChunk event
            header_json = (
                f'{{"type":"audio-chunk","data":{{'
                f'"rate":{rate},"width":{width},"channels":{channels},'
                f'"timestamp":0}},'
                f'"data_length":{len(pcm_bytes)}}}\n\n'
            ).encode()
            sock.sendall(header_json + pcm_bytes)

            # Wyoming AudioStop event (signals end of utterance)
            stop_json = b'{"type":"audio-stop","data":{},"data_length":0}\n\n'
            sock.sendall(stop_json)

            # Read transcript event lines
            response = b""
            sock.settimeout(3.0)
            try:
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
            except socket.timeout:
                pass

            # Extract "text" field from Wyoming Transcript JSON event
            text = _parse_transcript(response.decode(errors="ignore"))
            logger.info("STT transcript: %r", text)
            return text

    except (OSError, ConnectionRefusedError) as exc:
        logger.debug("Vosk STT not reachable: %s", exc)
        return ""


def _parse_transcript(response: str) -> str:
    """
    Naively extract the ``text`` field from a Wyoming ``transcript`` event.

    Example Wyoming response line::

        {"type":"transcript","data":{"text":"what is the speed limit"},"data_length":0}
    """
    import json  # noqa: PLC0415

    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "transcript":
                return obj.get("data", {}).get("text", "")
        except json.JSONDecodeError:
            continue
    return ""
