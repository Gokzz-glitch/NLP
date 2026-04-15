#!/usr/bin/env python3
"""
SmartSalai Edge-Sentinel Production Launcher (Hardened)

This launcher performs strict preflight checks, starts required services,
verifies health, and keeps processes supervised until shutdown.
"""

from __future__ import annotations

import json
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import urlopen

from core.secret_manager import SecretManager

# Fix Unicode encoding for Windows consoles.
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.resolve()
LOG_DIR = PROJECT_ROOT / "logs" / "production"


@dataclass
class ServiceSpec:
    name: str
    command: List[str]
    health_url: Optional[str] = None
    startup_timeout_sec: int = 30
    required: bool = True


class SmartSalaiProduction:
    def __init__(self, enable_live_vision: Optional[bool] = None) -> None:
        self.project_root = PROJECT_ROOT
        self.processes: Dict[str, subprocess.Popen] = {}
        self.log_handles = []
        self.shutdown_requested = False
        self.config = self.load_deployment_config()
        self.enable_live_vision = enable_live_vision

    def load_deployment_config(self) -> Dict:
        config_file = self.project_root / "DEPLOYMENT_PARAMETERS.json"
        if not config_file.exists():
            return {}
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _print_header(self) -> None:
        print("=" * 80)
        print(" SmartSalai Edge-Sentinel Production Launcher (Hardened)")
        print("=" * 80)
        print(f" Project Root: {self.project_root}")
        print(f" Started At  : {datetime.now().isoformat(timespec='seconds')}")
        print("=" * 80)

    def _deployment_value(self, key: str, default):
        deployment_cfg = self.config.get("deployment_config", {})
        return deployment_cfg.get(key, default)

    @staticmethod
    def _is_port_free(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return s.connect_ex((host, port)) != 0

    @staticmethod
    def _wait_for_http_health(url: str, timeout_sec: int) -> bool:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                with urlopen(url, timeout=2.0) as resp:
                    if 200 <= resp.status < 500:
                        return True
            except HTTPError as exc:
                # Some services return 404 for a generic health path; non-5xx
                # still proves the HTTP server is alive and reachable.
                if 400 <= exc.code < 500:
                    return True
            except URLError:
                pass
            except Exception:
                pass
            time.sleep(1)
        return False

    def _require_paths(self) -> bool:
        required = [
            self.project_root / "agent2_dashboard" / "api.py",
            self.project_root / "scripts" / "live_vision_stream.py",
            self.project_root / "core" / "secret_manager.py",
        ]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            print("[FAIL] Required files are missing:")
            for p in missing:
                print(f"   - {p}")
            return False
        return True

    def _validate_secrets(self) -> bool:
        try:
            SecretManager(strict_mode=True)
            return True
        except Exception as exc:
            print("[FAIL] Secret validation failed:")
            print(f"   {exc}")
            print("   Set required keys in environment/.env before startup.")
            return False

    def preflight_checks(self) -> bool:
        print("\n[*] Running preflight checks...")

        if sys.version_info < (3, 10):
            print("[FAIL] Python 3.10+ is required.")
            return False

        LOG_DIR.mkdir(parents=True, exist_ok=True)

        if not self._require_paths():
            return False

        if not self._validate_secrets():
            return False

        dashboard_port = int(os.getenv("DASHBOARD_PORT", self._deployment_value("dashboard_port", 8765)))
        if not self._is_port_free("127.0.0.1", dashboard_port):
            print(f"[FAIL] Dashboard port {dashboard_port} is already in use.")
            return False

        if self.enable_live_vision is None:
            enable_live = os.getenv("ENABLE_LIVE_VISION", "1").strip().lower() in {"1", "true", "yes", "on"}
        else:
            enable_live = self.enable_live_vision
        if enable_live:
            vision_port = int(os.getenv("LIVE_VISION_PORT", "9876"))
            if not self._is_port_free("127.0.0.1", vision_port):
                print(f"[FAIL] Live vision port {vision_port} is already in use.")
                return False

        print("[OK] Preflight checks passed.")
        return True

    def _start_service(self, spec: ServiceSpec, env: Dict[str, str]) -> bool:
        log_path = LOG_DIR / f"{spec.name.lower().replace(' ', '_')}.log"
        log_file = open(log_path, "a", encoding="utf-8")
        self.log_handles.append(log_file)

        print(f"[*] Starting {spec.name}...")
        proc = subprocess.Popen(
            spec.command,
            cwd=str(self.project_root),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.processes[spec.name] = proc

        # Give the process a brief chance to fail fast.
        time.sleep(2)
        if proc.poll() is not None:
            print(f"[FAIL] {spec.name} exited early (code {proc.returncode}).")
            print(f"       See log: {log_path}")
            return False

        if spec.health_url:
            healthy = self._wait_for_http_health(spec.health_url, spec.startup_timeout_sec)
            if not healthy:
                print(f"[FAIL] {spec.name} health check timed out: {spec.health_url}")
                print(f"       See log: {log_path}")
                return False

        print(f"[OK] {spec.name} started.")
        return True

    def start_services(self) -> bool:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.project_root)

        dashboard_port = int(os.getenv("DASHBOARD_PORT", self._deployment_value("dashboard_port", 8765)))
        health_url = f"http://127.0.0.1:{dashboard_port}/health"

        specs = [
            ServiceSpec(
                name="Dashboard API",
                command=[sys.executable, "-u", "agent2_dashboard/api.py"],
                health_url=health_url,
                startup_timeout_sec=45,
                required=True,
            ),
        ]

        if self.enable_live_vision is None:
            enable_live = os.getenv("ENABLE_LIVE_VISION", "1").strip().lower() in {"1", "true", "yes", "on"}
        else:
            enable_live = self.enable_live_vision
        if enable_live:
            stream_url = os.getenv("VISION_STREAM_URL", self._deployment_value("vision_stream", "http://127.0.0.1:8080/video"))
            vision_port = os.getenv("LIVE_VISION_PORT", "9876")
            specs.append(
                ServiceSpec(
                    name="Live Vision Stream",
                    command=[
                        sys.executable,
                        "-u",
                        "scripts/live_vision_stream.py",
                        "--stream",
                        str(stream_url),
                        "--port",
                        str(vision_port),
                    ],
                    health_url=None,
                    startup_timeout_sec=30,
                    required=False,
                )
            )

        for spec in specs:
            ok = self._start_service(spec, env)
            if not ok:
                if spec.required:
                    return False
                print(f"[WARN] Optional service '{spec.name}' failed to start; continuing.")

        print("\n[OK] Core production services are online.")
        print(f"     Dashboard URL: http://127.0.0.1:{dashboard_port}")
        print(f"     Logs directory: {LOG_DIR}")
        return True

    def _shutdown(self) -> None:
        if self.shutdown_requested:
            return
        self.shutdown_requested = True

        print("\n[*] Shutting down services...")
        for name, proc in self.processes.items():
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

        deadline = time.time() + 10
        while time.time() < deadline:
            alive = [p for p in self.processes.values() if p.poll() is None]
            if not alive:
                break
            time.sleep(0.25)

        for name, proc in self.processes.items():
            if proc.poll() is None:
                try:
                    proc.kill()
                    print(f"[WARN] Force-killed: {name}")
                except Exception:
                    pass

        for fh in self.log_handles:
            try:
                fh.flush()
                fh.close()
            except Exception:
                pass

        print("[OK] Shutdown complete.")

    def _signal_handler(self, signum, frame) -> None:
        del signum, frame
        self._shutdown()

    def monitor(self) -> int:
        if os.name != "nt":
            signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        print("\n[*] Monitoring services. Press Ctrl+C to stop.")
        try:
            while not self.shutdown_requested:
                for name, proc in self.processes.items():
                    code = proc.poll()
                    if code is not None:
                        print(f"[FAIL] Service exited: {name} (code {code})")
                        self._shutdown()
                        return 1
                time.sleep(2)
        finally:
            self._shutdown()
        return 0

    def run(self) -> int:
        self._print_header()

        if not self.preflight_checks():
            return 1

        if not self.start_services():
            self._shutdown()
            return 1

        return self.monitor()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SmartSalai production launcher")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run preflight checks only and exit.",
    )
    parser.add_argument(
        "--no-live-vision",
        action="store_true",
        help="Disable live vision process startup for this run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    launcher = SmartSalaiProduction(enable_live_vision=not args.no_live_vision)
    if args.preflight_only:
        launcher._print_header()
        return 0 if launcher.preflight_checks() else 1
    return launcher.run()


if __name__ == "__main__":
    sys.exit(main())
