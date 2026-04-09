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
├── simulation/                     # ← NEW: camera simulation harness
│   ├── __init__.py
│   ├── camera_ingest.py            # Abstract camera interfaces (Track 1 + Track 2)
│   ├── dashcam_sim.py              # Single front dashcam harness (Track 1)
│   └── config_acer_aspire7.yaml    # Laptop-optimised config
├── schemas/
│   └── universal_legal_schema.json # ULS-v1.0.0 — IN_TN jurisdiction active
├── tests/
│   ├── test_dashcam_sim.py         # ← NEW: Track 1 single-camera tests
│   ├── test_360_camera_scaffolding.py # ← NEW: Track 2 multi-camera scaffold tests
│   └── simulation_india_30min.py   # 30-min India road simulation
├── SAFETY.md                       # ← NEW: safety disclaimers (READ FIRST)
├── tasks.md                        # Kanban board (P5)
├── CHANGELOG.md                    # Keep-a-Changelog (P5)
└── README.md                       # This file
```

---

## ⚠️ Safety Notice

> **This is an experimental research prototype.  All outputs are ADVISORY /
> INFORMATIONAL ONLY.  No driving, braking, or steering decisions are made.
> The driver remains solely responsible for safe vehicle operation at all
> times.**

Read [`SAFETY.md`](SAFETY.md) before running or deploying this software.

---

## Simulation Tracks

### Track 1 — Dashcam-First Quickstart (current)

Run against a single front-facing dashcam video on your laptop.  No
special hardware, model weights, or camera rig required.

### Track 2 — 360-Camera Future Extension (planned)

Add a surround-view rig later by subclassing the `MultiCameraRig` abstract
class — zero changes to existing Track 1 code.

---

## Track 1 — Dashcam Quickstart

> Hardware: Acer Aspire 7, Intel i5-12th gen, RTX 3050 Mobile 4 GB VRAM

### 1. Install dependencies

```bash
pip install numpy pytest
# Optional — only needed for real video files or live camera:
pip install opencv-python
```

### 2. Run smoke test (synthetic frames, no camera or file needed)

```bash
python -m simulation.dashcam_sim --source synthetic --max-frames 30
```

Expected output:

```
── Dashcam Simulation Summary ──────────────────────────────────
{
  "frames_processed": 30,
  "total_advisory_events": ...,
  "source": "synthetic",
  ...
}
```

### 3. Replay a recorded dashcam file

```bash
python -m simulation.dashcam_sim \
  --source file \
  --path /path/to/dashcam.mp4 \
  --target-fps 15 \
  --output-jsonl /tmp/advisory.jsonl
```

### 4. Use the YAML config (recommended for laptops)

Edit `simulation/config_acer_aspire7.yaml` to set your `path:` and then:

```bash
python -m simulation.dashcam_sim --config simulation/config_acer_aspire7.yaml
```

Key YAML settings for RTX 3050 4 GB VRAM:

```yaml
target_fps: 15.0       # comfortable at 640×360; raise to 25 if VRAM < 2.5 GB
resize_width: 640
resize_height: 360
use_gpu: true
num_cpu_threads: 4
```

### 5. Live USB dashcam

```bash
python -m simulation.dashcam_sim --source device --device-index 0
```

Check `nvidia-smi` in a second terminal to monitor VRAM usage.

### 6. Run the test suite

```bash
pytest tests/test_dashcam_sim.py -v
pytest tests/test_360_camera_scaffolding.py -v
```

---

## Track 2 — 360-Camera Future Extension

When a 360-degree camera rig is available, extend the harness by:

1. **Subclass `MultiCameraRig`** in `simulation/camera_ingest.py`:

```python
from simulation.camera_ingest import MultiCameraRig, CalibrationParams

class My360Rig(MultiCameraRig):
    def __init__(self):
        super().__init__()
        # Attach real camera SDK sources to self._sources["front"], ["rear"], …
        for pos in self.STANDARD_POSITIONS:
            self._sources[pos] = MyRealSDKSource(pos)
```

2. **Provide calibration params** per lens:

```python
calibrations = {
    pos: CalibrationParams(
        camera_id=pos,
        fx=700.0, fy=700.0,
        cx=960.0, cy=540.0,
        distortion=[-0.3, 0.1, 0.0, 0.0],
        hfov_deg=195.0,       # fisheye
        pitch_deg=-5.0,
        mount_offset_xyz_m=(0.0, 0.0, 1.8),  # roof mount height
    )
    for pos in MultiCameraRig.STANDARD_POSITIONS
}
rig = My360Rig()
rig.calibrations = calibrations
```

3. **Register** the new source with the factory (optional):

```python
from simulation.camera_ingest import CameraSourceFactory
CameraSourceFactory.register("my_360_sdk", MyRealSDKSource)
```

4. **Run** with the rig:

```python
with My360Rig() as rig:
    for bundle in rig.stream():
        for cam_id, frame in bundle.items():
            process(frame)  # same FrameResult pipeline as Track 1
```

Track 2 tests use `Synthetic360Rig` (no hardware needed):

```bash
pytest tests/test_360_camera_scaffolding.py -v
```

---

## Sprint Status

| Sprint | Tasks | Done | In-Progress | Blocked |
|---|---|---|---|---|
| Sprint 0 — Init | 7 | 7 | 0 | 0 |
| Sprint 1 — Core | 8 | 0 | 0 | 3 ERR nodes |
| Sprint 2 — Integration | 5 | 0 | 0 | 0 |
| Sprint 3 — Simulation | 4 | 4 | 0 | 0 |

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
# Install Python dependencies
pip install numpy pytest

# Run dashcam simulation (synthetic mode — no camera needed)
python -m simulation.dashcam_sim --source synthetic --max-frames 30

# Run IMU near-miss detector smoke test (deterministic fallback mode)
python agents/imu_near_miss_detector.py

# Run full test suite
pytest tests/ -v
```
