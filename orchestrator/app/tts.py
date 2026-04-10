"""
orchestrator/app/tts.py
Piper TTS client / placeholder WAV generator.

When the Piper Wyoming service is reachable the text is sent there and the
resulting WAV bytes are returned.  When the service is unavailable (e.g.
during local development without Docker) a 880 Hz sine-wave WAV is generated
in-process as a placeholder so the rest of the pipeline can still be tested
end-to-end.

TODO: replace the sine-wave fallback with a hard error once Piper is always
      available in the deployment environment.
"""

from __future__ import annotations

import io
import logging
import math
import os
import socket
import struct
import wave

logger = logging.getLogger(__name__)

_TTS_HOST = os.getenv("TTS_HOST", "piper")
_TTS_PORT = int(os.getenv("TTS_PORT", "10200"))

# Sine-wave placeholder parameters
_SAMPLE_RATE = 22050        # Hz  (Piper default output rate)
_FREQ_HZ = 880              # A5 — easily audible placeholder tone
_DURATION_S = 1.5           # seconds
_AMPLITUDE = 16000          # 16-bit headroom


def synthesise(text: str) -> bytes:
    """
    Convert *text* to speech and return a WAV file as bytes.

    Tries the Piper Wyoming service first; falls back to a 880 Hz sine-wave
    placeholder on connection errors.

    Parameters
    ----------
    text:
        The string to speak.

    Returns
    -------
    bytes
        A valid WAV file (PCM, 16-bit, mono, 22 050 Hz).
    """
    wav = _try_piper(text)
    if wav:
        return wav
    logger.info("Piper unavailable — returning 880 Hz sine-wave placeholder")
    return _sine_wave_wav(text)


# ── Piper Wyoming client ──────────────────────────────────────────────────────

def _try_piper(text: str) -> bytes | None:
    """Attempt to synthesise *text* via the Piper Wyoming service."""
    try:
        with socket.create_connection((_TTS_HOST, _TTS_PORT), timeout=5.0) as sock:
            payload = text.encode("utf-8")
            header_json = (
                f'{{"type":"synthesize","data":{{'
                f'"text":"{text.replace(chr(34), chr(39))}"}},'
                f'"data_length":0}}\n\n'
            ).encode()
            sock.sendall(header_json)

            # Read back audio-chunk events and reassemble WAV
            audio_chunks: list[bytes] = []
            sample_rate: int = _SAMPLE_RATE
            sock.settimeout(8.0)
            try:
                buf = b""
                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    buf += data
                    buf, chunks, sr = _parse_audio_chunks(buf)
                    audio_chunks.extend(chunks)
                    if sr:
                        sample_rate = sr
            except socket.timeout:
                pass

            if audio_chunks:
                return _build_wav(b"".join(audio_chunks), sample_rate)

    except (OSError, ConnectionRefusedError) as exc:
        logger.debug("Piper not reachable: %s", exc)

    return None


def _parse_audio_chunks(buf: bytes) -> tuple[bytes, list[bytes], int]:
    """
    Naively parse Wyoming audio-chunk events from a byte buffer.

    Returns (remaining_buf, chunks, sample_rate).
    """
    import json  # noqa: PLC0415

    chunks: list[bytes] = []
    sample_rate: int = 0

    while True:
        sep = buf.find(b"\n\n")
        if sep == -1:
            break
        header_bytes = buf[:sep]
        rest = buf[sep + 2:]
        try:
            obj = json.loads(header_bytes.decode(errors="ignore"))
        except json.JSONDecodeError:
            buf = rest
            continue

        data_length = int(obj.get("data_length", 0))
        if len(rest) < data_length:
            break  # wait for more data

        payload = rest[:data_length]
        buf = rest[data_length:]

        if obj.get("type") == "audio-chunk":
            chunks.append(payload)
            if not sample_rate:
                sample_rate = int(obj.get("data", {}).get("rate", _SAMPLE_RATE))

    return buf, chunks, sample_rate


# ── WAV helpers ───────────────────────────────────────────────────────────────

def _build_wav(pcm_bytes: bytes, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM bytes in a RIFF/WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _sine_wave_wav(text: str = "") -> bytes:
    """
    Generate a 880 Hz sine-wave WAV as a TTS placeholder.

    The duration is proportional to the length of *text* (min 1 s, max 5 s)
    so the placeholder audio is vaguely "speech-length".
    """
    word_count = max(1, len(text.split()))
    duration = min(max(word_count * 0.35, 1.0), 5.0)  # 0.35 s per word

    num_samples = int(_SAMPLE_RATE * duration)
    pcm = bytearray()
    for i in range(num_samples):
        sample = int(_AMPLITUDE * math.sin(2 * math.pi * _FREQ_HZ * i / _SAMPLE_RATE))
        pcm += struct.pack("<h", sample)

    return _build_wav(bytes(pcm), _SAMPLE_RATE)
