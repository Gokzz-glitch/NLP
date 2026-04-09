"""
tests/test_dashcam_sim.py
=========================
Comprehensive tests for the single front-facing dashcam simulation path
(Track 1).  No real camera, no model weights, no display required.

All tests use SyntheticFrameSource so they pass in any CI environment.
"""

import os
import sys
import json
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation.camera_ingest import (
    CalibrationParams,
    CameraFrame,
    CameraSource,
    DashcamFileSource,
    SyntheticFrameSource,
    CameraSourceFactory,
)
from simulation.dashcam_sim import (
    DashcamSimConfig,
    DashcamSimulator,
    FrameResult,
    _StubDetector,
    _generate_advisory_events,
)


# ─────────────────────────────────────────────────────────────────────────────
# CalibrationParams
# ─────────────────────────────────────────────────────────────────────────────

class TestCalibrationParams:
    def test_default_camera_id(self):
        cal = CalibrationParams()
        assert cal.camera_id == "front"

    def test_custom_params(self):
        cal = CalibrationParams(
            camera_id="front",
            fx=800.0, fy=800.0,
            cx=320.0, cy=240.0,
            distortion=[0.1, -0.05, 0.0, 0.0],
            hfov_deg=120.0,
        )
        assert cal.fx == 800.0
        assert len(cal.distortion) == 4
        assert cal.hfov_deg == 120.0

    def test_default_distortion_is_zero(self):
        cal = CalibrationParams()
        assert all(v == 0.0 for v in cal.distortion)

    def test_mount_offset_default(self):
        cal = CalibrationParams()
        assert cal.mount_offset_xyz_m == (0.0, 0.0, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# CameraFrame
# ─────────────────────────────────────────────────────────────────────────────

class TestCameraFrame:
    def test_creation(self):
        import numpy as np
        bgr = np.zeros((480, 640, 3), dtype=np.uint8)
        frame = CameraFrame(
            camera_id="front",
            frame_index=0,
            timestamp_s=0.033,
            bgr=bgr,
        )
        assert frame.camera_id == "front"
        assert frame.frame_index == 0
        assert frame.bgr.shape == (480, 640, 3)

    def test_metadata_defaults_empty(self):
        import numpy as np
        frame = CameraFrame(
            camera_id="front",
            frame_index=1,
            timestamp_s=1.0,
            bgr=np.zeros((10, 10, 3), dtype=np.uint8),
        )
        assert frame.metadata == {}


# ─────────────────────────────────────────────────────────────────────────────
# SyntheticFrameSource (primary CI source)
# ─────────────────────────────────────────────────────────────────────────────

class TestSyntheticFrameSource:
    def test_context_manager_yields_frames(self):
        src = SyntheticFrameSource(max_frames=5)
        frames = []
        with src:
            for f in src.stream():
                frames.append(f)
        assert len(frames) == 5

    def test_frame_shape(self):
        src = SyntheticFrameSource(width=320, height=240, max_frames=2)
        with src:
            frame = src.read_frame()
        assert frame is not None
        assert frame.bgr.shape == (240, 320, 3)

    def test_frames_are_incrementally_indexed(self):
        src = SyntheticFrameSource(max_frames=10)
        with src:
            frames = list(src.stream())
        indices = [f.frame_index for f in frames]
        assert indices == list(range(10))

    def test_timestamps_increase(self):
        src = SyntheticFrameSource(fps=10, max_frames=5)
        with src:
            frames = list(src.stream())
        ts = [f.timestamp_s for f in frames]
        assert all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))

    def test_exhaust_returns_none(self):
        src = SyntheticFrameSource(max_frames=2)
        with src:
            src.read_frame()
            src.read_frame()
            assert src.read_frame() is None

    def test_metadata_synthetic_flag(self):
        src = SyntheticFrameSource(max_frames=1)
        with src:
            frame = src.read_frame()
        assert frame is not None
        assert frame.metadata.get("synthetic") is True

    def test_not_multi_camera(self):
        src = SyntheticFrameSource(max_frames=1)
        assert src.is_multi_camera is False

    def test_camera_id_propagated(self):
        src = SyntheticFrameSource(camera_id="front_custom", max_frames=1)
        with src:
            frame = src.read_frame()
        assert frame is not None
        assert frame.camera_id == "front_custom"

    def test_consecutive_frames_differ(self):
        import numpy as np
        src = SyntheticFrameSource(max_frames=5)
        with src:
            frames = list(src.stream())
        # Frames cycle through palettes so at least some should differ
        diffs = [
            not np.array_equal(frames[i].bgr, frames[i + 1].bgr)
            for i in range(len(frames) - 1)
        ]
        assert any(diffs), "Expected consecutive frames to differ"


# ─────────────────────────────────────────────────────────────────────────────
# CameraSourceFactory
# ─────────────────────────────────────────────────────────────────────────────

