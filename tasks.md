# SmartSalai Edge-Sentinel: Kanban Board

## TODO
- [ ] Persona 6: Ingest `MVA_2019_AMENDMENT.pdf` and `TN_GO_MS_56_2022.pdf` via `pdfplumber` [BLOCKED: MISSING_FILES]
- [ ] Persona 6: Map `chennai_accidents.csv` blackspots to geofencing logic [BLOCKED: MISSING_FILES]
- [ ] Persona 1: Implement BLE Mesh Protocol node discovery
- [ ] Persona 2: Integrate ULS validator with RAG output
- [ ] T-010: Legal RAG pipeline (`agents/legal_rag.py`)
- [ ] T-011: Section 208 audit drafter (`agents/sec208_drafter.py`)
- [ ] T-014: Full ZKP circuit (Groth16/Pedersen) replacing SHA3-256 coordinate commitment
- [ ] T-019: Bhashini TTS latency optimisation — target <50 ms via streaming API

## IN-PROGRESS
- [x] Persona 5: Project Structure Initialization
- [x] Persona 5: Kanban Task Management Setup

## DONE
- [x] Persona 1: Universal Legal Schema Definition
- [x] Persona 1: BLE Mesh Message Protocol JSON
- [x] T-008: BLE V2X mesh broker (`agents/ble_mesh_broker.py`) — HMAC-SHA256 + AES-128-CCM
- [x] T-009: Vision audit engine (`vision_audit.py`) — ONNX YOLOv8n pipeline; mock mode when model absent
- [x] T-012: Acoustic voice UI (`agents/acoustic_ui.py`) — Tamil/English TTS, priority queue
- [x] T-013: Agent event bus (`core/agent_bus.py`) — thread-safe pub/sub, heartbeat, watchdog
- [x] T-015: iRAD V-NMS-01 serialiser (`core/irad_serializer.py`)
- [x] T-016: Section 208 GPS-distance enforcement (`section_208_resolver.py`)
- [x] T-017/T-018 (ERR-003): Android ADB deployment script (`scripts/deploy_android.py`) — dynamic device discovery, no hardcoded fingerprint
- [x] ERR-001: Vision model download pipeline (`scripts/download_models.py`) — Roboflow → HF → ultralytics fallback chain; `models/vision/README.md` setup guide
- [x] ERR-002: Bhashini ULCA REST TTS client (`core/bhashini_tts.py`) wired into `acoustic_ui.py` — real Tamil synthesis when BHASHINI_USER_ID + BHASHINI_API_KEY present
- [x] ERR-003: ADB fingerprint removed — `scripts/deploy_android.py` enumerates devices dynamically

