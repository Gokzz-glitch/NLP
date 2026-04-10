#!/usr/bin/env python3
"""
Market readiness monitor for SmartSalai.

Provides:
- Live operational telemetry (downloads, SSL loop, training epochs)
- Requirements checklist with satisfied / not satisfied / manual verification
- Overall readiness percentage and pending work list
- Snapshot export to logs/market_readiness_snapshot.json
- Todo export to logs/market_readiness_todo.md
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
TESTING_DIR = PROJECT_ROOT / "Testing videos"
SSL_RESULTS_DIR = TESTING_DIR / "ssl_verification_results"
TRAIN_RESULTS_CSV = PROJECT_ROOT / "runs" / "detect" / "runs" / "detect" / "continuous_training" / "results.csv"
LOOP_STATE_FILE = SSL_RESULTS_DIR / "loop_state.json"
SNAPSHOT_FILE = LOGS_DIR / "market_readiness_snapshot.json"
TODO_FILE = LOGS_DIR / "market_readiness_todo.md"
HOURLY_LOG_FILE = LOGS_DIR / "hourly_accuracy_updates.jsonl"
HOURLY_STAMP_FILE = LOGS_DIR / "hourly_accuracy_last_stamp.txt"


@dataclass
class Requirement:
    rid: str
    title: str
    check_type: str
    target: str
    tokens: List[str]
    manual: bool = False


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def check_requirement(req: Requirement) -> Tuple[str, str]:
    if req.manual:
        return "MANUAL", "Needs human validation/evidence review"

    target_path = PROJECT_ROOT / req.target

    if req.check_type == "file_exists":
        ok = target_path.exists()
        return ("SATISFIED" if ok else "NOT_SATISFIED", str(target_path))

    if req.check_type == "contains_all":
        text = read_text(target_path)
        missing = [t for t in req.tokens if t not in text]
        if not missing:
            return "SATISFIED", f"All tokens present in {target_path}"
        return "NOT_SATISFIED", f"Missing tokens: {missing}"

    if req.check_type == "glob_contains_any":
        pattern = str(PROJECT_ROOT / req.target)
        files = [Path(p) for p in glob.glob(pattern, recursive=True)]
        for f in files:
            txt = read_text(f)
            if any(t in txt for t in req.tokens):
                return "SATISFIED", f"Matched in {f}"
        return "NOT_SATISFIED", f"No token match in {req.target}"

    return "NOT_SATISFIED", "Unsupported check type"


def get_requirements() -> List[Requirement]:
    # Derived from hackathon requirement sections shared in the prompt screenshots.
    return [
        Requirement("DL-1", "DriveLegal geo-fenced challan lookup", "contains_all", "scripts/live_road_test.py", ["GEO-FENCED CHALLAN", "DRIVELEGAL"]),
        Requirement("DL-2", "DriveLegal violation/challan logic", "contains_all", "scripts/live_road_test.py", ["Challan", "violation"]),
        Requirement("DL-3", "DriveLegal global applicability", "glob_contains_any", "scripts/**/*.py", ["global applicability", "Global Applicability"]),
        Requirement("DL-4", "DriveLegal offline robustness", "glob_contains_any", "scripts/**/*.py", ["offline", "Offline"]),

        Requirement("RW-1", "RoadWatch road metadata visibility", "contains_all", "scripts/live_road_test.py", ["contractor", "last_relaying", "budget"]),
        Requirement("RW-2", "RoadWatch complaint routing", "contains_all", "scripts/live_road_test.py", ["Auto-Routing Complaint", "executive_eng"]),
        Requirement("RW-3", "RoadWatch data accuracy hooks", "glob_contains_any", "scripts/**/*.py", ["query_road_contractor", "Data accuracy", "data accuracy"]),

        Requirement("RS-1", "RoadSoS nearest emergency services", "contains_all", "scripts/live_road_test.py", ["Nearest Trauma/Hospital", "Nearest Police Station"]),
        Requirement("RS-2", "RoadSoS towing and rescue", "contains_all", "scripts/live_road_test.py", ["Nearest Towing/Showroom", "towing"]),
        Requirement("RS-3", "RoadSoS offline POI database", "file_exists", "roadsos_offline.db", []),

        Requirement("OFF-1", "Offline legal store availability", "file_exists", "legal_vector_store.db", []),
        Requirement("OFF-2", "Offline emergency contacts config", "file_exists", "config/emergency_contacts.json", []),

        Requirement("TC-1", "Open model/API preference", "MANUAL", "", [], manual=True),
        Requirement("TC-2", "Originality/copyright compliance", "MANUAL", "", [], manual=True),
        Requirement("TC-3", "Identity/proof readiness", "MANUAL", "", [], manual=True),
    ]


def get_active_jobs() -> List[str]:
    ps_cmd = (
        "Get-CimInstance Win32_Process "
        "| Where-Object { $_.Name -match '^python(\\.exe)?$' -and "
        "($_.CommandLine -match 'youtube_ssl_verification.py|continuous_training_loop.py|colab_training_launcher.py|market_readiness_monitor.py') } "
        "| Select-Object -ExpandProperty CommandLine"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def get_latest_ssl_log() -> Path | None:
    logs = sorted(LOGS_DIR.glob("ssl_verify_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def get_download_status() -> Dict[str, object]:
    latest = get_latest_ssl_log()
    if not latest:
        return {
            "latest_log": None,
            "downloading_events": 0,
            "downloaded_events": 0,
            "current_download": None,
        }

    text = read_text(latest)
    downloading = re.findall(r"Downloading:\s*(.+)", text)
    downloaded = re.findall(r"Downloaded:\s*(.+)", text)

    current = None
    if len(downloading) > len(downloaded):
        current = downloading[-1]

    video_files = [
        p for p in TESTING_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".avi", ".mov"}
    ]

    return {
        "latest_log": str(latest),
        "downloading_events": len(downloading),
        "downloaded_events": len(downloaded),
        "saved_video_files": len(video_files),
        "current_download": current,
    }


def get_epoch_status(target_epochs: int) -> Dict[str, object]:
    if not TRAIN_RESULTS_CSV.exists():
        return {
            "epochs_completed": 0,
            "target_epochs": target_epochs,
            "epoch_progress_pct": 0.0,
            "last_metrics": None,
        }

    with TRAIN_RESULTS_CSV.open("r", encoding="utf-8", errors="ignore") as f:
        rows = list(csv.reader(f))

    completed = max(0, len(rows) - 1)
    pct = 0.0 if target_epochs <= 0 else min(100.0, (completed / target_epochs) * 100.0)

    last = rows[-1] if completed > 0 else None
    return {
        "epochs_completed": completed,
        "target_epochs": target_epochs,
        "epoch_progress_pct": round(pct, 2),
        "last_metrics": last,
    }


def get_ssl_status() -> Dict[str, object]:
    state = {}
    if LOOP_STATE_FILE.exists():
        try:
            state = json.loads(read_text(LOOP_STATE_FILE))
        except Exception:
            state = {}

    latest_log = get_latest_ssl_log()
    tail = []
    if latest_log:
        lines = read_text(latest_log).splitlines()
        tail = lines[-8:]

    return {
        "loop_state_present": LOOP_STATE_FILE.exists(),
        "cycles_completed": state.get("cycles_completed"),
        "last_cycle_at": state.get("last_cycle_at"),
        "processed_url_hashes": len(state.get("processed_url_hashes", [])) if isinstance(state.get("processed_url_hashes", []), list) else 0,
        "latest_log_tail": tail,
    }


def build_todo_and_readiness() -> Tuple[List[Dict[str, str]], Dict[str, float], List[str]]:
    reqs = get_requirements()
    out = []
    unsatisfied = []

    auto_total = 0
    auto_sat = 0

    manual_total = 0
    manual_done = 0

    for r in reqs:
        status, evidence = check_requirement(r)
        out.append({
            "id": r.rid,
            "title": r.title,
            "status": status,
            "evidence": evidence,
        })

        if status == "MANUAL":
            manual_total += 1
        else:
            auto_total += 1
            if status == "SATISFIED":
                auto_sat += 1
            else:
                unsatisfied.append(f"{r.rid} {r.title}")

    auto_pct = 0.0 if auto_total == 0 else (auto_sat / auto_total) * 100.0
    # Conservative overall: manual items count as pending until explicitly marked by human review.
    overall_total = auto_total + manual_total
    overall_sat = auto_sat + manual_done
    overall_pct = 0.0 if overall_total == 0 else (overall_sat / overall_total) * 100.0

    return out, {
        "auto_satisfied_pct": round(auto_pct, 2),
        "overall_market_ready_pct": round(overall_pct, 2),
    }, unsatisfied


def write_exports(snapshot: Dict[str, object]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    checklist = snapshot["requirements_checklist"]
    lines = [
        "# Market Readiness TODO",
        "",
        f"- Auto checklist satisfied: {snapshot['readiness']['auto_satisfied_pct']}%",
        f"- Overall market-ready (conservative): {snapshot['readiness']['overall_market_ready_pct']}%",
        "",
        "## Requirement Status",
        "",
    ]

    for item in checklist:
        mark = "[x]" if item["status"] == "SATISFIED" else "[ ]"
        lines.append(f"- {mark} {item['id']} {item['title']} ({item['status']})")

    lines += ["", "## Work Left", ""]
    pending = snapshot.get("work_left", [])
    if pending:
        for w in pending:
            lines.append(f"- [ ] {w}")
    else:
        lines.append("- [x] No auto-detected blockers")

    TODO_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _last_map50_from_metrics(last_metrics: object) -> float | None:
    if not isinstance(last_metrics, list) or len(last_metrics) < 8:
        return None
    try:
        return float(last_metrics[7])
    except Exception:
        return None


def write_hourly_update(snapshot: Dict[str, object]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    hour_stamp = time.strftime("%Y-%m-%d %H:00")

    last = ""
    if HOURLY_STAMP_FILE.exists():
        last = read_text(HOURLY_STAMP_FILE).strip()

    if last == hour_stamp:
        return

    epoch = snapshot.get("epoch_status", {})
    ready = snapshot.get("readiness", {})
    download = snapshot.get("download_status", {})
    ssl = snapshot.get("ssl_status", {})

    entry = {
        "hour": hour_stamp,
        "timestamp": snapshot.get("timestamp"),
        "epochs_completed": epoch.get("epochs_completed", 0),
        "target_epochs": epoch.get("target_epochs", 0),
        "epoch_progress_pct": epoch.get("epoch_progress_pct", 0.0),
        "accuracy_proxy_map50": _last_map50_from_metrics(epoch.get("last_metrics")),
        "downloaded_events": download.get("downloaded_events", 0),
        "saved_video_files": download.get("saved_video_files", 0),
        "ssl_cycles_completed": ssl.get("cycles_completed"),
        "auto_checklist_pct": ready.get("auto_satisfied_pct", 0.0),
        "market_ready_pct": ready.get("overall_market_ready_pct", 0.0),
        "work_left_count": len(snapshot.get("work_left", [])),
    }

    with HOURLY_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    HOURLY_STAMP_FILE.write_text(hour_stamp, encoding="utf-8")


def render(snapshot: Dict[str, object]) -> None:
    os.system("cls" if os.name == "nt" else "clear")

    print("=== MARKET READINESS LIVE MONITOR ===")
    print("")

    print("RUNNING JOBS")
    jobs = snapshot["active_jobs"]
    if jobs:
        for j in jobs:
            print(f"- {j}")
    else:
        print("- none")

    print("")
    print("DOWNLOAD STATUS")
    d = snapshot["download_status"]
    print(f"- downloading events: {d['downloading_events']}")
    print(f"- downloaded events: {d['downloaded_events']}")
    print(f"- saved video files: {d.get('saved_video_files', 0)}")
    print(f"- current download: {d.get('current_download')}")

    print("")
    print("TRAINING STATUS")
    e = snapshot["epoch_status"]
    print(f"- epochs completed: {e['epochs_completed']} / {e['target_epochs']}")
    print(f"- epoch progress: {e['epoch_progress_pct']}%")
    print(f"- last metrics row: {e['last_metrics']}")

    print("")
    print("SSL LOOP STATUS")
    s = snapshot["ssl_status"]
    print(f"- loop state file present: {s['loop_state_present']}")
    print(f"- cycles completed: {s.get('cycles_completed')}")
    print(f"- processed URL hashes: {s.get('processed_url_hashes')}")
    print(f"- last cycle at: {s.get('last_cycle_at')}")

    print("")
    print("REQUIREMENTS SUMMARY")
    r = snapshot["readiness"]
    print(f"- auto checklist satisfied: {r['auto_satisfied_pct']}%")
    print(f"- overall market-ready (conservative): {r['overall_market_ready_pct']}%")

    print("")
    print("WORK LEFT")
    pending = snapshot.get("work_left", [])
    if pending:
        for w in pending[:15]:
            print(f"- {w}")
        if len(pending) > 15:
            print(f"- ... and {len(pending) - 15} more")
    else:
        print("- No auto-detected blockers")

    print("")
    print(f"Snapshot JSON: {SNAPSHOT_FILE}")
    print(f"TODO Markdown: {TODO_FILE}")


def build_snapshot(target_epochs: int) -> Dict[str, object]:
    checklist, readiness, work_left = build_todo_and_readiness()
    snap = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "active_jobs": get_active_jobs(),
        "download_status": get_download_status(),
        "epoch_status": get_epoch_status(target_epochs=target_epochs),
        "ssl_status": get_ssl_status(),
        "requirements_checklist": checklist,
        "readiness": readiness,
        "work_left": work_left,
    }
    write_exports(snap)
    write_hourly_update(snap)
    return snap


def main() -> None:
    parser = argparse.ArgumentParser(description="Market readiness monitor")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=10, help="Refresh interval seconds")
    parser.add_argument("--target-epochs", type=int, default=50, help="Epoch target for percentage")
    args = parser.parse_args()

    if args.watch:
        while True:
            snap = build_snapshot(target_epochs=args.target_epochs)
            render(snap)
            time.sleep(max(2, args.interval))
    else:
        snap = build_snapshot(target_epochs=args.target_epochs)
        print(json.dumps(snap, indent=2))


if __name__ == "__main__":
    main()
