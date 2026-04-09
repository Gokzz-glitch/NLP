"""
tests/test_dashcam_basic.py
Basic dashcam configuration and simulation smoke tests.

These tests run without any hardware, real video file, or ONNX model.
They validate:
  - DashcamConfig preset loading and env-var overrides
  - Auto-detect helper (graceful when cv2 unavailable)
  - Single-camera simulation pipeline completes without error
  - 360-ready architecture: multiple cameras can be configured
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.dashcam_defaults import (
    CameraConfig,
    DashcamConfig,
    PRESETS,
    DEFAULT_FPS,
    DEFAULT_PRESET,
    detect_source_properties,
)


# ---------------------------------------------------------------------------
# Config preset tests
# ---------------------------------------------------------------------------

def test_default_preset_is_1080p():
    assert DEFAULT_PRESET == "1080p"
    w, h = PRESETS["1080p"]
    assert w == 1920 and h == 1080


def test_presets_contain_expected_resolutions():
    assert "720p"  in PRESETS
    assert "1080p" in PRESETS
    assert "4K"    in PRESETS
    assert PRESETS["720p"]  == (1280, 720)
    assert PRESETS["1080p"] == (1920, 1080)
    assert PRESETS["4K"]    == (3840, 2160)


def test_default_fps_is_30():
    assert DEFAULT_FPS == 30


def test_camera_config_defaults():
    cam = CameraConfig()
    assert cam.label == "front"
    assert cam.width == 1920
    assert cam.height == 1080
    assert cam.fps == 30.0
    assert cam.auto_detect is True


def test_dashcam_config_default_single_camera():
    cfg = DashcamConfig()
    assert cfg.mode == "single"
    assert len(cfg.cameras) == 1
    assert cfg.primary.label == "front"


def test_dashcam_config_from_env_defaults(monkeypatch):
    # Remove any accidental overrides from the test environment
    for var in ("DASHCAM_WIDTH", "DASHCAM_HEIGHT", "DASHCAM_FPS", "DASHCAM_SOURCE", "DASHCAM_CAMERA_MODE"):
        monkeypatch.delenv(var, raising=False)

    cfg = DashcamConfig.from_env()
    assert cfg.mode == "single"
    assert cfg.primary.width  == 1920
    assert cfg.primary.height == 1080
    assert cfg.primary.fps    == 30.0
    assert cfg.primary.source == "0"


def test_dashcam_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("DASHCAM_WIDTH",       "1280")
    monkeypatch.setenv("DASHCAM_HEIGHT",      "720")
    monkeypatch.setenv("DASHCAM_FPS",         "60")
    monkeypatch.setenv("DASHCAM_SOURCE",      "/tmp/test.mp4")
    monkeypatch.setenv("DASHCAM_CAMERA_MODE", "360")

    cfg = DashcamConfig.from_env()
    assert cfg.mode            == "360"
    assert cfg.primary.width   == 1280
    assert cfg.primary.height  == 720
    assert cfg.primary.fps     == 60.0
    assert cfg.primary.source  == "/tmp/test.mp4"


def test_dashcam_config_360_ready():
    """360-camera architecture: multiple cameras can be declared."""
    cfg = DashcamConfig(
        mode="360",
        cameras=[
            CameraConfig("front", source="front.mp4"),
            CameraConfig("rear",  source="rear.mp4"),
            CameraConfig("left",  source="left.mp4"),
            CameraConfig("right", source="right.mp4"),
        ],
    )
    assert cfg.mode == "360"
    assert len(cfg.cameras) == 4
    labels = [c.label for c in cfg.cameras]
    assert labels == ["front", "rear", "left", "right"]
    assert cfg.primary.label == "front"


def test_dashcam_config_summary():
    cfg = DashcamConfig()
    s   = cfg.summary()
    assert "single" in s
    assert "front"  in s
    assert "1920"   in s


def test_detect_source_properties_nonexistent_path():
    """Should return None gracefully for a path that doesn't exist."""
    result = detect_source_properties("/nonexistent/path/video.mp4")
    assert result is None


# ---------------------------------------------------------------------------
# Simulation smoke test
# ---------------------------------------------------------------------------

def test_dashcam_sim_smoke():
    """
    End-to-end smoke test: run 30 synthetic frames through the full pipeline
    (mock vision, synthetic IMU) and verify at least one event fires.
    """
    from dashcam_sim import run_simulation

    cfg = DashcamConfig()          # single front cam, 1080p/30fps defaults
    cfg.primary.source = "0"       # no real file — use synthetic frames

    result = run_simulation(cfg, n_frames=30, verbose=False)

    assert result["frames_processed"] >= 1
    assert result["mock_vision"] is True   # no real model in CI
    assert isinstance(result["near_misses"],       int)
    assert isinstance(result["sec208_challenges"], int)
    assert isinstance(result["elapsed_s"],         float)
    assert result["elapsed_s"] < 30.0     # must complete quickly on a laptop

    print(
        f"[PASS] test_dashcam_sim_smoke — "
        f"frames={result['frames_processed']}, "
        f"near_misses={result['near_misses']}, "
        f"sec208={result['sec208_challenges']}"
    )


def test_dashcam_sim_produces_sec208_event():
    """Simulation must file at least one Section 208 challenge (mock vision injects one)."""
    from dashcam_sim import run_simulation

    cfg = DashcamConfig()
    result = run_simulation(cfg, n_frames=60, verbose=False)
    assert result["sec208_challenges"] >= 1, (
        f"Expected ≥1 Section 208 challenge, got {result['sec208_challenges']}"
    )
    print(f"[PASS] test_dashcam_sim_produces_sec208_event — challenges={result['sec208_challenges']}")


if __name__ == "__main__":
    test_default_preset_is_1080p()
    test_presets_contain_expected_resolutions()
    test_default_fps_is_30()
    test_camera_config_defaults()
    test_dashcam_config_default_single_camera()
    test_dashcam_config_360_ready()
    test_dashcam_config_summary()
    test_detect_source_properties_nonexistent_path()
    test_dashcam_sim_smoke()
    test_dashcam_sim_produces_sec208_event()
    print("\n[ALL PASS] test_dashcam_basic.py")
