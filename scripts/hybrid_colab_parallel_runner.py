#!/usr/bin/env python3
"""
Hybrid Colab + Local Parallel Runner

Purpose:
- Offload heavy model training to Google Colab GPU.
- Run lightweight local loops in parallel (YouTube SSL ingestion, readiness monitor, dashboard server).
- Track launched processes for easy inspection/stop.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import choose_executor_for_workload, sort_by_executor_priority

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
JOB_TRACK_FILE = LOGS_DIR / "hybrid_parallel_jobs.json"


def _windows_creation_flags() -> int:
    # Keep child processes detached so this orchestrator can exit cleanly.
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS


def _python_cmd(script_rel: str, args: List[str]) -> List[str]:
    return [sys.executable, script_rel, *args]


def _launch_detached(command: List[str], cwd: Path) -> Dict[str, object]:
    creationflags = _windows_creation_flags()
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return {
        "pid": proc.pid,
        "command": command,
        "cwd": str(cwd),
        "launched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "launched",
    }


def _find_existing_pid(command_hint: str) -> int | None:
    if os.name != "nt":
        return None

    ps_cmd = (
        "Get-CimInstance Win32_Process "
        "| Where-Object { $_.Name -match '^python(\\.exe)?$' -and $_.CommandLine -match '"
        + command_hint
        + "' } "
        "| Select-Object -First 1 -ExpandProperty ProcessId"
    )

    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            text=True,
            cwd=str(PROJECT_ROOT),
        ).strip()
        if out.isdigit():
            return int(out)
    except Exception:
        return None

    return None


def _find_all_pids(command_hint: str) -> List[int]:
    if os.name != "nt":
        return []

    ps_cmd = (
        "Get-CimInstance Win32_Process "
        "| Where-Object { $_.Name -match '^python(\\.exe)?$' -and $_.CommandLine -match '"
        + command_hint
        + "' } "
        "| Select-Object -ExpandProperty ProcessId"
    )

    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        pids: List[int] = []
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids
    except Exception:
        return []


def _dedupe_processes(command_hint: str) -> List[int]:
    pids = _find_all_pids(command_hint)
    if len(pids) <= 1:
        return []

    # Keep the first PID and terminate the rest.
    to_kill = pids[1:]
    for pid in to_kill:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
            else:
                os.kill(pid, 9)
        except Exception:
            pass
    return to_kill


def _launch_or_reuse(name: str, command: List[str], cwd: Path, command_hint: str) -> Dict[str, object]:
    existing_pid = _find_existing_pid(command_hint)
    if existing_pid:
        return {
            "pid": existing_pid,
            "command": command,
            "cwd": str(cwd),
            "launched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "reused",
            "note": f"Reused existing process for {name}",
        }

    return _launch_detached(command, cwd)


def _save_jobs(jobs: Dict[str, object]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    JOB_TRACK_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")


def _build_workload_plan(enable_local_gpu_training: bool) -> Dict[str, List[Dict[str, object]]]:
    workloads: List[Dict[str, object]] = [
        {"name": "colab_training_pipeline", "weight": 1.00},
        {"name": "colab_artifact_sync", "weight": 0.55},
        {"name": "youtube_ssl_loop", "weight": 0.30},
        {"name": "market_readiness_monitor", "weight": 0.20},
        {"name": "dashboard_server", "weight": 0.10},
    ]
    if enable_local_gpu_training:
        workloads.append({"name": "local_gpu_training_loop", "weight": 0.90})

    colab = []
    rtx = []
    for item in workloads:
        executor = choose_executor_for_workload(float(item["weight"]))
        tagged = {**item, "executor": executor}
        if executor == "colab":
            colab.append(tagged)
        else:
            rtx.append(tagged)

    return {
        "colab": sort_by_executor_priority(colab, lambda x: x["weight"], "colab"),
        "rtx": sort_by_executor_priority(rtx, lambda x: x["weight"], "rtx"),
    }


def _print_workload_plan(plan: Dict[str, List[Dict[str, object]]]) -> None:
    print("\nWORKLOAD ROUTING PLAN")
    print("- Colab queue (heaviest first):")
    for item in plan.get("colab", []):
        print(f"  - {item['name']} (weight={item['weight']:.2f})")

    print("- RTX queue (lightest first):")
    for item in plan.get("rtx", []):
        print(f"  - {item['name']} (weight={item['weight']:.2f})")


def start_local_parallel_jobs(
    speed_kmh: float,
    poll_interval: int,
    monitor_interval: int,
    sync_interval: int,
    enable_local_gpu_training: bool,
    dedupe_existing: bool = False,
) -> Dict[str, object]:
    jobs: Dict[str, object] = {
        "runner": "hybrid_colab_parallel_runner",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "jobs": {},
        "dedupe": {},
    }

    if dedupe_existing:
        jobs["dedupe"]["youtube_ssl_verification.py"] = _dedupe_processes("youtube_ssl_verification.py")
        jobs["dedupe"]["market_readiness_monitor.py"] = _dedupe_processes("market_readiness_monitor.py")
        jobs["dedupe"]["http.server 8765"] = _dedupe_processes("http.server 8765")
        jobs["dedupe"]["continuous_training_loop.py"] = _dedupe_processes("continuous_training_loop.py")
        jobs["dedupe"]["colab_artifact_sync.py"] = _dedupe_processes("colab_artifact_sync.py")

    youtube_cmd = _python_cmd(
        "scripts/youtube_ssl_verification.py",
        [
            "--path", "new",
            "--loop",
            "--file", "data/video_sources/video_sources.txt",
            "--speed-kmh", str(speed_kmh),
            "--gentle",
            "--poll-interval", str(poll_interval),
            "--max-videos-per-cycle", "1",
            "--max-verifications-per-video", "8",
            "--cooldown-sec", "2",
        ],
    )
    jobs["jobs"]["youtube_ssl_loop"] = _launch_or_reuse(
        "youtube_ssl_loop",
        youtube_cmd,
        PROJECT_ROOT,
        "youtube_ssl_verification.py",
    )

    monitor_cmd = _python_cmd(
        "scripts/market_readiness_monitor.py",
        [
            "--watch",
            "--interval", str(monitor_interval),
            "--target-epochs", "50",
        ],
    )
    jobs["jobs"]["market_readiness_monitor"] = _launch_or_reuse(
        "market_readiness_monitor",
        monitor_cmd,
        PROJECT_ROOT,
        "market_readiness_monitor.py",
    )

    dashboard_cmd = [sys.executable, "-m", "http.server", "8765"]
    jobs["jobs"]["dashboard_server"] = _launch_or_reuse(
        "dashboard_server",
        dashboard_cmd,
        PROJECT_ROOT,
        "http.server 8765",
    )

    sync_cmd = _python_cmd(
        "scripts/colab_artifact_sync.py",
        [
            "--interval", str(sync_interval),
        ],
    )
    jobs["jobs"]["colab_artifact_sync"] = _launch_or_reuse(
        "colab_artifact_sync",
        sync_cmd,
        PROJECT_ROOT,
        "colab_artifact_sync.py",
    )

    if enable_local_gpu_training:
        local_train_cmd = _python_cmd("continuous_training_loop.py", [])
        jobs["jobs"]["local_gpu_training_loop"] = _launch_or_reuse(
            "local_gpu_training_loop",
            local_train_cmd,
            PROJECT_ROOT,
            "continuous_training_loop.py",
        )

    _save_jobs(jobs)
    return jobs


def launch_colab_flow() -> Path:
    # Import here so this script stays fast and independent unless Colab flow is requested.
    sys.path.insert(0, str(PROJECT_ROOT))
    import colab_training_launcher as ctl  # noqa: WPS433

    notebook_path = Path(ctl.save_notebook_to_drive())
    ctl.launch_colab()
    return notebook_path


def print_colab_next_steps(notebook_path: Path) -> None:
    print("\nCOLAB STEPS")
    print("1) Colab page opened in browser.")
    print(f"2) Upload notebook: {notebook_path.name}")
    print("3) Runtime -> Change runtime type -> GPU (T4/L4/A100)")
    print("4) Run all cells to start heavy training on Colab.")
    print("5) Keep this local machine running for ingestion + monitoring.")


def print_local_status(jobs: Dict[str, object]) -> None:
    print("\nLOCAL PARALLEL JOBS")
    for name, info in jobs.get("jobs", {}).items():
        print(f"- {name}: pid={info.get('pid')}")

    print("\nARTIFACTS")
    print(f"- job tracker: {JOB_TRACK_FILE}")
    print(f"- live dashboard: http://127.0.0.1:8765/dashboard/live_monitor.html")
    print(f"- readiness snapshot: logs/market_readiness_snapshot.json")
    print(f"- hourly metrics: logs/hourly_accuracy_updates.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Colab + local tasks in parallel")
    parser.add_argument("--speed-kmh", type=float, default=150.0, help="Target speed profile for local SSL loop")
    parser.add_argument("--poll-interval", type=int, default=120, help="URL poll interval for SSL loop")
    parser.add_argument("--monitor-interval", type=int, default=10, help="Refresh interval for readiness monitor")
    parser.add_argument("--sync-interval", type=int, default=45, help="Artifact sync interval for Colab weights")
    parser.add_argument("--local-gpu-training", action="store_true", help="Also run local continuous training loop in parallel")
    parser.add_argument("--no-colab", action="store_true", help="Skip Colab browser launch")
    parser.add_argument("--dedupe-existing", action="store_true", help="Terminate duplicate existing local jobs before reuse/launch")
    args = parser.parse_args()

    print("HYBRID PARALLEL MODE")
    print("- Heavy GPU training: Colab")
    print("- Light concurrent tasks: Local machine")

    plan = _build_workload_plan(enable_local_gpu_training=args.local_gpu_training)
    _print_workload_plan(plan)

    notebook_path = PROJECT_ROOT / "COLAB_TRAINING_AUTO.ipynb"
    if not args.no_colab:
        notebook_path = launch_colab_flow()

    jobs = start_local_parallel_jobs(
        speed_kmh=args.speed_kmh,
        poll_interval=max(30, args.poll_interval),
        monitor_interval=max(5, args.monitor_interval),
        sync_interval=max(10, args.sync_interval),
        enable_local_gpu_training=args.local_gpu_training,
        dedupe_existing=args.dedupe_existing,
    )

    print_colab_next_steps(notebook_path)
    print_local_status(jobs)
    print("\nDONE: Hybrid parallel pipeline launched.")


if __name__ == "__main__":
    main()
