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
│   └── acoustic_ui.py              # P4: Bhashini TTS voice UI [TODO T-012]
├── core/
│   ├── agent_bus.py                # P1: JSON-RPC inter-agent bus [TODO T-013]
│   ├── zkp_envelope.py             # P1: Pedersen ZKP telemetry wrap [TODO T-014]
│   └── irad_serializer.py          # P3: iRAD-schema telemetry serializer [TODO T-015]
├── schemas/
│   └── universal_legal_schema.json # ULS-v1.0.0 — IN_TN jurisdiction active
├── tests/
├── docs/
├── tasks.md                        # Kanban board (P5)
├── CHANGELOG.md                    # Keep-a-Changelog (P5)
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

## Quick Start — Basic / Laptop (Minimal)

Runs entirely on your laptop with **no camera hardware, no ONNX model, and no cloud
connection** — synthetic frames and mock vision are used automatically.

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Run the basic dashcam simulation (30 synthetic frames, mock vision)
python dashcam_sim.py

# 3. Run the basic test suite
python -m pytest tests/test_agents.py tests/test_core.py \
                 tests/test_orchestrator.py tests/test_dashcam_basic.py -v
```

### Using a real dashcam video file

```bash
# Any MP4 / AVI file — resolution and FPS are auto-detected
python dashcam_sim.py --source my_drive.mp4

# Override preset or frame count
python dashcam_sim.py --source my_drive.mp4 --preset 720p --frames 120
```

### Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `DASHCAM_SOURCE` | `0` (synthetic) | Video file path or device index |
| `DASHCAM_WIDTH` | `1920` | Frame width override (pixels) |
| `DASHCAM_HEIGHT` | `1080` | Frame height override (pixels) |
| `DASHCAM_FPS` | `30` | Frame rate override |
| `DASHCAM_CAMERA_MODE` | `single` | `single` (dashcam) or `360` |
| `VISION_MOCK_MODE` | `0` | Set `1` to force mock vision (CI/no-model) |
| `VISION_MODEL_PATH` | *(auto)* | Path to custom YOLOv8 ONNX model |

### 360-camera (future / architecture placeholder)

The architecture is 360-ready. To add cameras, pass multiple `CameraConfig`
objects — each stream is processed independently and events merge on the bus:

```python
from config.dashcam_defaults import DashcamConfig, CameraConfig

cfg = DashcamConfig(
    mode="360",
    cameras=[
        CameraConfig("front", source="front.mp4"),
        CameraConfig("rear",  source="rear.mp4"),
    ],
)
```

> **SAFETY NOTICE** — This is a research/simulation tool. It is **not** certified
> for any safety-critical or real-vehicle deployment. The driver remains solely
> responsible for vehicle operation at all times.

---

## Quick Start (Development — Legacy)

```bash
# Install Python dependencies (dev mode)
pip install torch onnxruntime numpy

# Run IMU near-miss detector smoke test (deterministic fallback mode)
python agents/imu_near_miss_detector.py
```
