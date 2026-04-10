# NNDL Voice Assistant — Architecture

## Overview

Offline, hands-free voice assistant targeting **Tamil Nadu drivers**.  
All speech processing runs locally — no cloud services required.

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Driver's Device                                │
│                                                                       │
│   Microphone ──► mic_client.py ──► ws://orchestrator:9000/ws/mic     │
│                                        │                              │
│   Speaker   ◄── reply.wav   ◄──────────┘                              │
└───────────────────────────────────────────────────────────────────────┘
                                         │
              ┌──────────────────────────▼──────────────────────────┐
              │              Orchestrator  :9000  (FastAPI)          │
              │                                                      │
              │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
              │  │  wake.py │  │  stt.py  │  │    tts.py        │  │
              │  │ Wyoming  │  │ Wyoming  │  │  Piper / sine    │  │
              │  │ protocol │  │ protocol │  │  fallback WAV    │  │
              │  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
              │       │             │                  │             │
              └───────┼─────────────┼──────────────────┼─────────────┘
                      │             │                  │
            ┌─────────▼──┐  ┌───────▼──────┐  ┌───────▼──────┐
            │openwakeword│  │    vosk      │  │    piper     │
            │  :10400    │  │   :10300     │  │   :10200     │
            │ (Wyoming)  │  │  (Wyoming)   │  │  (Wyoming)   │
            └────────────┘  └─────────────┘  └─────────────┘

              ┌──────────────────────────────────────────────────────┐
              │              Orchestrator Tools                      │
              │                                                      │
              │  ┌────────────────────┐  ┌──────────────────────┐  │
              │  │  tools/rag.py      │  │ tools/speed_limit.py │  │
              │  │  Qdrant vector DB  │  │  Valhalla + TN table │  │
              │  └────────┬───────────┘  └───────────┬──────────┘  │
              └───────────┼──────────────────────────┼──────────────┘
                          │                          │
                ┌─────────▼──────┐       ┌───────────▼──────────┐
                │   qdrant :6333 │       │  valhalla :8002      │
                │  (vector DB)   │       │  (map-matching)      │
                └────────────────┘       └──────────────────────┘
```

---

## Port Reference

| Service       | Container Port | Protocol  | Description                        |
|---------------|:--------------:|:---------:|------------------------------------|
| openwakeword  | 10400          | TCP/Wyoming | Wake-word detection ("hey_jarvis")|
| vosk          | 10300          | TCP/Wyoming | Offline speech-to-text             |
| piper         | 10200          | TCP/Wyoming | Offline text-to-speech             |
| qdrant        | 6333           | HTTP/gRPC   | Vector database (RAG)              |
| valhalla      | 8002           | HTTP        | Map-matching / speed limits        |
| orchestrator  | 9000           | HTTP/WS     | FastAPI coordinator                |

---

## Audio Format

| Property    | Value                              |
|-------------|------------------------------------|
| Sample rate | 16 000 Hz                          |
| Bit depth   | 16-bit signed little-endian        |
| Channels    | 1 (mono)                           |
| Frame size  | 20 ms → 320 samples → 640 bytes    |
| Container   | Raw PCM on wire; WAV in reply      |

---

## WebSocket Protocol (`/ws/mic`)

```
Client                              Orchestrator
  │                                      │
  │── binary: PCM chunk (640 bytes) ──►  │  (buffering, wake-word check)
  │── binary: PCM chunk …              ──►│
  │                                      │
  │◄── text: "WAKE" ─────────────────── │  (wake-word fired)
  │                                      │
  │── binary: PCM chunk (utterance) ──►  │  (STT accumulation)
  │── binary: PCM chunk …              ──►│
  │                                      │
  │── text: "DONE" ───────────────────►  │  (end of utterance)
  │                                      │
  │◄── binary: WAV bytes ─────────────── │  (TTS reply)
  │                                      │
  │◄── text: "BYE" ─────────────────── │  (server closing)
  ╳                                      ╳
```

### Control messages

| Direction     | Message     | Meaning                                    |
|---------------|-------------|--------------------------------------------|
| Server → Client | `WAKE`    | Wake-word detected; switch to STT mode     |
| Client → Server | `DONE`    | End of utterance; trigger transcription    |
| Server → Client | `BYE`     | Session ending; client may close           |

---

## HTTP Endpoints

| Method | Path        | Description                                    |
|--------|-------------|------------------------------------------------|
| GET    | /health     | Liveness check; returns service addresses      |
| POST   | /gps        | Ingest GPS fix; rolling 50-point trace         |
| GET    | /gps/trace  | Return current GPS trace                       |
| WS     | /ws/mic     | Microphone audio streaming (see above)         |

---

## GPS Data Flow

```
mic_client / vehicle ECU
    │
    │  POST /gps  { lat, lon, speed_kmh, heading_deg, timestamp_ms }
    ▼
Orchestrator  (deque, maxlen=50)
    │
    ├── speed_limit.py  →  Valhalla /locate  →  posted speed
    └── RAG context     →  Qdrant search     →  relevant road rule
```

---

## Environment Variables

| Variable         | Default        | Description                     |
|------------------|----------------|---------------------------------|
| `WAKE_HOST`      | openwakeword   | openwakeword container hostname |
| `WAKE_PORT`      | 10400          | Wyoming TCP port                |
| `STT_HOST`       | vosk           | Vosk container hostname         |
| `STT_PORT`       | 10300          | Wyoming TCP port                |
| `TTS_HOST`       | piper          | Piper container hostname        |
| `TTS_PORT`       | 10200          | Wyoming TCP port                |
| `QDRANT_HOST`    | qdrant         | Qdrant container hostname       |
| `QDRANT_PORT`    | 6333           | Qdrant HTTP port                |
| `VALHALLA_HOST`  | valhalla       | Valhalla container hostname     |
| `VALHALLA_PORT`  | 8002           | Valhalla HTTP port              |
| `LOG_LEVEL`      | info           | Python log level                |

---

## Roadmap / TODOs

- [ ] Replace hash-based embeddings in `rag.py` with a multilingual
      sentence-transformer model.
- [ ] Seed Qdrant with MV Act / Tamil Nadu-specific driving regulations.
- [ ] Implement full Wyoming binary protocol framing in `wake.py` / `stt.py`.
- [ ] Add Tamil (`ta`) TTS voice to Piper; enable language selection via
      driver preference profile.
- [ ] Integrate the 50-point GPS trace with Valhalla `trace_attributes` for
      accurate map-matching on curved roads.
- [ ] Add intent classification layer (NLU) between STT and tool dispatch.
- [ ] Expose Prometheus metrics from the orchestrator.
- [ ] Add JWT authentication to the WebSocket endpoint.
