#!/usr/bin/env python3
"""
scripts/mic_client.py
Demo microphone client for the NNDL voice assistant.

Records audio from the default system microphone, streams it in 20 ms PCM
frames to the orchestrator WebSocket endpoint (``ws://localhost:9000/ws/mic``),
then saves the TTS reply WAV to ``reply.wav``.

Dependencies
------------
    pip install sounddevice websocket-client numpy

Usage
-----
    python scripts/mic_client.py              # record 4 seconds (default)
    python scripts/mic_client.py --sec 6      # record 6 seconds
    python scripts/mic_client.py --host 192.168.1.5 --port 9000
    python scripts/mic_client.py --output /tmp/response.wav
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mic_client")

# ── audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE = 16000        # Hz — must match orchestrator
CHANNELS = 1               # mono
SAMPLE_WIDTH = 2           # bytes per sample (16-bit signed)
FRAME_MS = 20              # milliseconds per WebSocket frame
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320 samples per frame
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH       # 640 bytes per frame


def _import_deps():
    """Import optional dependencies with a helpful error message."""
    try:
        import numpy as np          # noqa: F401
        import sounddevice as sd    # noqa: F401
        import websocket            # noqa: F401
        return np, sd, websocket
    except ImportError as exc:
        logger.error(
            "Missing dependency: %s\n"
            "Install with:  pip install sounddevice websocket-client numpy",
            exc,
        )
        sys.exit(1)


def record_audio(duration_s: float, sample_rate: int = SAMPLE_RATE) -> bytes:
    """
    Record *duration_s* seconds of mono 16-bit PCM from the default mic.

    Returns raw PCM bytes.
    """
    np, sd, _ = _import_deps()
    logger.info("Recording %.1f s from microphone …", duration_s)
    samples = sd.rec(
        int(duration_s * sample_rate),
        samplerate=sample_rate,
        channels=CHANNELS,
        dtype="int16",
        blocking=True,
    )
    logger.info("Recording complete.")
    return samples.tobytes()


def stream_and_receive(
    pcm_bytes: bytes,
    host: str,
    port: int,
    output_path: Path,
) -> None:
    """
    Stream *pcm_bytes* to the orchestrator WebSocket in 20 ms frames,
    then save the received WAV reply to *output_path*.
    """
    _, _, websocket = _import_deps()
    import websocket as ws_module  # noqa: PLC0415

    url = f"ws://{host}:{port}/ws/mic"
    logger.info("Connecting to %s", url)

    reply_chunks: list[bytes] = []
    wake_received = False

    def on_open(wsapp):
        logger.info("WebSocket connected — streaming %d bytes in %d ms frames",
                    len(pcm_bytes), FRAME_MS)
        offset = 0
        while offset < len(pcm_bytes):
            frame = pcm_bytes[offset : offset + FRAME_BYTES]
            wsapp.send_binary(frame)
            offset += FRAME_BYTES
            time.sleep(FRAME_MS / 1000)

        logger.info("All frames sent — signalling DONE")
        wsapp.send("DONE")

    def on_message(wsapp, message):
        nonlocal wake_received
        if isinstance(message, bytes):
            reply_chunks.append(message)
            logger.info("Received WAV chunk: %d bytes", len(message))
        elif isinstance(message, str):
            msg = message.strip()
            if msg == "WAKE":
                wake_received = True
                logger.info("Wake-word detected by server!")
            elif msg == "BYE":
                logger.info("Server closed session.")
                wsapp.close()
            else:
                logger.info("Server message: %s", msg)

    def on_error(wsapp, error):
        logger.error("WebSocket error: %s", error)

    def on_close(wsapp, code, reason):
        logger.info("WebSocket closed (code=%s)", code)

    wsapp = ws_module.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    wsapp.run_forever()

    if reply_chunks:
        wav_data = b"".join(reply_chunks)
        output_path.write_bytes(wav_data)
        logger.info("Reply saved to %s (%d bytes)", output_path, len(wav_data))
    else:
        logger.warning("No WAV reply received from orchestrator.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo microphone client for the NNDL voice assistant.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--sec", type=float, default=4.0,
                        help="Recording duration in seconds.")
    parser.add_argument("--host", default="localhost",
                        help="Orchestrator host.")
    parser.add_argument("--port", type=int, default=9000,
                        help="Orchestrator WebSocket port.")
    parser.add_argument("--output", default="reply.wav",
                        help="Output WAV file path.")
    args = parser.parse_args()

    output_path = Path(args.output)
    pcm_bytes = record_audio(args.sec)
    stream_and_receive(pcm_bytes, args.host, args.port, output_path)


if __name__ == "__main__":
    main()
