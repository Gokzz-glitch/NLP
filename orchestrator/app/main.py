"""
orchestrator/app/main.py
FastAPI coordinator for the NNDL offline voice assistant stack.

Endpoints
---------
GET  /health      — service liveness check
POST /gps         — accept GPS fix; maintain 50-point rolling trace
WS   /ws/mic      — stream 16 kHz / 16-bit / mono PCM audio from client;
                    returns synthesised TTS reply as WAV bytes
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from typing import Any, Deque, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .wake import detect_wake_word
from .stt import transcribe
from .tts import synthesise

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator")

# ── application ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="NNDL Voice Orchestrator",
    description="Offline hands-free voice assistant for Tamil Nadu drivers.",
    version="0.1.0",
)

# ── GPS rolling trace (max 50 points) ─────────────────────────────────────────
_GPS_MAX: int = 50
gps_trace: Deque[Dict[str, Any]] = deque(maxlen=_GPS_MAX)


# ── schemas ───────────────────────────────────────────────────────────────────
class GPSPoint(BaseModel):
    lat: float
    lon: float
    speed_kmh: float = 0.0
    heading_deg: float = 0.0
    timestamp_ms: int = 0


class HealthResponse(BaseModel):
    status: str
    gps_points: int
    services: Dict[str, str]


# ── helpers ───────────────────────────────────────────────────────────────────
def _service_env(name: str, default_host: str, default_port: int) -> str:
    host = os.getenv(f"{name}_HOST", default_host)
    port = os.getenv(f"{name}_PORT", str(default_port))
    return f"{host}:{port}"


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Return liveness info and downstream service addresses."""
    return HealthResponse(
        status="ok",
        gps_points=len(gps_trace),
        services={
            "wake": _service_env("WAKE", "openwakeword", 10400),
            "stt": _service_env("STT", "vosk", 10300),
            "tts": _service_env("TTS", "piper", 10200),
            "qdrant": _service_env("QDRANT", "qdrant", 6333),
            "valhalla": _service_env("VALHALLA", "valhalla", 8002),
        },
    )


@app.post("/gps", tags=["telemetry"])
async def ingest_gps(point: GPSPoint) -> Dict[str, Any]:
    """
    Append a GPS fix to the rolling 50-point trace.

    Returns the current trace length and the last stored fix.
    """
    gps_trace.append(point.model_dump())
    logger.debug("GPS fix stored — trace length %d", len(gps_trace))
    return {"stored": True, "trace_length": len(gps_trace), "last": point.model_dump()}


@app.get("/gps/trace", tags=["telemetry"])
async def get_trace() -> Dict[str, Any]:
    """Return the current GPS trace (up to 50 points)."""
    return {"trace": list(gps_trace)}


@app.websocket("/ws/mic")
async def ws_mic(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time microphone audio.

    Protocol
    --------
    1. Client connects and streams raw PCM frames (16 kHz, 16-bit, mono).
       Each message is a binary chunk of any size (20 ms frames recommended).
    2. Orchestrator buffers audio.
    3. When a wake-word is detected the orchestrator signals the client with
       the text message ``"WAKE"`` and begins STT transcription on subsequent
       audio.
    4. After the utterance the orchestrator sends back a WAV file (bytes) as
       the TTS reply, then resets to wake-word listening mode.
    5. If the client sends the text message ``"DONE"`` the server finalises
       transcription immediately.
    6. The server sends ``"BYE"`` just before closing.

    Audio format: 16 000 Hz, 16-bit signed little-endian, mono (1 channel).
    """
    await websocket.accept()
    logger.info("WebSocket /ws/mic connected from %s", websocket.client)

    audio_buf: List[bytes] = []
    wake_active: bool = False

    try:
        while True:
            message = await websocket.receive()

            # ── binary frame (PCM audio) ──────────────────────────────────
            if "bytes" in message and message["bytes"] is not None:
                chunk: bytes = message["bytes"]
                audio_buf.append(chunk)

                if not wake_active:
                    # Check for wake-word on accumulated audio
                    pcm = b"".join(audio_buf)
                    if await asyncio.to_thread(detect_wake_word, pcm):
                        wake_active = True
                        audio_buf.clear()
                        await websocket.send_text("WAKE")
                        logger.info("Wake-word detected")

                # Keep buffer bounded (10 seconds max at 16 kHz/16-bit/mono)
                max_bytes = 16000 * 2 * 10
                total = sum(len(b) for b in audio_buf)
                while total > max_bytes and audio_buf:
                    removed = audio_buf.pop(0)
                    total -= len(removed)

            # ── text control message ──────────────────────────────────────
            elif "text" in message and message["text"] is not None:
                cmd: str = message["text"].strip().upper()

                if cmd == "DONE" or (wake_active and cmd == "END"):
                    pcm = b"".join(audio_buf)
                    transcript = await asyncio.to_thread(transcribe, pcm)
                    logger.info("Transcribed: %r", transcript)

                    # Build reply and synthesise TTS
                    reply_text = _build_reply(transcript)
                    wav_bytes = await asyncio.to_thread(synthesise, reply_text)

                    await websocket.send_bytes(wav_bytes)
                    logger.info("TTS reply sent (%d bytes)", len(wav_bytes))

                    # Reset for next utterance
                    audio_buf.clear()
                    wake_active = False

    except WebSocketDisconnect:
        logger.info("WebSocket /ws/mic disconnected")
    finally:
        try:
            await websocket.send_text("BYE")
            await websocket.close()
        except Exception:
            pass


# ── internal helpers ──────────────────────────────────────────────────────────

def _build_reply(transcript: str) -> str:
    """
    Minimal intent dispatcher.  Expand with RAG / speed-limit lookups here.

    TODO: integrate rag.query() and speed_limit.get_limit() for real answers.
    """
    from .tools.rag import query as rag_query  # noqa: PLC0415
    from .tools.speed_limit import get_limit   # noqa: PLC0415

    t = transcript.lower().strip()

    if not t:
        return "Sorry, I did not catch that."

    if "speed" in t or "limit" in t:
        last_gps = gps_trace[-1] if gps_trace else None
        if last_gps:
            lat, lon = last_gps["lat"], last_gps["lon"]
            limit = get_limit(lat, lon)
            return f"The speed limit here is {limit} kilometres per hour."
        return "Speed limit information is unavailable without a GPS fix."

    # Fall back to RAG knowledge base
    answer = rag_query(t)
    if answer:
        return answer

    return f"You said: {transcript}. How can I help you?"
