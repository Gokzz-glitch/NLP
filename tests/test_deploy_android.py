"""
tests/test_deploy_android.py

Unit tests for scripts/deploy_android.py covering:
  - list_devices: parses adb output correctly
  - list_devices: returns empty list when adb unavailable
  - list_devices: filters header line, blank lines
  - pick_device: auto-selects first authorised device
  - pick_device: returns None when no authorised devices
  - pick_device: matches by serial when --serial provided
  - pick_device: returns None when requested serial not authorised
  - check_nnapi: returns True when lib found
  - check_nnapi: returns False when lib absent
  - push_models: skips file when not on disk
  - push_models: calls adb push for present files
  - _check_adb_available: True when adb responds; False when FileNotFoundError
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import subprocess
from unittest.mock import MagicMock, patch, call
import pytest

import deploy_android as da


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# _check_adb_available
# ---------------------------------------------------------------------------

class TestCheckAdbAvailable:

    def test_returns_true_when_adb_responds(self):
        with patch("subprocess.run", return_value=_completed("Android Debug Bridge")):
            assert da._check_adb_available()

    def test_returns_false_when_adb_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert not da._check_adb_available()


# ---------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------

_DEVICES_OUTPUT = (
    "List of devices attached\n"
    "emulator-5554\tdevice\n"
    "ABC123456789\tdevice\n"
    "XYZ987\tunauthorized\n"
    "\n"
)

_NO_DEVICES_OUTPUT = "List of devices attached\n\n"


class TestListDevices:

    def test_parses_multiple_devices(self):
        with patch("subprocess.run", return_value=_completed(_DEVICES_OUTPUT)):
            devs = da.list_devices()
        assert len(devs) == 3

    def test_parses_serial_correctly(self):
        with patch("subprocess.run", return_value=_completed(_DEVICES_OUTPUT)):
            serials = [d["serial"] for d in da.list_devices()]
        assert "emulator-5554" in serials
        assert "ABC123456789" in serials

    def test_parses_state_correctly(self):
        with patch("subprocess.run", return_value=_completed(_DEVICES_OUTPUT)):
            states = {d["serial"]: d["state"] for d in da.list_devices()}
        assert states["emulator-5554"] == "device"
        assert states["XYZ987"] == "unauthorized"

    def test_returns_empty_when_no_devices(self):
        with patch("subprocess.run", return_value=_completed(_NO_DEVICES_OUTPUT)):
            assert da.list_devices() == []

    def test_returns_empty_when_adb_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert da.list_devices() == []

    def test_skips_blank_lines(self):
        output = "List of devices attached\n\nABC\tdevice\n\n"
        with patch("subprocess.run", return_value=_completed(output)):
            devs = da.list_devices()
        assert len(devs) == 1


# ---------------------------------------------------------------------------
# pick_device
# ---------------------------------------------------------------------------

class TestPickDevice:

    def test_picks_first_authorised_when_no_serial(self):
        with patch("subprocess.run", return_value=_completed(_DEVICES_OUTPUT)):
            result = da.pick_device()
        assert result == "emulator-5554"

    def test_returns_none_when_no_authorised(self):
        output = "List of devices attached\nABC\tunauthorized\n"
        with patch("subprocess.run", return_value=_completed(output)):
            result = da.pick_device()
        assert result is None

    def test_picks_by_serial(self):
        with patch("subprocess.run", return_value=_completed(_DEVICES_OUTPUT)):
            result = da.pick_device("ABC123456789")
        assert result == "ABC123456789"

    def test_returns_none_when_serial_not_authorised(self):
        with patch("subprocess.run", return_value=_completed(_DEVICES_OUTPUT)):
            result = da.pick_device("XYZ987")
        assert result is None

    def test_returns_none_when_serial_missing(self):
        with patch("subprocess.run", return_value=_completed(_DEVICES_OUTPUT)):
            result = da.pick_device("DOES_NOT_EXIST")
        assert result is None

    def test_returns_none_when_no_devices(self):
        with patch("subprocess.run", return_value=_completed(_NO_DEVICES_OUTPUT)):
            result = da.pick_device()
        assert result is None


# ---------------------------------------------------------------------------
# check_nnapi
# ---------------------------------------------------------------------------

class TestCheckNNAPI:

    def test_returns_true_when_lib_found(self):
        with patch("subprocess.run", return_value=_completed("YES\n")):
            assert da.check_nnapi("ABC123")

    def test_returns_false_when_lib_absent(self):
        def side_effect(cmd, **kwargs):
            # Both probe paths return NO
            return _completed("NO\n")
        with patch("subprocess.run", side_effect=side_effect):
            result = da.check_nnapi("ABC123")
        assert not result

    def test_returns_true_via_dumpsys_fallback(self):
        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if "dumpsys" in " ".join(cmd):
                return _completed("android.hardware.neuralnetworks\n")
            return _completed("NO\n")
        with patch("subprocess.run", side_effect=side_effect):
            result = da.check_nnapi("ABC123")
        assert result


# ---------------------------------------------------------------------------
# push_models
# ---------------------------------------------------------------------------

class TestPushModels:

    def test_skips_missing_local_file(self):
        with patch("os.path.exists", return_value=False):
            with patch("subprocess.run", return_value=_completed()) as mock_run:
                res = da.push_models("SERIAL123")
        assert "indian_traffic_yolov8.onnx" in res["skipped"]

    def test_pushes_when_file_exists_and_not_on_device(self):
        def run_side_effect(cmd, **kwargs):
            if "mkdir" in cmd:
                return _completed()
            if "-f" in " ".join(cmd):          # existence check on device
                return _completed("MISSING\n")
            if "push" in cmd:
                return _completed("1 file pushed\n")
            return _completed()

        with patch("os.path.exists", return_value=True):
            with patch("subprocess.run", side_effect=run_side_effect):
                res = da.push_models("SERIAL123")
        assert "indian_traffic_yolov8.onnx" in res["pushed"]

    def test_skips_when_already_on_device(self):
        def run_side_effect(cmd, **kwargs):
            if "mkdir" in cmd:
                return _completed()
            return _completed("EXISTS\n")

        with patch("os.path.exists", return_value=True):
            with patch("subprocess.run", side_effect=run_side_effect):
                res = da.push_models("SERIAL123", force=False)
        assert "indian_traffic_yolov8.onnx" in res["skipped"]

    def test_force_pushes_even_when_on_device(self):
        def run_side_effect(cmd, **kwargs):
            if "mkdir" in cmd:
                return _completed()
            if "push" in cmd:
                return _completed("1 file pushed\n")
            return _completed("EXISTS\n")

        with patch("os.path.exists", return_value=True):
            with patch("subprocess.run", side_effect=run_side_effect):
                res = da.push_models("SERIAL123", force=True)
        assert "indian_traffic_yolov8.onnx" in res["pushed"]

    def test_records_failure_on_push_error(self):
        def run_side_effect(cmd, **kwargs):
            if "mkdir" in cmd:
                return _completed()
            if "-f" in " ".join(cmd):
                return _completed("MISSING\n")
            if "push" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr="permission denied")
            return _completed()

        with patch("os.path.exists", return_value=True):
            with patch("subprocess.run", side_effect=run_side_effect):
                res = da.push_models("SERIAL123")
        assert "indian_traffic_yolov8.onnx" in res["failed"]

    def test_result_has_three_keys(self):
        with patch("os.path.exists", return_value=False):
            with patch("subprocess.run", return_value=_completed()):
                res = da.push_models("SERIAL123")
        assert set(res.keys()) == {"pushed", "skipped", "failed"}
