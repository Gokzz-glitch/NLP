#!/usr/bin/env python3
"""
scripts/deploy_android.py
SmartSalai Edge-Sentinel — Android NPU Deployment Script (ERR-003 resolver)

Dynamically discovers connected Android devices via ADB — no hardcoded
device fingerprint required.  Pushes ONNX model files and validates
NNAPI (Neural Network API) delegate availability on the target device.

Usage:
  python scripts/deploy_android.py              # discover + push all models
  python scripts/deploy_android.py --list       # list connected devices only
  python scripts/deploy_android.py --serial <serial> --push-models
  python scripts/deploy_android.py --check-nnapi

Prerequisites:
  - ADB installed and on PATH  (sdk/platform-tools or standalone)
  - USB debugging enabled on the Android device
  - USB cable connected (or adb tcpip for wireless)

ERR-003 status: RESOLVED — device fingerprint is no longer hardcoded.
  The script enumerates all connected ADB devices at runtime and targets
  the first authorised device by default (or the one specified via --serial).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)

VISION_MODELS_DIR = os.path.join(_PROJECT_ROOT, "models", "vision")
DEVICE_MODELS_DIR = "/sdcard/SmartSalai/models/vision"   # on-device path

# Model file to push (ERR-001 output)
_VISION_ONNX = os.path.join(VISION_MODELS_DIR, "indian_traffic_yolov8.onnx")

# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

def _adb(*args: str, serial: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """
    Run an adb command and return the CompletedProcess.

    Args:
        *args:   adb sub-command and arguments (e.g. "devices", "push", …).
        serial:  Target device serial.  If None, adb selects the only device.
        check:   If True, raise subprocess.CalledProcessError on non-zero exit.

    Raises:
        FileNotFoundError: if `adb` is not on PATH.
    """
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, check=check
    )


def _check_adb_available() -> bool:
    """Return True if adb is reachable on PATH."""
    try:
        _adb("version")
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Device discovery (ERR-003 fix)
# ---------------------------------------------------------------------------

def list_devices() -> list[dict]:
    """
    Run `adb devices` and return a list of connected, authorised devices.

    Each entry is:
        {"serial": str, "state": str}
    where state is one of:  device  (authorised)
                            unauthorized
                            offline

    Returns an empty list if adb is unavailable or no devices are connected.
    """
    try:
        result = _adb("devices", check=False)
    except FileNotFoundError:
        return []

    devices = []
    for line in result.stdout.splitlines()[1:]:   # skip header
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            serial, state = parts[0].strip(), parts[1].strip()
            devices.append({"serial": serial, "state": state})
    return devices


def pick_device(serial: Optional[str] = None) -> Optional[str]:
    """
    Select the target device serial.

    If *serial* is given, verify it is present and authorised.
    Otherwise, select the first authorised device.

    Returns:
        Device serial string, or None if no authorised device is found.
    """
    devices = list_devices()
    authorised = [d for d in devices if d["state"] == "device"]

    if not authorised:
        return None

    if serial:
        match = next((d for d in authorised if d["serial"] == serial), None)
        if match:
            return match["serial"]
        print(f"  WARNING: Device {serial!r} not found or not authorised.")
        return None

    # Default: first authorised device
    return authorised[0]["serial"]


# ---------------------------------------------------------------------------
# NNAPI availability check
# ---------------------------------------------------------------------------

def check_nnapi(serial: str) -> bool:
    """
    Probe whether the device exposes Android NNAPI (Neural Network API).

    Strategy: check for /vendor/lib64/libneuralnetworks.so or the NNAPI
    service (android.hardware.neuralnetworks.*).

    Returns True if NNAPI is likely available for ONNX Runtime delegation.
    """
    probe_paths = [
        "/vendor/lib64/libneuralnetworks.so",
        "/system/lib64/libneuralnetworks.so",
    ]
    for path in probe_paths:
        res = _adb("shell", f"[ -f {path} ] && echo YES || echo NO", serial=serial, check=False)
        if "YES" in res.stdout:
            return True

    # Fallback: check dumpsys for NNAPI service
    res = _adb("shell", "dumpsys -l 2>/dev/null | grep -i neural", serial=serial, check=False)
    return "neural" in res.stdout.lower()


# ---------------------------------------------------------------------------
# Model push
# ---------------------------------------------------------------------------

def push_models(serial: str, force: bool = False) -> dict:
    """
    Push ONNX model files to DEVICE_MODELS_DIR on the Android device.

    Args:
        serial: ADB device serial (from pick_device()).
        force:  Re-push even if the file already exists on device.

    Returns:
        {"pushed": [filenames], "skipped": [filenames], "failed": [filenames]}
    """
    results: dict[str, list] = {"pushed": [], "skipped": [], "failed": []}

    models = [
        ("indian_traffic_yolov8.onnx", _VISION_ONNX),
    ]

    # Create target directory on device
    _adb("shell", f"mkdir -p {DEVICE_MODELS_DIR}", serial=serial, check=False)

    for filename, local_path in models:
        device_path = f"{DEVICE_MODELS_DIR}/{filename}"

        if not os.path.exists(local_path):
            print(f"  SKIP (not found locally): {filename}")
            print(f"         Run: python scripts/download_models.py   to fetch it.")
            results["skipped"].append(filename)
            continue

        # Check if already on device
        if not force:
            check = _adb("shell", f"[ -f {device_path} ] && echo EXISTS || echo MISSING",
                         serial=serial, check=False)
            if "EXISTS" in check.stdout:
                print(f"  SKIP (already on device): {filename}")
                results["skipped"].append(filename)
                continue

        print(f"  PUSH: {local_path}  →  {device_path}")
        try:
            push_res = _adb("push", local_path, device_path, serial=serial)
            print(f"    {push_res.stdout.strip()}")
            results["pushed"].append(filename)
        except subprocess.CalledProcessError as exc:
            print(f"  FAILED: {filename}: {exc.stderr.strip()}")
            results["failed"].append(filename)

    return results


# ---------------------------------------------------------------------------
# Device info
# ---------------------------------------------------------------------------

def get_device_info(serial: str) -> dict:
    """Return a dict of useful device properties via adb shell getprop."""
    props = {
        "model":       "ro.product.model",
        "android_ver": "ro.build.version.release",
        "api_level":   "ro.build.version.sdk",
        "cpu_abi":     "ro.product.cpu.abi",
        "npu_vendor":  "ro.hardware.egl",
    }
    info = {"serial": serial}
    for key, prop in props.items():
        res = _adb("shell", f"getprop {prop}", serial=serial, check=False)
        info[key] = res.stdout.strip() or "unknown"
    return info


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy SmartSalai models to Android")
    parser.add_argument("--list",        action="store_true", help="List connected ADB devices and exit")
    parser.add_argument("--serial",      default=None,         help="Target device serial (auto-detected if omitted)")
    parser.add_argument("--push-models", action="store_true",  help="Push ONNX models to the device")
    parser.add_argument("--check-nnapi", action="store_true",  help="Check NNAPI availability on the device")
    parser.add_argument("--force",       action="store_true",  help="Re-push even if models already on device")
    args = parser.parse_args()

    # Check adb
    if not _check_adb_available():
        print(
            "[ERR-003] adb not found on PATH.\n"
            "  Install Android SDK Platform Tools:\n"
            "    https://developer.android.com/tools/releases/platform-tools\n"
            "  Or: apt install adb   (Debian/Ubuntu)"
        )
        sys.exit(1)

    # --list
    devices = list_devices()
    if not devices:
        print("[ERR-003] No ADB devices connected.\n"
              "  Enable USB Debugging on your Android device, connect via USB, and run again.")
        sys.exit(1 if not args.list else 0)

    print(f"[ERR-003] Connected ADB devices ({len(devices)} found):")
    for d in devices:
        prefix = "  ✓" if d["state"] == "device" else "  ✗"
        print(f"  {prefix}  {d['serial']:30s}  [{d['state']}]")

    if args.list:
        sys.exit(0)

    # Select device
    serial = pick_device(args.serial)
    if not serial:
        print("[ERR-003] No authorised device found. "
              "Accept the USB Debugging prompt on the device and retry.")
        sys.exit(1)

    # Print device info
    info = get_device_info(serial)
    print(f"\n[ERR-003] Target device: {info['model']}  "
          f"Android {info['android_ver']}  API {info['api_level']}  {info['cpu_abi']}")
    print(f"  Serial: {serial}  (ERR-003 RESOLVED — no hardcoded fingerprint)")

    # --check-nnapi
    if args.check_nnapi or not (args.push_models):
        nnapi = check_nnapi(serial)
        status = "AVAILABLE ✓" if nnapi else "NOT FOUND ✗"
        print(f"  NNAPI:  {status}")
        if not nnapi:
            print(
                "  WARNING: NNAPI not detected. ONNX Runtime will fall back to CPU.\n"
                "  For NPU acceleration, ensure your device runs Android 8.1+ (API 27+)\n"
                "  and the SoC vendor has an NNAPI HAL (T-017 prerequisite)."
            )

    # --push-models (default action if no flags given)
    if args.push_models or not args.check_nnapi:
        print(f"\n  Pushing models to {DEVICE_MODELS_DIR} …")
        res = push_models(serial, force=args.force)
        print(f"  Pushed: {len(res['pushed'])}  "
              f"Skipped: {len(res['skipped'])}  "
              f"Failed: {len(res['failed'])}")
        if res["failed"]:
            sys.exit(1)

    print("\n[ERR-003] Deployment complete.")


if __name__ == "__main__":
    main()
