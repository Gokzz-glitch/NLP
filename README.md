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
| Vision Model | YOLOv8-nano (Roboflow Indian road-sign dataset — IDD checkpoint pending ERR-001) |
| IMU Model | TCN (3-layer dilated, receptive field 1.2 s, 6-DOF @100 Hz) |
| Language | AI4Bharat IndicTrans2 / Bhashini offline TTS |
| Cloud Dependency | ZERO (all inference on-device) |
| Privacy | SHA3-256 coordinate commitment + coordinate coarsening (≈500 m grid). Full ZKP circuit (Groth16/Pedersen) on T-014 backlog. |
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
│   ├── sign_auditor.py             # P3: YOLOv8-nano sign audit + 500m GPS check
│   ├── ble_mesh_broker.py          # P1: BLE V2X hazard sharing (HMAC + AES-128-CCM)
│   ├── acoustic_ui.py              # P4: TTS voice UI (Bhashini Tamil + pyttsx3 fallback)
│   ├── legal_rag.py                # P2: MVA RAG pipeline [TODO T-010]
│   └── sec208_drafter.py           # P2: Section 208 audit drafter [TODO T-011]
├── core/
│   ├── agent_bus.py                # P1: JSON-RPC inter-agent pub/sub bus
│   ├── zkp_envelope.py             # P1: SHA3-256 GPS commitment (ZKP circuit T-014)
│   ├── bhashini_tts.py             # P4: Bhashini ULCA REST TTS client (ERR-002 resolved)
│   └── irad_serializer.py          # P3: iRAD V-NMS-01 telemetry serialiser
├── scripts/
│   ├── download_models.py          # ERR-001: vision model download (Roboflow/HF/ultralytics)
│   └── deploy_android.py           # ERR-003: Android ADB deployment, dynamic device discovery
├── models/
│   └── vision/
│       ├── README.md               # ERR-001 setup instructions
│       └── indian_traffic_yolov8.onnx  ← not committed; run scripts/download_models.py
├── schemas/
│   └── universal_legal_schema.json # ULS-v1.0.0 — IN_TN jurisdiction active
├── tests/
├── docs/
├── .env.example                    # All required environment variables
├── tasks.md                        # Kanban board (P5)
├── CHANGELOG.md                    # Keep-a-Changelog (P5)
└── README.md                       # This file
```

---

## Sprint Status

| Sprint | Tasks | Done | In-Progress | Blocked |
|---|---|---|---|---|
| Sprint 0 — Init | 7 | 7 | 0 | 0 |
| Sprint 1 — Core | 8 | 5 | 0 | 3 ERR nodes |
| Sprint 2 — Integration | 5 | 0 | 0 | 0 |

See [`tasks.md`](tasks.md) for full Kanban board.

---

## ERR_DATA_MISSING Nodes

| Code | Missing Data | Blocked Tasks |
|---|---|---|
| ERR-001 | IDD-trained YOLOv8-nano ONNX INT8 checkpoint URI | T-009, T-018 | **RESOLVED** — `scripts/download_models.py` (Roboflow → HF → ultralytics fallback). See `models/vision/README.md`. |
| ERR-002 | Bhashini offline TTS model package path | T-012, T-019 | **RESOLVED** — `core/bhashini_tts.py` implements Bhashini ULCA REST API; set `BHASHINI_USER_ID` + `BHASHINI_API_KEY` in `.env`. |
| ERR-003 | Target Android device ADB fingerprint | T-017, T-018 | **RESOLVED** — `scripts/deploy_android.py` discovers devices dynamically; no hardcoded fingerprint. |

---

## Quick Start (Development)

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env:  set ROBOFLOW_API_KEY, BHASHINI_USER_ID, BHASHINI_API_KEY as available

# 3. Download the vision model (ERR-001)
#    Option A: with Roboflow API key
python scripts/download_models.py --source roboflow
#    Option B: from HuggingFace (no key required for public repo)
python scripts/download_models.py --source hf
#    Option C: base YOLOv8n for pipeline smoke-tests only (wrong class labels)
python scripts/download_models.py --source ultralytics

# 4. Run the full test suite
python -m pytest tests/ --ignore=tests/simulation_india_30min.py -q

# 5. Start the API server
uvicorn api.server:app --reload

# 6. (Optional) Deploy models to Android (ERR-003)
python scripts/deploy_android.py --check-nnapi
python scripts/deploy_android.py --push-models
```

### Tamil TTS setup (ERR-002)

Set `BHASHINI_USER_ID` and `BHASHINI_API_KEY` in `.env` (register at https://bhashini.gov.in)
to enable real Tamil synthesis via the Bhashini ULCA REST API.

Without credentials the system falls back to pyttsx3 → espeak English.

