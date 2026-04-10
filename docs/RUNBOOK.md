# NNDL Voice Assistant — Runbook

## Prerequisites

| Tool            | Version  | Install                                      |
|-----------------|----------|----------------------------------------------|
| Docker          | ≥ 24     | https://docs.docker.com/get-docker/          |
| Docker Compose  | ≥ 2.20   | bundled with Docker Desktop                  |
| Python          | ≥ 3.9    | https://www.python.org/downloads/            |
| sounddevice     | any      | `pip install sounddevice`                    |
| websocket-client| any      | `pip install websocket-client`               |
| numpy           | any      | `pip install numpy`                          |

> **Offline note**: all speech models run locally.  No internet access is
> required after the initial model download step.

---

## Step-by-step Setup

### 1 — Clone the repository

```bash
git clone https://github.com/<your-org>/nndl.git
cd nndl
```

### 2 — Create required directories

```bash
mkdir -p models/vosk voices data/valhalla_tiles
```

### 3 — Download models

#### Vosk STT model (≈ 50 MB, English; swap for `vosk-model-small-en-in` for Indian English)

```bash
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
mv vosk-model-small-en-us-0.15 models/vosk/model
rm vosk-model-small-en-us-0.15.zip
```

#### Piper TTS voice (≈ 65 MB, US English; swap for a Tamil voice when available)

```bash
curl -LO https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx
curl -LO https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx.json
mv en_US-lessac-medium.onnx* voices/
```

#### Valhalla map tiles (Tamil Nadu OSM extract)

```bash
# Install valhalla-tools or use the Docker image to build tiles
# Quick start: download a pre-built tile set for Tamil Nadu from Geofabrik
curl -LO https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf
# Build tiles (takes ~10 minutes on a laptop)
docker run -v $(pwd)/data/valhalla_tiles:/custom_files \
  ghcr.io/gis-ops/docker-valhalla/valhalla:latest \
  valhalla_build_tiles -c /valhalla.json southern-zone-latest.osm.pbf
```

> Skip the tile build for a quick smoke test — Valhalla will start without
> tiles and the orchestrator will fall back to the TN static speed table.

---

### 4 — Start the stack

```bash
docker compose up --build -d
```

Watch logs:

```bash
docker compose logs -f orchestrator
```

### 5 — Verify all services are healthy

```bash
docker compose ps
```

All six services should show `healthy`.  If any remain `unhealthy` after
60 seconds see the **Troubleshooting** section below.

### 6 — Check the orchestrator health endpoint

```bash
curl -s http://localhost:9000/health | python3 -m json.tool
```

Expected output:

```json
{
  "status": "ok",
  "gps_points": 0,
  "services": {
    "wake": "openwakeword:10400",
    "stt":  "vosk:10300",
    "tts":  "piper:10200",
    "qdrant": "qdrant:6333",
    "valhalla": "valhalla:8002"
  }
}
```

### 7 — Send a GPS fix

```bash
curl -s -X POST http://localhost:9000/gps \
  -H 'Content-Type: application/json' \
  -d '{"lat":13.082,"lon":80.270,"speed_kmh":45,"heading_deg":90,"timestamp_ms":0}'
```

### 8 — Run the mic client

Install Python dependencies (once):

```bash
pip install sounddevice websocket-client numpy
```

Record 4 seconds and get a TTS reply:

```bash
python scripts/mic_client.py --sec 4
```

The script will:
1. Record 4 seconds from your default microphone.
2. Stream the audio to `ws://localhost:9000/ws/mic` in 20 ms frames.
3. Wait for the server to detect the wake-word ("hey jarvis"), transcribe,
   and synthesise a reply.
4. Save the reply WAV to `reply.wav` in the current directory.

Play the reply:

```bash
# Linux
aplay reply.wav
# macOS
afplay reply.wav
# Windows
powershell -c "(New-Object Media.SoundPlayer 'reply.wav').PlaySync()"
```

---

## Service Verification

### openwakeword (Wyoming :10400)

```bash
docker compose exec openwakeword sh -c \
  'echo > /dev/tcp/localhost/10400 && echo "OK" || echo "FAIL"'
```

### Vosk STT (Wyoming :10300)

```bash
docker compose exec vosk sh -c \
  'echo > /dev/tcp/localhost/10300 && echo "OK" || echo "FAIL"'
```

### Piper TTS (Wyoming :10200)

```bash
docker compose exec piper sh -c \
  'echo > /dev/tcp/localhost/10200 && echo "OK" || echo "FAIL"'
```

### Qdrant (:6333)

```bash
curl -s http://localhost:6333/readyz
```

Expected: `{"title":"qdrant - Ready","version":"..."}`

### Valhalla (:8002)

```bash
curl -s http://localhost:8002/status | python3 -m json.tool
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `orchestrator` stays `unhealthy` | Upstream service not ready | `docker compose logs orchestrator` — confirm depends_on services are healthy first |
| Vosk `unhealthy` | Model not found at `/model` | Verify `models/vosk/model/` exists and contains `am/`, `conf/` subdirectories |
| Piper `unhealthy` | Voice `.onnx` missing from `voices/` | Download the voice file (step 3) |
| Valhalla `unhealthy` | Tile directory empty | Either build tiles (step 3) or ignore — the TN speed table fallback works without tiles |
| `reply.wav` is a sine tone | Piper not reachable from orchestrator | Piper container unhealthy; check `docker compose logs piper` |
| No wake-word detection | openwakeword container unhealthy | Check logs; ensure the wake-word name `hey_jarvis` matches the container command |
| `sounddevice` error | No microphone | Check system audio settings; use `python -c "import sounddevice; print(sounddevice.query_devices())"` |
| Port conflict | Another service on same port | Change host port in `docker-compose.yml` (left side of `ports:`) |

---

## Port Reference

| Service      | Host Port | Container Port | Protocol     |
|--------------|:---------:|:--------------:|:------------:|
| openwakeword | 10400     | 10400          | TCP (Wyoming)|
| vosk         | 10300     | 10300          | TCP (Wyoming)|
| piper        | 10200     | 10200          | TCP (Wyoming)|
| qdrant       | 6333      | 6333           | HTTP         |
| qdrant gRPC  | 6334      | 6334           | gRPC         |
| valhalla     | 8002      | 8002           | HTTP         |
| orchestrator | 9000      | 9000           | HTTP / WS    |

---

## Development Tips

### Run the orchestrator locally (without Docker)

```bash
cd orchestrator
pip install -r requirements.txt
# Point at local/mock services
WAKE_HOST=localhost WAKE_PORT=10400 \
STT_HOST=localhost  STT_PORT=10300  \
TTS_HOST=localhost  TTS_PORT=10200  \
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

### Mock mode without any downstream services

All stub modules (`wake.py`, `stt.py`, `tts.py`) handle connection failures
gracefully:

- `wake.py` returns `False` (no wake-word) when openwakeword is down.
- `stt.py` returns `""` (empty transcript) when Vosk is down.
- `tts.py` returns an **880 Hz sine-wave WAV** when Piper is down — this lets
  you test the full WebSocket round-trip without any speech model.

### Interactive API docs

With the orchestrator running, open http://localhost:9000/docs for the
auto-generated Swagger UI.

### Rebuild a single service

```bash
docker compose up --build orchestrator -d
```

### Tail all logs

```bash
docker compose logs -f
```

### Stop the stack

```bash
docker compose down
```

Remove persistent Qdrant data:

```bash
docker compose down -v
```
