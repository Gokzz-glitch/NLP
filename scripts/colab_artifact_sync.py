#!/usr/bin/env python3
"""
Colab Artifact Sync Daemon

Continuously mirrors Colab-produced training artifacts from the workspace
(Drive-synced folder) into stable local model paths for downstream services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_FILE = LOGS_DIR / "colab_sync_state.json"

# Common locations where Colab or local jobs may emit training artifacts.
CANDIDATE_FILES = [
    PROJECT_ROOT / "runs" / "detect" / "ssl_training" / "weights" / "best.pt",
    PROJECT_ROOT / "runs" / "detect" / "ssl_training" / "weights" / "last.pt",
    PROJECT_ROOT / "runs" / "detect" / "runs" / "detect" / "ssl_training" / "weights" / "best.pt",
    PROJECT_ROOT / "runs" / "detect" / "runs" / "detect" / "ssl_training" / "weights" / "last.pt",
    PROJECT_ROOT / "models" / "best_ssl_trained.pt",
]

TARGET_MAP = {
    "best.pt": PROJECT_ROOT / "models" / "colab_best_latest.pt",
    "last.pt": PROJECT_ROOT / "models" / "colab_last_latest.pt",
    "best_ssl_trained.pt": PROJECT_ROOT / "models" / "colab_best_latest.pt",
}


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _load_state() -> Dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict[str, str]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _existing_sources() -> List[Path]:
    return [p for p in CANDIDATE_FILES if p.exists() and p.is_file()]


def _copy_if_changed(src: Path, state: Dict[str, str]) -> bool:
    key = str(src)
    digest = _sha1(src)
    if state.get(key) == digest:
        return False

    target = TARGET_MAP.get(src.name)
    if target is None:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    state[key] = digest

    # Keep a stable alias consumed by other local scripts.
    if target.name == "colab_best_latest.pt":
        shutil.copy2(target, PROJECT_ROOT / "models" / "best_colab_mirror.pt")

    print(f"[SYNC] Updated from {src} -> {target}")
    return True


def run(interval_sec: int) -> None:
    print("[SYNC] Colab artifact sync daemon started")
    print(f"[SYNC] Poll interval: {interval_sec}s")

    state = _load_state()
    while True:
        changed_any = False
        for src in _existing_sources():
            try:
                changed_any = _copy_if_changed(src, state) or changed_any
            except Exception as exc:
                print(f"[SYNC] Error processing {src}: {exc}")

        if changed_any:
            _save_state(state)

        time.sleep(max(10, interval_sec))


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously sync Colab training artifacts")
    parser.add_argument("--interval", type=int, default=45, help="Polling interval in seconds")
    args = parser.parse_args()

    run(interval_sec=args.interval)


if __name__ == "__main__":
    main()
