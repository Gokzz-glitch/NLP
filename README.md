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

## Quick Start (Development)

```bash
# Install all dependencies (runtime + test + security audit)
pip install -r requirements.txt

# Run IMU near-miss detector smoke test (deterministic fallback mode)
python agents/imu_near_miss_detector.py
```

---

## ⚠️ Safety Disclaimer

**This is a RESEARCH PROTOTYPE — NOT a certified ADAS system.**
See [`SAFETY.md`](SAFETY.md) for mandatory safety disclaimers and prohibited uses before running or deploying this software.

---

## Testing

All tests are in the `tests/` directory and run with [pytest](https://docs.pytest.org).

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all unit + integration tests
python -m pytest tests/ -q

# Run specific test suites
python -m pytest tests/test_core.py              # Core bus / ZKP / iRAD
python -m pytest tests/test_agents.py            # All agents
python -m pytest tests/test_orchestrator.py      # End-to-end orchestration
python -m pytest tests/test_property_based.py    # Property-based (Hypothesis)
python -m pytest tests/test_fuzz_inputs.py       # Adversarial / fuzz inputs
python -m pytest tests/test_stress_enterprise.py # Concurrent stress tests
python -m pytest tests/test_etl_pipeline.py      # ETL PDF ingestion pipeline
```

### Test Categories

| Suite | Description |
|---|---|
| `test_core.py` | AgentBus pub/sub, ZKP Pedersen envelope, iRAD schema |
| `test_agents.py` | All 6 persona agents (LegalRAG, Sec208, SignAuditor, BLE, TTS, Blackspot) |
| `test_imu_near_miss_detector.py` | IMU buffer, TCN feature extractor, severity classifier |
| `test_orchestrator.py` | Full bus-driven pipeline integration |
| `test_property_based.py` | Invariant testing with Hypothesis (ZKP round-trip, iRAD completeness, severity monotonicity, BLE MTU) |
| `test_fuzz_inputs.py` | Adversarial / malformed inputs to API, agents, and parsers |
| `test_stress_enterprise.py` | SQLite WAL concurrency, async API load |

---

## Simulation Harness

The `sim/` package provides an offline evaluation harness that runs the full pipeline on synthetic or recorded video input and emits JSON metrics.

```bash
# Synthetic simulation (no video clip needed) — 60-second urban scenario
python sim/run_video_sim.py --synthetic --duration 60 --metrics-out /tmp/metrics.json

# Real dashcam video (requires OpenCV: pip install opencv-python-headless)
python sim/run_video_sim.py --video 360-cam.mp4 \
       --scenario national_highway_night \
       --vehicle two_wheeler_100cc \
       --metrics-out /tmp/nh_night_metrics.json

# Sweep ALL 100 scenario × vehicle combinations (takes ~5 min)
python sim/run_video_sim.py --synthetic --all-scenarios --duration 10 \
       --metrics-out /tmp/all_scenarios.json

# Run the 30-minute India omnibus simulation (IMU only, terminal report)
python tests/simulation_india_30min.py
```

### Available Scenarios (`sim/scenarios.py`)

| Key | Description |
|---|---|
| `national_highway_day` | 4/6-lane NH; 90 km/h; clear |
| `national_highway_night` | NH at night; glare; reduced grip |
| `national_highway_rain` | NH monsoon; aquaplaning risk |
| `state_highway_day` | 2-lane SH; pedestrians + animals |
| `urban_arterial_day` | Chennai peak-hour; gridlock |
| `urban_arterial_night_glare` | Urban night + headlight glare |
| `rural_single_lane` | Narrow rural road; large potholes |
| `mountain_ghat_day` | Nilgiris hairpins; mist; steep |
| `construction_zone` | Active NHAI construction; debris |
| `school_zone_peak` | Dense pedestrian crossings; 25 km/h |

### Metrics Output

```json
{
  "scenario_name": "Urban Arterial — Chennai Peak Hour",
  "vehicle_class": "Two-Wheeler (<125cc)",
  "avg_latency_ms": 0.15,
  "p95_latency_ms": 1.45,
  "avg_fps": 6471.0,
  "peak_memory_mb": 12.3,
  "detection_counts": {"speed_camera": 1, "speed_limit_sign": 8},
  "near_miss_counts": {"CRITICAL": 0, "HIGH": 1},
  "sec208_triggers": 1,
  "disclaimer": "SIMULATION ONLY — NOT CERTIFIED ADAS — DO NOT USE TO MAKE REAL DRIVING DECISIONS"
}
```

---

## CI / CD

GitHub Actions workflow is at [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

| Job | Trigger | Includes |
|---|---|---|
| **Lint** | Every push / PR | flake8, mypy (advisory) |
| **Tests** | Every push / PR | Full test matrix (Python 3.10, 3.11) |
| **Simulation** | After tests pass | 30-min simulation + video harness smoke test |
| **Security** | Every push / PR | pip-audit dependency CVE scan, trufflehog secret scan |

### Run CI locally

```bash
# Lint
flake8 . --max-line-length=120 --extend-ignore=E203,W503,E501

# Full test suite
python -m pytest tests/ -v

# Dependency audit
pip-audit

# Simulation smoke-test
python sim/run_video_sim.py --synthetic --duration 10 --metrics-out /tmp/smoke.json
```

---

## Security Guidance

- **No secrets in code**: all keys/tokens loaded from env vars (`.env`, never committed).
- **`.gitignore`** excludes `*.pem`, `*.key`, `*.onnx`, `*.env`, `zkp_keys/`, `secrets/`.
- **Razorpay webhook**: HMAC-SHA256 verified in `api/server.py` before processing.
- **SQLite WAL**: concurrent write safety tested in `tests/test_stress_enterprise.py`.
- Run `pip-audit` regularly; update `requirements.txt` pinned versions when advisories are published.

