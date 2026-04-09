# CHANGELOG: SmartSalai Edge-Sentinel

## [0.2.0-alpha] - 2026-04-09
### Added
- `simulation/` package: camera-ingest abstraction layer.
  - `camera_ingest.py`: abstract `CameraSource` ABC, `CameraFrame` dataclass,
    `CalibrationParams` placeholder, `DashcamFileSource`, `DashcamDeviceSource`,
    `SyntheticFrameSource` (CI-safe, no hardware), `MultiCameraRig` + `Synthetic360Rig`
    scaffolding for Track 2 360-camera support, `CameraSourceFactory` registry.
  - `dashcam_sim.py`: single front-facing dashcam simulation harness (Track 1);
    supports file, device, and synthetic sources; JSONL output; advisory-only events.
  - `config_acer_aspire7.yaml`: laptop-optimised config for Acer Aspire 7 RTX 3050 4 GB.
- `tests/test_dashcam_sim.py`: 30+ tests for Track 1 single-camera path including
  safety-critical property tests (advisory-only prefix enforcement, no control outputs).
- `tests/test_360_camera_scaffolding.py`: 25+ tests for Track 2 multi-camera
  scaffolding (no real 360 hardware required).
- `SAFETY.md`: safety disclaimers, advisory-only guardrails, responsible use requirements.
- README updated with two-track quickstart:
  - Track 1: Dashcam-first quickstart (Acer Aspire 7).
  - Track 2: 360-camera future extension pattern.

## [0.1.0-alpha] - 2026-03-31
### Initialized
- Project structure for multi-agent orchestration.
- Persona 5 DevOps tracking (Kanban).
- Universal Legal Schema (ULS) defined.
- BLE Mesh Protocol schema established.

### Changed
- Transitioned to STRICT REAL-DATA MODE.
- Persona 6 directives updated for MVA/TN_GO PDF ingestion.
- Vision pipeline updated for indian_traffic_yolov8.onnx deployment.

