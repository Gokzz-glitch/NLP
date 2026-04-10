#!/usr/bin/env python3
"""
Watchdog for Colab runtime heartbeat.

Alerts when logs/colab_heartbeat.log becomes stale so account switching can happen quickly.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = PROJECT_ROOT / "logs"
HEARTBEAT_PATH = LOGS_DIR / "colab_heartbeat.log"
STATE_PATH = LOGS_DIR / "colab_runtime_state.json"
ALERT_PATH = LOGS_DIR / "colab_runtime_alert.json"


def _parse_heartbeat_ts(line: str) -> datetime | None:
    try:
        ts = line.split("|", 1)[0].strip()
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _last_heartbeat_time() -> datetime | None:
    if not HEARTBEAT_PATH.exists():
        return None
    lines = HEARTBEAT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        parsed = _parse_heartbeat_ts(line)
        if parsed is not None:
            return parsed
    return None


def _write_alert(status: str, message: str, stale_sec: int | None) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "message": message,
        "stale_seconds": stale_sec,
        "heartbeat_file": str(HEARTBEAT_PATH),
        "runtime_state_file": str(STATE_PATH),
    }
    ALERT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[WATCHDOG] {message}")


def run(interval_sec: int, stale_sec: int) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    print("[WATCHDOG] Started")
    print(f"[WATCHDOG] interval={interval_sec}s stale_threshold={stale_sec}s")

    last_status = ""
    while True:
        now = datetime.now(timezone.utc)
        hb_ts = _last_heartbeat_time()

        if hb_ts is None:
            status = "waiting"
            message = "No heartbeat yet"
            lag = None
        else:
            lag = int((now - hb_ts).total_seconds())
            if lag > stale_sec:
                status = "runtime_down"
                message = f"Colab runtime heartbeat stale ({lag}s). Switch account now."
            else:
                status = "runtime_alive"
                message = f"Colab runtime alive (last heartbeat {lag}s ago)"

        if status != last_status:
            _write_alert(status=status, message=message, stale_sec=lag)
            last_status = status

        time.sleep(max(10, interval_sec))


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Colab runtime heartbeat")
    parser.add_argument("--interval", type=int, default=30, help="Polling interval in seconds")
    parser.add_argument("--stale-sec", type=int, default=150, help="Stale heartbeat threshold in seconds")
    args = parser.parse_args()

    run(interval_sec=args.interval, stale_sec=args.stale_sec)


if __name__ == "__main__":
    main()