class TestCameraSourceFactory:
    def test_create_synthetic(self):
        src = CameraSourceFactory.create("synthetic", max_frames=2)
        assert isinstance(src, SyntheticFrameSource)

    def test_unknown_source_raises(self):
        with pytest.raises(KeyError, match="Unknown camera source"):
            CameraSourceFactory.create("nonexistent_source")

    def test_register_and_create_custom(self):
        class _MySource(SyntheticFrameSource):
            pass

        CameraSourceFactory.register("_test_custom", _MySource)
        src = CameraSourceFactory.create("_test_custom", max_frames=1)
        assert isinstance(src, _MySource)

    def test_dashcam_file_registered(self):
        # DashcamFileSource is pre-registered but we don't open it (no file)
        src = CameraSourceFactory.create("dashcam_file", path="/nonexistent.mp4")
        assert isinstance(src, DashcamFileSource)


# ─────────────────────────────────────────────────────────────────────────────
# DashcamSimConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestDashcamSimConfig:
    def test_defaults(self):
        cfg = DashcamSimConfig()
        assert cfg.source == "synthetic"
        assert cfg.target_fps == 15.0
        assert cfg.detection_confidence_min == 0.45
        assert cfg.use_gpu is True

    def test_custom_fields(self):
        cfg = DashcamSimConfig(
            source="file",
            path="/tmp/dashcam.mp4",
            max_frames=100,
            target_fps=10.0,
            resize_width=320,
            resize_height=180,
        )
        assert cfg.source == "file"
        assert cfg.max_frames == 100
        assert cfg.resize_width == 320


# ─────────────────────────────────────────────────────────────────────────────
# _StubDetector
# ─────────────────────────────────────────────────────────────────────────────

class TestStubDetector:
    def test_returns_list(self):
        import numpy as np
        det = _StubDetector()
        bgr = np.zeros((360, 640, 3), dtype=np.uint8)
        result = det.predict(bgr)
        assert isinstance(result, list)

    def test_detections_have_required_keys(self):
        import numpy as np
        det = _StubDetector()
        bgr = np.full((360, 640, 3), 128, dtype=np.uint8)
        detections = det.predict(bgr)
        for d in detections:
            assert "label" in d
            assert "confidence" in d
            assert "bbox_xywh" in d
            assert len(d["bbox_xywh"]) == 4

    def test_confidence_above_threshold(self):
        import numpy as np
        det = _StubDetector(conf_threshold=0.45)
        bgr = np.full((360, 640, 3), 200, dtype=np.uint8)
        detections = det.predict(bgr)
        for d in detections:
            assert d["confidence"] >= 0.45

    def test_deterministic_for_same_frame(self):
        import numpy as np
        det = _StubDetector()
        bgr = np.full((360, 640, 3), 77, dtype=np.uint8)
        result_a = det.predict(bgr)
        result_b = det.predict(bgr)
        assert result_a == result_b


# ─────────────────────────────────────────────────────────────────────────────
# Advisory event generation
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvisoryEvents:
    def test_speed_camera_triggers_advisory(self):
        detections = [{"label": "speed_camera", "confidence": 0.8, "bbox_xywh": [0, 0, 50, 50]}]
        events = _generate_advisory_events(detections)
        assert any("speed" in e.lower() for e in events)

    def test_pothole_triggers_advisory(self):
        detections = [{"label": "pothole", "confidence": 0.7, "bbox_xywh": [10, 10, 30, 20]}]
        events = _generate_advisory_events(detections)
        assert any("pothole" in e.lower() or "hazard" in e.lower() for e in events)

    def test_pedestrian_triggers_advisory(self):
        detections = [{"label": "pedestrian", "confidence": 0.9, "bbox_xywh": [0, 0, 50, 100]}]
        events = _generate_advisory_events(detections)
        assert any("pedestrian" in e.lower() for e in events)

    def test_unknown_label_no_advisory(self):
        detections = [{"label": "tree", "confidence": 0.95, "bbox_xywh": [0, 0, 100, 200]}]
        events = _generate_advisory_events(detections)
        assert events == []

    def test_empty_detections_no_advisory(self):
        events = _generate_advisory_events([])
        assert events == []

    def test_multiple_labels_multiple_advisories(self):
        detections = [
            {"label": "speed_camera", "confidence": 0.8, "bbox_xywh": [0, 0, 50, 50]},
            {"label": "pothole", "confidence": 0.75, "bbox_xywh": [100, 100, 30, 20]},
        ]
        events = _generate_advisory_events(detections)
        assert len(events) == 2


# ─────────────────────────────────────────────────────────────────────────────
# DashcamSimulator — synthetic path (full integration)
# ─────────────────────────────────────────────────────────────────────────────

