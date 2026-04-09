# SmartSalai Edge-Sentinel

> **Competition**: IIT Madras CoERS Hackathon 2026  
> **Track**: Smart Road Safety & Traffic Management  
> **Team Repository**: `Gokzz-glitch/NLP`

---

## System Overview

**SmartSalai Edge-Sentinel** is an edge-native, offline-first, multi-agent AI framework that acts as a proactive bio-legal shield for two-wheeler drivers in Tamil Nadu. It combines real-time computer vision, sensor fusion, and statutory law to protect drivers from both physical harm and legal liability — entirely on-device.

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

---

## Architecture Constraints

| Constraint | Value |
|---|---|
| Hardware Target | Android mid-range NPU (Dimensity 700 / SD 680 class) |
| Inference Backend | ONNX Runtime NNAPI delegate — INT8 quantized |
| Vision Model | YOLOv8-nano (IDD-trained weights only — no COCO/Cityscapes) |
| IMU Model | TCN (3-layer dilated, receptive field 1.2 s, 6-DOF @100 Hz) |
| Language | AI4Bharat IndicTrans2 / Bhashini offline TTS |
| Cloud Dependency | ZERO (all inference on-device) |
| Privacy | ZKP envelope (Pedersen Commitment) on all telemetry emits |
| Legal Dataset | MoRTH Gazette S.O. 2224(E); TN G.O.(Ms).No.56/2022 |
| Telemetry Schema | iRAD (MoRTH Integrated Road Accident Database, 2022) |

---

## Legal Framework

- **Section 194D** (MVA 2019): Helmet violation — INR 1000 first offence; TN pillion mandate
- **Section 183** (MVA 2019): Speeding — TN zone thresholds; Section 208 challenge trigger
- **Section 208 Protocol**: If a speed camera is detected but no IRC:67-compliant sign exists within 500m upstream → auto-draft legally-binding Audit Request to RTO

See [`schemas/universal_legal_schema.json`](schemas/universal_legal_schema.json) for the full jurisdiction-swappable offence ontology.

---

## Repository Structure

```
NLP/
├── agents/
│   ├── imu_near_miss_detector.py   # P3: TCN sensor fusion, near-miss detection
│   ├── sign_auditor.py             # P3: YOLOv8-nano sign audit [TODO T-009]
│   ├── ble_mesh_broker.py          # P1: BLE V2X hazard sharing [TODO T-008]
│   ├── legal_rag.py                # P2: MVA RAG pipeline [TODO T-010]
│   ├── sec208_drafter.py           # P2: Section 208 audit drafter [TODO T-011]
│   ├── acoustic_ui.py              # P4: Bhashini TTS voice UI [TODO T-012]
│   └── blackspot_geofence.py       # P3: Chennai blackspot geofencing
├── core/
│   ├── agent_bus.py                # P1: JSON-RPC inter-agent bus [TODO T-013]
│   ├── zkp_envelope.py             # P1: Pedersen ZKP telemetry wrap [TODO T-014]
│   └── irad_serializer.py          # P3: iRAD-schema telemetry serializer [TODO T-015]
├── etl/
│   ├── pdf_extractor.py            # P6: PDF text extraction
│   ├── text_chunker.py             # P6: Legal section chunker
│   ├── embedder.py                 # P6: ONNX-INT8 sentence embedder
│   ├── sqlite_vss_ingestor.py      # P6: SQLite-VSS Edge-RAG persistence
│   └── pipeline.py                 # P6: ETL orchestrator
├── api/
│   └── server.py                   # FastAPI REST interface
├── schemas/
│   └── universal_legal_schema.json # ULS-v1.0.0 — IN_TN jurisdiction active
├── raw_data/                       # Source PDFs and CSV
├── tests/                          # pytest test suite
├── docs/
│   └── architecture.md             # Module descriptions, data-flow diagram
├── system_orchestrator.py          # Main entry point
├── vision_audit.py                 # ONNX vision inference engine
├── edge_vector_store.py            # Legal vector store interface
├── section_208_resolver.py         # Section 208 challenge generator
├── offline_tts_manager.py          # Offline TTS manager
├── ingest_legal_pdfs.py            # ETL CLI runner
├── tasks.md                        # Kanban board (P5)
├── CHANGELOG.md                    # Keep-a-Changelog (P5)
├── requirements.txt                # Python dependencies
└── README.md                       # This file
```

---

## Sprint Status

| Sprint | Tasks | Done | In-Progress | Blocked |
|---|---|---|---|---|
| Sprint 0 — Init | 7 | 7 | 0 | 0 |
| Sprint 1 — Core | 8 | 0 | 0 | 3 ERR nodes |
| Sprint 2 — Integration | 5 | 0 | 0 | 0 |

See [`tasks.md`](tasks.md) for full Kanban board.

---

## ERR_DATA_MISSING Nodes

| Code | Missing Data | Blocked Tasks |
|---|---|---|
| ERR-001 | IDD-trained YOLOv8-nano ONNX INT8 checkpoint URI | T-009, T-018 |
| ERR-002 | Bhashini offline TTS model package path | T-012, T-019 |
| ERR-003 | Target Android device ADB fingerprint | T-017, T-018 |

---

## Quick Start (Development)

```bash
# Install Python dependencies (dev mode)
pip install -r requirements.txt

# Run IMU near-miss detector smoke test (deterministic fallback mode)
python agents/imu_near_miss_detector.py

# Run full test suite
VISION_MOCK_MODE=1 python -m pytest tests/ -v
```

> **Note**: `vision_audit.py` runs in **mock mode** (returns empty detections) until you supply
> `VISION_MODEL_PATH` pointing to a valid YOLOv8-nano ONNX INT8 checkpoint.
> See [`docs/architecture.md`](docs/architecture.md) for full environment variable reference.
