# SmartSalai Edge-Sentinel — Architecture Overview

## System Architecture

SmartSalai Edge-Sentinel is a multi-agent, edge-native AI framework for two-wheeler road safety in Tamil Nadu. All inference runs fully on-device (zero cloud dependency).

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SmartSalai Edge-Sentinel v0.1.0                      │
│                         (Android NPU — INT8)                            │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────────┤
│  P1: BLE     │  P2: Legal   │  P3: Vision  │  P4: Voice  │  P5: DevOps │
│  Mesh Broker │  RAG / Sec   │  & IMU-TCN   │  Bhashini   │  CI/CD      │
│  (V2X, ZKP)  │  208 Drafter │  Near-Miss   │  TTS <100ms │  Kanban     │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴─────────────┘
       │              │              │              │
       └──────────────┴──────JSON-RPC Bus───────────┘
                         (core/agent_bus.py)
```

## Module Descriptions

### `agents/`
| File | Persona | Description |
|---|---|---|
| `imu_near_miss_detector.py` | P3 | TCN-based sensor fusion; detects near-miss events from 6-DOF IMU at 100 Hz |
| `sign_auditor.py` | P3 | YOLOv8-nano sign audit; classifies traffic signs (requires ONNX model) |
| `ble_mesh_broker.py` | P1 | BLE V2X hazard sharing between nearby vehicles |
| `legal_rag.py` | P2 | MVA 2019 / TN G.O. RAG pipeline using Edge vector store |
| `sec208_drafter.py` | P2 | Drafts Section 208 MVA audit requests when camera lacks IRC:67 signage |
| `acoustic_ui.py` | P4 | Bhashini offline TTS voice alerts (Tanglish) |
| `blackspot_geofence.py` | P3 | Maps Chennai blackspot CSV data to geofencing alerts |

### `core/`
| File | Description |
|---|---|
| `agent_bus.py` | JSON-RPC inter-agent message bus |
| `zkp_envelope.py` | Pedersen Commitment ZKP wrapper for privacy-preserving telemetry |
| `irad_serializer.py` | Converts events to iRAD (MoRTH Integrated Road Accident Database) schema |

### `etl/`
ETL pipeline for ingesting legal PDFs and accident data into the Edge vector store.

| File | Description |
|---|---|
| `pdf_extractor.py` | Raw text extraction using pdfplumber with Tesseract OCR fallback |
| `text_chunker.py` | Section-aware legal document chunking |
| `embedder.py` | Local ONNX-INT8 sentence-embedding generation |
| `sqlite_vss_ingestor.py` | Persists embeddings into SQLite-VSS for Edge-RAG |
| `pipeline.py` | Orchestrates the ETL stages (directory watcher + ordered execution) |

### `schemas/`
- `universal_legal_schema.json` — ULS-v1.0.0; jurisdiction-swappable offence ontology for IN_TN

### Root-level modules
| File | Description |
|---|---|
| `system_orchestrator.py` | Main entry point; routes sensor data through all agents |
| `vision_audit.py` | ONNX YOLOv8-nano inference engine (falls back to mock mode without model file) |
| `edge_vector_store.py` | SQLite-VSS legal vector store interface |
| `section_208_resolver.py` | Challenge generator for speed-camera / signage compliance |
| `offline_tts_manager.py` | Offline TTS orchestration (pyttsx3 fallback when Bhashini unavailable) |
| `ingest_legal_pdfs.py` | CLI script to ingest raw data PDFs into the ETL pipeline |

## Data Flow

```
[IMU @100Hz] ─────────────────────────────────────────► NearMissDetector
                                                              │
[Camera Frame] ──► VisionAuditEngine (ONNX INT8) ────────────┤
                                                              ▼
                                                    SmartSalaiOrchestrator
                                                         ├── Section208Resolver
                                                         ├── OfflineTTSManager
                                                         └── EdgeVectorStore (RAG)
```

## Privacy & Legal

- **Zero telemetry upload**: all inference stays on-device
- **ZKP envelope**: Pedersen Commitment wraps all iRAD telemetry emits before any sharing
- **Legal dataset**: MoRTH Gazette S.O. 2224(E); TN G.O.(Ms).No.56/2022
- **Section 208 trigger**: auto-drafted when speed camera detected but no IRC:67 sign within 500 m upstream

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `VISION_MODEL_PATH` | `models/vision/indian_traffic_yolov8.onnx` | Path to YOLOv8-nano ONNX INT8 checkpoint |
| `VISION_MOCK_MODE` | `0` | Set to `1` to force mock vision mode (CI/testing) |
| `VISION_CONF_THRESHOLD` | `0.45` | Detection confidence threshold |
| `RAW_DATA_DIR` | `raw_data/` | Directory containing source PDFs for ETL |
