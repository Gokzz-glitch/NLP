"""
tests/test_360_camera_scaffolding.py
=====================================
Tests for the Track 2 (360-degree / multi-camera) scaffolding.

No real 360-degree hardware is required — ``Synthetic360Rig`` provides
six synthetic camera sources that satisfy the full multi-camera contract.

These tests verify:
  1. The abstract ``MultiCameraRig`` interface is correctly structured.
  2. ``Synthetic360Rig`` works end-to-end as a drop-in 360-camera stub.
  3. Adding a real 360 source (Track 2) requires only subclassing — no
     changes to the rest of the stack.
  4. Calibration placeholders are wired through for each lens.
  5. The ``CameraSourceFactory`` extension point is functional.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from simulation.camera_ingest import (
    CalibrationParams,
    CameraFrame,
    CameraSource,
    CameraSourceFactory,
    MultiCameraRig,
    Synthetic360Rig,
    SyntheticFrameSource,
)


# ─────────────────────────────────────────────────────────────────────────────
# MultiCameraRig interface
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiCameraRigInterface:
    def test_is_multi_camera_true(self):
        rig = Synthetic360Rig(max_frames=2)
        assert rig.is_multi_camera is True

    def test_single_source_is_not_multi_camera(self):
        src = SyntheticFrameSource(max_frames=2)
        assert src.is_multi_camera is False

    def test_camera_ids_returns_list(self):
        rig = Synthetic360Rig(max_frames=2)
        ids = rig.camera_ids
        assert isinstance(ids, list)
        assert len(ids) > 0

    def test_standard_positions_covered(self):
        rig = Synthetic360Rig(max_frames=2)
        ids = set(rig.camera_ids)
        expected = set(MultiCameraRig.STANDARD_POSITIONS)
        assert ids == expected, f"Missing positions: {expected - ids}"

    def test_context_manager_lifecycle(self):
        """open() and release() must be callable without errors."""
        rig = Synthetic360Rig(max_frames=2)
        with rig:
            pass  # no exception expected

    def test_empty_rig_read_all_returns_none(self):
        """A rig with no sources should return None."""
        rig = MultiCameraRig()
        # _sources is empty → read_all_frames should return None
        result = rig.read_all_frames()
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic360Rig — frame-by-frame behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestSynthetic360Rig:
    def test_stream_yields_bundles(self):
        rig = Synthetic360Rig(max_frames=3)
        bundles = []
        with rig:
            for bundle in rig.stream():
                bundles.append(bundle)
        assert len(bundles) == 3

    def test_bundle_has_all_positions(self):
        rig = Synthetic360Rig(max_frames=1)
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        expected = set(MultiCameraRig.STANDARD_POSITIONS)
        assert set(bundle.keys()) == expected

    def test_each_frame_is_camera_frame(self):
        rig = Synthetic360Rig(max_frames=1)
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        for cid, frame in bundle.items():
            assert isinstance(frame, CameraFrame)

    def test_camera_ids_match_bundle_keys(self):
        rig = Synthetic360Rig(max_frames=1)
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        assert set(rig.camera_ids) == set(bundle.keys())

    def test_frame_dimensions_configurable(self):
        rig = Synthetic360Rig(width=160, height=120, max_frames=1)
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        for cid, frame in bundle.items():
            assert frame.bgr.shape == (120, 160, 3), (
                f"Wrong shape for camera {cid}: {frame.bgr.shape}"
            )

    def test_exhaustion_returns_none(self):
        rig = Synthetic360Rig(max_frames=2)
        with rig:
            rig.read_all_frames()
            rig.read_all_frames()
            result = rig.read_all_frames()
        assert result is None

    def test_frame_indices_increase(self):
        rig = Synthetic360Rig(max_frames=4)
        front_indices = []
        with rig:
            for bundle in rig.stream():
                front_indices.append(bundle["front"].frame_index)
        assert front_indices == list(range(4))

    def test_timestamps_increase_per_lens(self):
        rig = Synthetic360Rig(fps=10, max_frames=3)
        ts_by_lens: dict = {pos: [] for pos in MultiCameraRig.STANDARD_POSITIONS}
        with rig:
            for bundle in rig.stream():
                for pos, frame in bundle.items():
                    ts_by_lens[pos].append(frame.timestamp_s)
        for pos, ts_list in ts_by_lens.items():
            assert all(ts_list[i] < ts_list[i + 1] for i in range(len(ts_list) - 1)), (
                f"Timestamps not increasing for lens {pos}: {ts_list}"
            )

    def test_each_lens_has_correct_camera_id(self):
        rig = Synthetic360Rig(max_frames=1)
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        for pos, frame in bundle.items():
            assert frame.camera_id == pos, (
                f"Expected camera_id={pos!r}, got {frame.camera_id!r}"
            )

    def test_frames_synthetic_metadata_flag(self):
        rig = Synthetic360Rig(max_frames=1)
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        for frame in bundle.values():
            assert frame.metadata.get("synthetic") is True


# ─────────────────────────────────────────────────────────────────────────────
# Calibration placeholders wired through the rig
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiCameraCalibration:
    def test_calibration_params_accepted(self):
        cals = {
            pos: CalibrationParams(
                camera_id=pos,
                hfov_deg=195.0,  # fisheye lens typical HFOV
                pitch_deg=-10.0,
            )
            for pos in MultiCameraRig.STANDARD_POSITIONS
        }
        rig = Synthetic360Rig(max_frames=1)
        # Inject calibrations after construction (scaffold pattern)
        rig.calibrations = cals
        assert rig.calibrations["front"].hfov_deg == 195.0
        assert rig.calibrations["rear"].pitch_deg == -10.0

    def test_single_camera_calibration(self):
        cal = CalibrationParams(
            camera_id="front",
            fx=700.0, fy=700.0,
            cx=320.0, cy=240.0,
            distortion=[-0.3, 0.1, 0.0, 0.0],
            hfov_deg=120.0,
            mount_offset_xyz_m=(0.0, 0.0, 1.5),
        )
        src = SyntheticFrameSource(camera_id="front", calibration=cal, max_frames=1)
        assert src.calibration.fx == 700.0
        assert src.calibration.mount_offset_xyz_m == (0.0, 0.0, 1.5)


# ─────────────────────────────────────────────────────────────────────────────
# Extensibility: adding a real 360 source via subclassing
# ─────────────────────────────────────────────────────────────────────────────

class TestExtensibilityPattern:
    """
    Verifies that the scaffold supports Track 2 extension with zero changes
    to existing code — only a new subclass is needed.
    """

    def test_custom_rig_subclass_is_accepted(self):
        """A custom rig subclass should satisfy the MultiCameraRig contract."""
        class _MyCustom360Rig(MultiCameraRig):
            """Hypothetical real 360-camera driver (stub for test)."""
            def __init__(self):
                super().__init__(max_frames=2)
                for pos in ["front", "rear"]:
                    self._sources[pos] = SyntheticFrameSource(
                        camera_id=pos, max_frames=2
                    )

        rig = _MyCustom360Rig()
        assert rig.is_multi_camera is True
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        assert set(bundle.keys()) == {"front", "rear"}

    def test_custom_source_registered_in_factory(self):
        """New camera sources can be registered without modifying the factory."""
        class _Real360Source(SyntheticFrameSource):
            """Placeholder for a real 360-camera SDK wrapper."""
            pass

        CameraSourceFactory.register("real_360_sdk", _Real360Source)
        src = CameraSourceFactory.create("real_360_sdk", max_frames=2)
        assert isinstance(src, _Real360Source)

    def test_single_camera_source_abc_contract(self):
        """Any CameraSource subclass must implement open/release/read_frame."""
        import abc

        # Verify CameraSource has abstract methods
        abstract_methods = getattr(CameraSource, "__abstractmethods__", set())
        assert "open" in abstract_methods
        assert "release" in abstract_methods
        assert "read_frame" in abstract_methods

    def test_incomplete_source_raises_on_instantiation(self):
        """An incomplete CameraSource subclass must not be instantiable."""
        class _Incomplete(CameraSource):
            pass  # missing open, release, read_frame

        with pytest.raises(TypeError):
            _Incomplete()


# ─────────────────────────────────────────────────────────────────────────────
# Multi-camera frame consistency checks
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiCameraConsistency:
    def test_all_lenses_same_frame_index(self):
        """In a synchronised rig all lenses must share the same frame index."""
        rig = Synthetic360Rig(max_frames=3)
        with rig:
            for bundle in rig.stream():
                indices = [f.frame_index for f in bundle.values()]
                assert len(set(indices)) == 1, (
                    f"Frame indices not synchronised: {indices}"
                )

    def test_no_shared_bgr_array_between_lenses(self):
        """Each lens must have its own independent BGR array."""
        rig = Synthetic360Rig(max_frames=1)
        with rig:
            bundle = rig.read_all_frames()
        assert bundle is not None
        frames = list(bundle.values())
        for i in range(len(frames)):
            for j in range(i + 1, len(frames)):
                assert frames[i].bgr is not frames[j].bgr, (
                    "Lenses share the same BGR array (aliasing bug)"
                )

    def test_stream_count_matches_max_frames(self):
        n = 5
        rig = Synthetic360Rig(max_frames=n)
        with rig:
            bundles = list(rig.stream())
        assert len(bundles) == n