class TestDashcamSimulator:
    def _make_sim(self, max_frames: int = 10, **kwargs) -> DashcamSimulator:
        cfg = DashcamSimConfig(
            source="synthetic",
            max_frames=max_frames,
            target_fps=0,  # no throttle in tests
            **kwargs,
        )
        return DashcamSimulator(cfg)

    def test_run_returns_results(self):
        sim = self._make_sim(max_frames=5)
        results = sim.run()
        assert len(results) == 5

    def test_result_type(self):
        sim = self._make_sim(max_frames=3)
        results = sim.run()
        assert all(isinstance(r, FrameResult) for r in results)

    def test_frame_indices_sequential(self):
        sim = self._make_sim(max_frames=8)
        results = sim.run()
        assert [r.frame_index for r in results] == list(range(8))

    def test_camera_id_is_front(self):
        sim = self._make_sim(max_frames=4)
        results = sim.run()
        assert all(r.camera_id == "front" for r in results)

    def test_inference_ms_positive(self):
        sim = self._make_sim(max_frames=5)
        results = sim.run()
        assert all(r.inference_ms >= 0.0 for r in results)

    def test_frame_dimensions_match_config(self):
        sim = self._make_sim(max_frames=3, resize_width=320, resize_height=180)
        results = sim.run()
        # Synthetic source uses config dimensions directly
        for r in results:
            assert r.frame_width == 320
            assert r.frame_height == 180

    def test_advisory_events_are_strings(self):
        sim = self._make_sim(max_frames=10)
        results = sim.run()
        for r in results:
            assert all(isinstance(e, str) for e in r.advisory_events)

    def test_detections_list_structure(self):
        sim = self._make_sim(max_frames=10)
        results = sim.run()
        for r in results:
            for d in r.detections:
                assert "label" in d
                assert "confidence" in d
                assert "bbox_xywh" in d

    def test_summary_keys_present(self):
        sim = self._make_sim(max_frames=5)
        sim.run()
        summary = sim.summary()
        assert "frames_processed" in summary
        assert "total_advisory_events" in summary
        assert "avg_inference_ms" in summary
        assert "source" in summary
        assert summary["frames_processed"] == 5

    def test_jsonl_output(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
            outpath = fh.name
        try:
            cfg = DashcamSimConfig(
                source="synthetic",
                max_frames=4,
                target_fps=0,
                output_jsonl=outpath,
            )
            sim = DashcamSimulator(cfg)
            sim.run()

            with open(outpath) as fh:
                lines = [json.loads(line) for line in fh if line.strip()]
            assert len(lines) == 4
            for line in lines:
                assert "frame_index" in line
                assert "advisory_events" in line
        finally:
            os.unlink(outpath)

    def test_invalid_source_raises(self):
        cfg = DashcamSimConfig(source="bogus_source", max_frames=1, target_fps=0)
        sim = DashcamSimulator(cfg)
        with pytest.raises(ValueError, match="Unknown source"):
            sim.run()

    def test_file_source_requires_path(self):
        cfg = DashcamSimConfig(source="file", path="", max_frames=1, target_fps=0)
        sim = DashcamSimulator(cfg)
        with pytest.raises(ValueError, match="path must be set"):
            sim.run()

    def test_custom_detector_used(self):
        """Verify the harness calls a custom injected detector."""
        calls = []

        class _RecordingDetector:
            def predict(self, bgr):
                calls.append(bgr.shape)
                return []

        cfg = DashcamSimConfig(source="synthetic", max_frames=3, target_fps=0)
        sim = DashcamSimulator(cfg, detector=_RecordingDetector())
        sim.run()
        assert len(calls) == 3

    def test_frame_result_to_dict(self):
        result = FrameResult(
            frame_index=0, timestamp_s=0.0, camera_id="front",
            detections=[], advisory_events=["ADVISORY: test"],
            inference_ms=2.5, frame_width=640, frame_height=360,
        )
        d = result.to_dict()
        assert d["frame_index"] == 0
        assert d["advisory_events"] == ["ADVISORY: test"]
        assert d["inference_ms"] == 2.5

    # -- safety-critical property tests --

    def test_no_control_outputs_in_results(self):
        """Advisory events must never contain steering/braking control commands."""
        FORBIDDEN = ["steer", "brake", "accelerate", "control", "override"]
        sim = self._make_sim(max_frames=20)
        results = sim.run()
        for r in results:
            for ev in r.advisory_events:
                ev_lower = ev.lower()
                for word in FORBIDDEN:
                    assert word not in ev_lower, (
                        f"Advisory event contains forbidden control word {word!r}: {ev!r}"
                    )

    def test_advisory_events_contain_advisory_prefix(self):
        """All advisory events must start with 'ADVISORY:' to prevent misinterpretation."""
        sim = self._make_sim(max_frames=30)
        results = sim.run()
        for r in results:
            for ev in r.advisory_events:
                assert ev.startswith("ADVISORY:"), (
                    f"Event missing 'ADVISORY:' prefix: {ev!r}"
                )
