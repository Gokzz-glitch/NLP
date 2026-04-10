#!/usr/bin/env python3
"""
Real-World SSL Goal Loop

Goal:
- Run end-to-end loop until real-world agreement/accuracy reaches target threshold.
- Pipeline per cycle:
  1) Optional G0DM0D3 research prompt refresh
  2) Ingest open-source dashcam sources (YouTube/direct links/local files)
  3) YOLO inference + Gemini SSL verification
  4) Merge self-labeled samples into YOLO dataset
  5) Retrain YOLO on SSL dataset
  6) Re-evaluate on validation dashcam sources
  7) Stop automatically when target is achieved

Default stop target: 95.0% agreement on validation batch.
"""

from __future__ import annotations

import argparse
import glob
import hmac
import json
import os
import gc
import atexit
import shutil
import subprocess
import sys
import time
import textwrap
import logging
from urllib import error, request
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ultralytics import YOLO

try:
    import torch
except Exception:
    torch = None

try:
    from huggingface_hub import hf_hub_download, HfApi
except Exception:
    hf_hub_download = None
    HfApi = None

try:
    import wandb
except Exception:
    wandb = None

# Project-local imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.youtube_ssl_verification import YouTubeSSLVerificationPipeline
from scripts.ssl_data_formatter import format_ssl_data
from scripts.road_scene_taxonomy import canonicalize_label, class_id_map, class_names, deterministic_split_key, write_ssl_training_yaml
from scripts.utils.gpu_runtime import resolve_ultralytics_device
LOCK_PATH = PROJECT_ROOT / "logs" / "realworld_ssl_goal_loop.lock"
logger = logging.getLogger("edge_sentinel.loop")
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _pid_looks_like_realworld_loop(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        return _pid_exists(pid)

    try:
        cmd = (
            "$p = Get-CimInstance Win32_Process -Filter \"ProcessId = "
            + str(pid)
            + "\"; if ($p) { $p.CommandLine }"
        )
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                cmd,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        line = (out or "").strip().lower()
        return "realworld_ssl_goal_loop.py" in line
    except Exception:
        return _pid_exists(pid)


def _acquire_single_instance_lock() -> None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    current_pid = os.getpid()

    if LOCK_PATH.exists():
        try:
            payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            existing_pid = int(payload.get("pid", 0) or 0)
        except Exception:
            existing_pid = 0

        if _pid_exists(existing_pid) and _pid_looks_like_realworld_loop(existing_pid):
            raise SystemExit(
                f"realworld_ssl_goal_loop already running (pid={existing_pid}). "
                "Stop existing loop before starting another instance."
            )

    payload = {
        "pid": current_pid,
        "started_at": datetime.now().isoformat(),
        "argv": sys.argv,
    }
    LOCK_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _release_lock() -> None:
        try:
            if LOCK_PATH.exists():
                data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
                if int(data.get("pid", 0) or 0) == current_pid:
                    LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_release_lock)


@dataclass
class CycleResult:
    cycle: int
    started_at: str
    ended_at: str
    model_path: str
    train_sources_count: int
    val_sources_count: int
    ssl_samples_before: int
    ssl_samples_after: int
    val_agreement_rate: float
    val_verified: int
    val_detections: int
    train_map50: float
    train_loss: float
    reached_target: bool
    notes: str


class RealWorldSSLGoalLoop:
    def __init__(
        self,
        target_accuracy: float = 95.0,
        max_cycles: int = 20,
        min_val_verified: int = 30,
        train_epochs: int = 2,
        train_sources_file: str = "video_sources.txt",
        val_sources_file: str = "video_sources_val.txt",
        model_seed: str = "yolov8_pothole.pt",
        speed_kmh: float = 120.0,
        max_videos_per_cycle: int = 2,
        max_verifications_per_video: int = 20,
        cooldown_sec: float = 1.0,
        gentle: bool = False,
        enable_godmod3_research: bool = True,
        godmod3_research_mode: str = "classic",
        use_wandb: bool = True,
        auto_select_best_weight: bool = True,
        hf_discovery_limit: int = 8,
        hf_download_limit: int = 4,
        benchmark_videos_cap: int = 1,
        real_dataset_yaml: str = "",
        gpu_only: bool = True,
        allow_yolo_proxy_when_quota_backoff: bool = True,
        yolo_proxy_min_conf: float = 0.60,
        use_consortium: bool = True,
    ):
        self.target_accuracy = float(target_accuracy)
        self.max_cycles = int(max_cycles)
        self.min_val_verified = int(min_val_verified)
        self.train_epochs = int(train_epochs)
        self.train_sources_file = str(train_sources_file)
        self.val_sources_file = str(val_sources_file)
        self.speed_kmh = float(speed_kmh)
        self.max_videos_per_cycle = int(max_videos_per_cycle)
        self.max_verifications_per_video = int(max_verifications_per_video)
        self.cooldown_sec = float(cooldown_sec)
        self.gentle = bool(gentle)
        self.enable_godmod3_research = bool(enable_godmod3_research)
        mode = str(godmod3_research_mode or "classic").strip().lower()
        self.godmod3_research_mode = mode if mode in {"classic", "ultraplinian"} else "classic"
        self.use_wandb = bool(use_wandb)
        self.auto_select_best_weight = bool(auto_select_best_weight)
        self.hf_discovery_limit = int(hf_discovery_limit)
        self.hf_download_limit = int(hf_download_limit)
        self.benchmark_videos_cap = int(benchmark_videos_cap)
        self.real_dataset_yaml = str(real_dataset_yaml or "").strip()
        self.gpu_only = bool(gpu_only)
        self.allow_yolo_proxy_when_quota_backoff = bool(allow_yolo_proxy_when_quota_backoff)
        self.yolo_proxy_min_conf = float(max(0.0, min(1.0, yolo_proxy_min_conf)))
        self.use_consortium = bool(use_consortium)
        self.rollback_score_margin = 0.25
        self.scene_classes = class_names()
        self.scene_class_ids = class_id_map()

        self._ensure_ssl_api_key_env()

        self.logs_dir = PROJECT_ROOT / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.loop_log_path = self.logs_dir / "realworld_ssl_goal_history.json"
        self.research_digest_dir = self.logs_dir / "research_crawl"
        self.validation_speed_buckets = self._load_validation_speed_buckets()
        self.research_sources_file = PROJECT_ROOT / "research_sources.txt"
        self.research_crawl_limit = int(os.getenv("SSL_RESEARCH_CRAWL_LIMIT", "4"))

        self.models_dir = PROJECT_ROOT / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.weights_archive_dir = self.models_dir / "weights_archive"
        self.weights_archive_dir.mkdir(parents=True, exist_ok=True)

        # Pick the strongest available seed model.
        preferred = [
            PROJECT_ROOT / "models" / "best_realworld_ssl.pt",
            PROJECT_ROOT / "models" / "best_deployable.pt",
            PROJECT_ROOT / "models" / "colab_best_latest.pt",
            PROJECT_ROOT / "models" / "best_colab_mirror.pt",
            PROJECT_ROOT / "models" / "best_continuous.pt",
            PROJECT_ROOT / "models" / "best.pt",
            PROJECT_ROOT / model_seed,
            PROJECT_ROOT / "yolov8_pothole_refined.pt",
            PROJECT_ROOT / "yolov8_pothole.pt",
            PROJECT_ROOT / "yolov8n.pt",
        ]

        self.current_model_path = None
        for p in preferred:
            if p.exists():
                self.current_model_path = str(p)
                break
        if not self.current_model_path:
            self.current_model_path = model_seed

        self.train_device, self.train_device_name, self.device_meta = resolve_ultralytics_device(
            torch,
            require_gpu=self.gpu_only,
        )
        if self.device_meta.get("cuda_available", False):
            print(
                f"[RUNTIME] CUDA enabled on {self.train_device_name} "
                f"(ultralytics_device={self.train_device})"
            )
        else:
            raise RuntimeError("GPU_ONLY enforced: CUDA unavailable; CPU fallback disabled")

        self.history = self._load_history()
        self.wandb_run = None

    @staticmethod
    def _speed_bucket_label(speed_kmh: float) -> str:
        if speed_kmh < 30:
            return "low"
        if speed_kmh < 90:
            return "mid"
        return "high"

    def _load_validation_speed_buckets(self) -> List[float]:
        raw = os.getenv("SSL_VALIDATION_SPEED_BUCKETS", "1,60,150")
        values: List[float] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                values.append(float(token))
            except Exception:
                continue
        values = sorted({max(1.0, min(150.0, value)) for value in values})
        return values or [1.0, 60.0, 150.0]

    def _load_research_sources(self) -> List[str]:
        if self.research_sources_file.exists():
            sources = [
                line.strip()
                for line in self.research_sources_file.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if sources:
                return sources[: self.research_crawl_limit]

        # Default research sources are lightweight, stable reference pages that cover
        # agent orchestration, crawl pipelines, and multimodal evaluation patterns.
        return [
            "https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/README.md",
            "https://raw.githubusercontent.com/firecrawl/firecrawl/main/README.md",
            "https://raw.githubusercontent.com/googlecloudplatform/generative-ai/main/README.md",
            "https://raw.githubusercontent.com/googlecloudplatform/generative-ai/main/vision/sample-apps/V-Start/README.md",
        ][: self.research_crawl_limit]

    @staticmethod
    def _fetch_url_text(url: str, timeout: int = 20) -> str:
        req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    @staticmethod
    def _extract_research_excerpt(text: str, max_lines: int = 24) -> str:
        lines = [line.rstrip() for line in text.splitlines()]
        filtered: List[str] = []
        keywords = (
            "speed", "validation", "perception", "temporal", "fusion", "autonomous",
            "evaluation", "accuracy", "robust", "crawl", "agent", "gemini", "firecrawl",
        )
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if any(keyword in stripped.lower() for keyword in keywords):
                filtered.append(stripped)
            if len(filtered) >= max_lines:
                break
        if not filtered:
            filtered = [line.strip() for line in lines if line.strip()][:max_lines]
        return "\n".join(filtered)

    def _run_research_crawl_refresh(self, cycle: int) -> Optional[str]:
        sources = self._load_research_sources()
        if not sources:
            return None

        self.research_digest_dir.mkdir(parents=True, exist_ok=True)
        digest_lines = [
            f"# Research Crawl Digest - Cycle {cycle}",
            f"Timestamp: {datetime.now().isoformat()}",
            "",
        ]
        manifest: List[Dict[str, str]] = []

        for url in sources:
            try:
                text = self._fetch_url_text(url, timeout=20)
                excerpt = self._extract_research_excerpt(text)
                digest_lines.extend([
                    f"## Source: {url}",
                    "```text",
                    excerpt,
                    "```",
                    "",
                ])
                manifest.append({"url": url, "status": "ok", "excerpt_lines": str(len(excerpt.splitlines()))})
            except Exception as exc:
                digest_lines.extend([
                    f"## Source: {url}",
                    f"Fetch failed: {exc}",
                    "",
                ])
                manifest.append({"url": url, "status": f"error: {exc}"})

        digest_path = self.research_digest_dir / f"research_cycle_{cycle:03d}.md"
        digest_path.write_text("\n".join(digest_lines).strip() + "\n", encoding="utf-8")
        manifest_path = self.research_digest_dir / f"research_cycle_{cycle:03d}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.history.setdefault("research_crawls", []).append({
            "cycle": cycle,
            "digest_path": str(digest_path),
            "manifest_path": str(manifest_path),
            "sources": sources,
        })
        self._save_history()
        self._wandb_log({"research/cycle": cycle, "research/source_count": len(sources)})
        return str(digest_path)

    def _evaluate_speed_buckets(self, val_sources: List[str], model_path: str) -> Dict[str, Dict[str, Any]]:
        bucket_reports: Dict[str, Dict[str, Any]] = {}
        for speed_kmh in self.validation_speed_buckets:
            label = f"{int(speed_kmh)}kmh"
            report = self._run_ssl_verification(
                sources=val_sources,
                model_path=model_path,
                skip_processed=False,
                speed_kmh=speed_kmh,
            )
            time.sleep(0.05)  # Physical thermal cooldown: 50ms pulse between validation buckets
            metrics = self._score_validation_report(report)
            bucket_reports[label] = {
                "speed_kmh": speed_kmh,
                "metrics": metrics,
                "report": report,
            }
        return bucket_reports

    @staticmethod
    def _weighted_bucket_score(bucket_reports: Dict[str, Dict[str, Any]]) -> float:
        weights = {
            "1kmh": 0.2,
            "60kmh": 0.3,
            "150kmh": 0.5,
        }
        total = 0.0
        total_weight = 0.0
        for label, bundle in bucket_reports.items():
            weight = weights.get(label, 1.0)
            total += float(bundle["metrics"].get("score", 0.0)) * weight
            total_weight += weight
        return total / total_weight if total_weight > 0 else 0.0

    def _ensure_ssl_api_key_env(self) -> None:
        """Ensure Gemini and OpenRouter API keys are loaded for SSL teacher and fallback."""
        # Prefer explicit Gemini keys, else fallback to OpenRouter, else GODMODE
        gemini_pool = os.getenv("GEMINI_API_KEYS", "").strip()
        gemini_single = os.getenv("GEMINI_API_KEY", "").strip()
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        godmode_pool = os.getenv("GODMODE_API_KEYS", "").strip()
        godmode_single = os.getenv("GODMODE_API_KEY", "").strip() or os.getenv("GODMODE_KEY", "").strip()

        if not gemini_pool and not gemini_single:
            if openrouter_key:
                os.environ["GEMINI_API_KEY"] = openrouter_key
                print("[SSL LOOP] Using OPENROUTER_API_KEY as GEMINI fallback for teacher.")
            elif godmode_pool:
                os.environ["GEMINI_API_KEYS"] = godmode_pool
                print("[SSL LOOP] Using GODMODE_API_KEYS as GEMINI_API_KEYS fallback")
            elif godmode_single:
                os.environ["GEMINI_API_KEY"] = godmode_single
                print("[SSL LOOP] Using GODMODE API key as GEMINI_API_KEY fallback")

    @staticmethod
    def _parse_yaml_path_line(raw_line: str) -> Optional[str]:
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            return None
        _, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        return value or None

    def _prepare_real_dataset_yaml(self, yaml_path: Path) -> Path:
        """Fix common cloud-only paths (kaggle/colab) into local workspace paths."""
        if not yaml_path.exists():
            return yaml_path

        raw_lines = yaml_path.read_text(encoding="utf-8").splitlines()
        parent = yaml_path.parent
        local_train = (parent / "train" / "images").resolve()
        local_val = (parent / "valid" / "images").resolve()
        local_test = (parent / "test" / "images").resolve()

        changed = False
        rewritten = []

        for line in raw_lines:
            stripped = line.strip()
            if stripped.startswith("train:"):
                current = self._parse_yaml_path_line(line) or ""
                if ("/kaggle/" in current or "/content/" in current) and local_train.exists():
                    line = f"train: {local_train.as_posix()}"
                    changed = True
            elif stripped.startswith("val:"):
                current = self._parse_yaml_path_line(line) or ""
                if ("/kaggle/" in current or "/content/" in current) and local_val.exists():
                    line = f"val: {local_val.as_posix()}"
                    changed = True
            elif stripped.startswith("test:"):
                current = self._parse_yaml_path_line(line) or ""
                if ("/kaggle/" in current or "/content/" in current) and local_test.exists():
                    line = f"test: {local_test.as_posix()}"
                    changed = True
            rewritten.append(line)

        if not changed:
            return yaml_path

        runtime_yaml = yaml_path.with_name("data.runtime.yaml")
        runtime_yaml.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        return runtime_yaml

    def _resolve_training_data_yaml(self) -> str:
        """Prefer real labeled datasets when available; otherwise fallback to SSL dataset."""
        candidates: List[Path] = []

        ssl_dataset_yaml = PROJECT_ROOT / "datasets" / "ssl_v1" / "data.yaml"
        if ssl_dataset_yaml.exists():
            return str(ssl_dataset_yaml)

        if self.real_dataset_yaml:
            candidate = Path(self.real_dataset_yaml)
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
            candidates.append(candidate)

        candidates.extend(
            [
                PROJECT_ROOT / "raw_data" / "pothole_dataset" / "data.runtime.yaml",
                PROJECT_ROOT / "raw_data" / "pothole_dataset" / "data_local.yaml",
                PROJECT_ROOT / "raw_data" / "pothole_dataset" / "data.yaml",
                PROJECT_ROOT / "ssl_training.yaml",
            ]
        )

        for candidate in candidates:
            if candidate.exists():
                if candidate.name == "data.yaml":
                    candidate = self._prepare_real_dataset_yaml(candidate)
                return str(candidate)

        return "ssl_training.yaml"

    def _wandb_init(self):
        if not self.use_wandb or wandb is None:
            return
        if self.wandb_run is not None:
            return

        try:
            self.wandb_run = wandb.init(
                project=os.getenv("WANDB_PROJECT", "smartsalai-realworld-ssl"),
                name=f"realworld_ssl_goal_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                config={
                    "target_accuracy": self.target_accuracy,
                    "max_cycles": self.max_cycles,
                    "train_epochs": self.train_epochs,
                    "speed_kmh": self.speed_kmh,
                    "max_videos_per_cycle": self.max_videos_per_cycle,
                    "max_verifications_per_video": self.max_verifications_per_video,
                    "auto_select_best_weight": self.auto_select_best_weight,
                    "allow_yolo_proxy_when_quota_backoff": self.allow_yolo_proxy_when_quota_backoff,
                    "yolo_proxy_min_conf": self.yolo_proxy_min_conf,
                },
            )
        except Exception:
            self.wandb_run = None

    def _wandb_log(self, payload: Dict):
        if self.wandb_run is None:
            return
        try:
            self.wandb_run.log(payload)
        except Exception:
            pass

    def _collect_local_weight_candidates(self) -> List[str]:
        """Collect local open-source checkpoints likely usable by Ultralytics."""
        prioritized_paths = [
            PROJECT_ROOT / "models" / "best_realworld_ssl.pt",
            PROJECT_ROOT / "models" / "best_deployable.pt",
            PROJECT_ROOT / "models" / "colab_best_latest.pt",
            PROJECT_ROOT / "models" / "best_colab_mirror.pt",
            PROJECT_ROOT / "models" / "best_continuous.pt",
            PROJECT_ROOT / "models" / "best.pt",
            PROJECT_ROOT / "yolov8_pothole_refined.pt",
            PROJECT_ROOT / "yolov8_pothole.pt",
            PROJECT_ROOT / "yolov8n.pt",
        ]

        candidates = []
        seen = set()
        for path in prioritized_paths:
            if path.exists() and path.is_file():
                ap = str(path.resolve())
                if ap not in seen:
                    seen.add(ap)
                    candidates.append(ap)

        for pattern in [
            str(PROJECT_ROOT / "models" / "*.pt"),
            str(PROJECT_ROOT / "*.pt"),
            str(PROJECT_ROOT / "runs" / "detect" / "**" / "best.pt"),
        ]:
            for p in glob.glob(pattern, recursive=True):
                ap = str(Path(p).resolve())
                if ap not in seen and Path(ap).is_file():
                    seen.add(ap)
                    candidates.append(ap)
        return candidates

    def _archive_weight_candidate(self, model_path: str, source_label: str) -> Optional[str]:
        """Keep a durable copy of every candidate weight that was evaluated."""
        candidate = Path(model_path)
        if not candidate.exists():
            return None

        safe_label = source_label.replace("/", "__").replace(":", "_").replace(" ", "_")
        suffix = candidate.suffix or ".pt"
        archived_name = f"{safe_label}__{candidate.stem}{suffix}"
        archived_path = self.weights_archive_dir / archived_name
        try:
            shutil.copy2(candidate, archived_path)
            return str(archived_path)
        except Exception:
            return None

    def _discover_hf_weight_candidates(self) -> List[Dict[str, str]]:
        """Find open-source pothole/hazard YOLO checkpoints on Hugging Face."""
        if HfApi is None:
            return []

        api = HfApi()
        queries = ["pothole yolov8", "road hazard yolo", "accident detection yolov8"]
        found = []
        seen_repo = set()

        for q in queries:
            try:
                models = api.list_models(search=q, limit=self.hf_discovery_limit)
            except Exception:
                continue

            for m in models:
                repo = getattr(m, "id", None)
                if not repo or repo in seen_repo:
                    continue
                seen_repo.add(repo)
                found.append({"repo_id": repo})

        return found[: self.hf_download_limit]

    def _download_hf_weight_candidate(self, repo_id: str) -> Optional[str]:
        """Try common Ultralytics weight filenames from HF repo."""
        if hf_hub_download is None:
            return None

        filenames = ["best.pt", "model.pt", "weights/best.pt"]
        for fn in filenames:
            try:
                local = hf_hub_download(repo_id=repo_id, filename=fn, local_dir=str(self.models_dir))
                if local and Path(local).exists():
                    stable_name = repo_id.replace("/", "__") + "__" + Path(fn).name
                    stable_path = self.models_dir / stable_name
                    shutil.copy2(local, stable_path)
                    return str(stable_path)
            except Exception:
                continue
        return None

    def _benchmark_weight(self, model_path: str, val_sources: List[str]) -> Tuple[float, int, int]:
        """Return (agreement_rate, verified_count, detections_count)."""
        prev_cap = self.max_videos_per_cycle
        try:
            self.max_videos_per_cycle = max(1, self.benchmark_videos_cap)
            report = self._run_ssl_verification(
                sources=val_sources,
                model_path=model_path,
                skip_processed=True,
                speed_kmh=self.speed_kmh,
            )
            return self._extract_accuracy_proxy(report)
        finally:
            self.max_videos_per_cycle = prev_cap

    def _select_best_weight(self, val_sources: List[str]) -> str:
        """Benchmark local + discovered HF candidates and return best model path."""
        scored = []
        archive_records = []

        local_candidates = self._collect_local_weight_candidates()
        for c in local_candidates:
            try:
                agreement, verified, detections = self._benchmark_weight(c, val_sources)
                scored.append((agreement, verified, detections, c, "local"))
                archived = self._archive_weight_candidate(c, "local")
                archive_records.append({
                    "source": "local",
                    "path": c,
                    "archived_path": archived,
                    "agreement": agreement,
                    "verified": verified,
                    "detections": detections,
                })
                self._wandb_log({
                    "weight_benchmark/agreement": agreement,
                    "weight_benchmark/verified": verified,
                    "weight_benchmark/detections": detections,
                    "weight_benchmark/source": 0,
                })
            except Exception:
                continue

        hf_candidates = self._discover_hf_weight_candidates()
        for item in hf_candidates:
            repo_id = item["repo_id"]
            downloaded = self._download_hf_weight_candidate(repo_id)
            if not downloaded:
                continue
            try:
                agreement, verified, detections = self._benchmark_weight(downloaded, val_sources)
                scored.append((agreement, verified, detections, downloaded, f"hf:{repo_id}"))
                archived = self._archive_weight_candidate(downloaded, f"hf__{repo_id}")
                archive_records.append({
                    "source": f"hf:{repo_id}",
                    "path": downloaded,
                    "archived_path": archived,
                    "agreement": agreement,
                    "verified": verified,
                    "detections": detections,
                })
                self._wandb_log({
                    "weight_benchmark/agreement": agreement,
                    "weight_benchmark/verified": verified,
                    "weight_benchmark/detections": detections,
                    "weight_benchmark/source": 1,
                })
            except Exception:
                continue

        if not scored:
            return self.current_model_path

        # Prefer higher agreement, then more verified samples, then detections.
        scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        best_agreement, best_verified, best_detections, best_path, best_source = scored[0]

        benchmark_manifest = {
            "selected": {
                "path": best_path,
                "source": best_source,
                "agreement": best_agreement,
                "verified": best_verified,
                "detections": best_detections,
            },
            "evaluated": archive_records,
        }
        try:
            (self.weights_archive_dir / "benchmark_manifest.json").write_text(
                json.dumps(benchmark_manifest, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

        print(
            f"Auto-selected best weight: {best_path} | source={best_source} | "
            f"agreement={best_agreement:.2f}% verified={best_verified} detections={best_detections}"
        )
        return best_path

    def _load_history(self) -> Dict:
        if self.loop_log_path.exists():
            try:
                return json.loads(self.loop_log_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "session_started_at": datetime.now().isoformat(),
            "target_accuracy": self.target_accuracy,
            "max_cycles": self.max_cycles,
            "cycles": [],
            "best": {
                "cycle": None,
                "val_agreement_rate": 0.0,
                "model_path": self.current_model_path,
            },
            "status": "running",
        }

    def _save_history(self):
        self.loop_log_path.write_text(json.dumps(self.history, indent=2), encoding="utf-8")

    def _read_sources(self, file_path: str) -> List[str]:
        p = PROJECT_ROOT / file_path
        if not p.exists():
            return []
        urls = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    urls.append(s)
        return urls

    def _ensure_val_sources(self):
        val_path = PROJECT_ROOT / self.val_sources_file
        if val_path.exists():
            return

        # Create a placeholder instead of auto-splitting train sources.
        # This prevents accidental train/validation leakage.
        val_path.write_text(
            "# Add validation-only dashcam URLs/files here (must not overlap with train sources)\n",
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_source_token(source: str) -> str:
        return str(source or "").strip().rstrip("/").lower()

    def _validate_source_partitions(self, train_sources: List[str], val_sources: List[str]) -> None:
        min_train_sources = 2
        min_val_sources = 2

        if len(train_sources) < min_train_sources:
            raise RuntimeError(
                f"Training sources too small: {len(train_sources)}. "
                f"Require at least {min_train_sources} unique sources."
            )

        if len(val_sources) < min_val_sources:
            raise RuntimeError(
                f"Validation sources too small: {len(val_sources)}. "
                f"Require at least {min_val_sources} unique sources."
            )

        train_norm = {self._normalize_source_token(s) for s in train_sources if str(s).strip()}
        val_norm = {self._normalize_source_token(s) for s in val_sources if str(s).strip()}

        overlap = sorted(train_norm.intersection(val_norm))
        if overlap:
            preview = ", ".join(overlap[:3])
            raise RuntimeError(
                "Train/validation source leakage detected. "
                f"Found {len(overlap)} overlapping source(s). Example: {preview}. "
                "Use disjoint source files for --train-sources and --val-sources."
            )

    def _count_ssl_samples(self) -> int:
        labels_dir = PROJECT_ROOT / "datasets" / "ssl_v1" / "labels"
        if not labels_dir.exists():
            return 0
        return sum(1 for p in labels_dir.glob("*.txt") if p.is_file())

    def _sync_ssl_training_manifests(self) -> Optional[str]:
        dataset_root = PROJECT_ROOT / "datasets" / "ssl_v1"
        images_dir = dataset_root / "images"
        if not images_dir.exists():
            return None

        image_paths = [
            path for path in images_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        ]
        if not image_paths:
            return None

        train_entries: List[str] = []
        val_entries: List[str] = []
        for image_path in sorted(image_paths):
            split_key = deterministic_split_key(image_path)
            if split_key % 10 == 0:
                val_entries.append(image_path.resolve().as_posix())
            else:
                train_entries.append(image_path.resolve().as_posix())

        if not train_entries:
            train_entries = list(val_entries[:1])
        if not val_entries and train_entries:
            val_entries = [train_entries[-1]]

        train_manifest = dataset_root / "train.txt"
        val_manifest = dataset_root / "val.txt"
        train_manifest.write_text("\n".join(train_entries) + "\n", encoding="utf-8")
        val_manifest.write_text("\n".join(val_entries) + "\n", encoding="utf-8")

        yaml_path = write_ssl_training_yaml(dataset_root, self.scene_classes)
        self.history.setdefault("ssl_dataset", {})["train_manifest"] = str(train_manifest)
        self.history.setdefault("ssl_dataset", {})["val_manifest"] = str(val_manifest)
        self.history.setdefault("ssl_dataset", {})["yaml"] = str(yaml_path)
        self._save_history()
        return str(yaml_path)

    def _run_godmod3_research_hint(self, cycle: int):
        if not self.enable_godmod3_research:
            return

        script = PROJECT_ROOT / "scripts" / "godmod3_research.py"
        if not script.exists():
            return

        query = (
            "Given a real-world dashcam SSL loop covering potholes, speed breakers, signs, lanes, "
            "vehicles, pedestrians, cyclists, and traffic control objects, suggest one practical "
            "improvement for SSL data quality and one for robustness under rain/night/occlusion conditions."
        )

        cmd = [
            sys.executable,
            str(script),
            "--mode",
            self.godmod3_research_mode,
            "--query",
            query,
            "--save",
        ]
        try:
            # Best-effort only. No hard failure if endpoint/key unavailable.
            subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False, timeout=90)
        except Exception:
            pass

    def _run_research_refresh(self, cycle: int):
        # Keep this best-effort. The loop should keep training even when research endpoints are unavailable.
        self._run_godmod3_research_hint(cycle)
        return self._run_research_crawl_refresh(cycle)

    def _run_ssl_verification(
        self,
        sources: List[str],
        model_path: str,
        skip_processed: bool,
        speed_kmh: float,
    ) -> Dict:
        pipeline = YouTubeSSLVerificationPipeline(
            videos_dir="Testing videos",
            model_path=model_path,
            gentle_mode=self.gentle,
            cooldown_sec=self.cooldown_sec,
            max_videos_per_cycle=self.max_videos_per_cycle,
            max_verifications_per_video=self.max_verifications_per_video,
            allow_yolo_proxy_on_quota_backoff=self.allow_yolo_proxy_when_quota_backoff,
            yolo_proxy_min_conf=self.yolo_proxy_min_conf,
        )
        pipeline.run_batch_youtube_verification(
            urls=sources,
            speed_kmh=speed_kmh,
            skip_processed=skip_processed,
        )
        return pipeline.verification_report

    def _merge_self_labeled_into_ssl_dataset(self) -> int:
        """Merge learner_agent JSON self-labels into datasets/ssl_v1/images+labels."""
        before = self._count_ssl_samples()

        raw_dir = PROJECT_ROOT / "raw_data" / "self_labeled"
        out_dir = PROJECT_ROOT / "datasets" / "ssl_v1"
        classes = self.scene_class_ids

        if raw_dir.exists():
            try:
                format_ssl_data(str(raw_dir), str(out_dir), classes)
            except Exception:
                pass

        self._sync_ssl_training_manifests()

        after = self._count_ssl_samples()
        return max(0, after - before)

    def _merge_hard_negatives_into_ssl_dataset(self) -> int:
        """Copy hard negatives into the SSL dataset with speed-aware oversampling."""
        hard_neg_dir = PROJECT_ROOT / "raw_data" / "hard_negatives"
        images_dir = PROJECT_ROOT / "datasets" / "ssl_v1" / "images"
        labels_dir = PROJECT_ROOT / "datasets" / "ssl_v1" / "labels"
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)

        if not hard_neg_dir.exists():
            return 0

        candidates = []
        for img_path in hard_neg_dir.glob("*.jpg"):
            try:
                meta_path = img_path.with_suffix(".json")
                meta = {}
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                speed_kmh = float(meta.get("speed_kmh", 0.0) or 0.0)
                bucket = str(meta.get("speed_bucket") or self._speed_bucket_label(speed_kmh)).lower()
                priority = 2 if bucket == "high" or speed_kmh >= 90 else 1 if bucket == "mid" or speed_kmh >= 30 else 0
                candidates.append((priority, speed_kmh, img_path))
            except Exception:
                continue

        copied = 0
        candidates.sort(key=lambda item: (item[0], item[1], item[2].name), reverse=True)
        for priority, speed_kmh, img_path in candidates:
            label_path = img_path.with_suffix(".txt")
            meta_path = img_path.with_suffix(".json")
            boosts = 2 if priority >= 2 else 1
            for boost_idx in range(boosts):
                suffix = f"__boost{boost_idx}" if boost_idx > 0 else ""
                dst_img = images_dir / f"{img_path.stem}{suffix}{img_path.suffix}"
                dst_label = labels_dir / f"{img_path.stem}{suffix}{label_path.suffix}"
                shutil.copy2(img_path, dst_img)
                if label_path.exists():
                    shutil.copy2(label_path, dst_label)
                else:
                    dst_label.write_text("", encoding="utf-8")
                copied += 1

                # Preserve the metadata next to the copied label for later inspection.
                if meta_path.exists():
                    meta_dst = labels_dir / f"{img_path.stem}{suffix}.json"
                    shutil.copy2(meta_path, meta_dst)

        if copied > 0:
            self._sync_ssl_training_manifests()

        return copied

    def _train_once(self, cycle: int, data_yaml: str) -> Tuple[float, float, str]:
        """
        Returns: (mAP50, train_loss, best_model_path)
        Implements auto-resume and persistent checkpoint syncing for Colab.
        """
        # PHASE 1: AUTO-RESUME LOGIC
        backup_dir = PROJECT_ROOT / "weights_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_weight = backup_dir / "last_crucible.pt"
        yolo_weights_dir = PROJECT_ROOT / "runs" / "detect" / "realworld_ssl_goal" / "weights"

        if backup_weight.exists():
            print(f"[AUTO-RESUME] Loading weights from {backup_weight}")
            model = YOLO(str(backup_weight))
            resume_flag = True
        else:
            model = YOLO(self.current_model_path)
            resume_flag = False

        # Some checkpoints in this repo are segmentation variants. The realworld
        # dataset configured here uses detection labels, so force a detect model.
        model_task = getattr(getattr(model, "model", None), "task", "")
        if str(model_task).lower() == "segment":
            detect_seed = str(PROJECT_ROOT / "yolov8n.pt")
            model = YOLO(detect_seed if Path(detect_seed).exists() else "yolov8n.pt")

        # Adaptive schedule: increase effort on later cycles if target not reached.
        adaptive_epochs = self.train_epochs + (1 if cycle >= 3 else 0) + (1 if cycle >= 6 else 0) + (1 if cycle >= 10 else 0)

        # CRITICAL OVERRIDE: Enforce strict RTX 3050 VRAM and Windows stability
        results = model.train(
            data=data_yaml,
            epochs=adaptive_epochs,
            imgsz=416,           # Enforce 416x416 input size
            batch=4,             # Strict batch size for 4GB VRAM
            half=True,           # FP16 precision
            patience=6,
            device='0',          # Force CUDA:0
            save=True,
            verbose=False,
            project="runs/detect",
            name="realworld_ssl_goal",
            exist_ok=True,
            workers=0,           # Single-threaded DataLoader for Windows
            resume=resume_flag,
        )

        metrics = getattr(results, "results_dict", {}) or {}
        map50 = float(metrics.get("metrics/mAP50(B)", metrics.get("metrics/mAP50", 0.0)))
        train_loss = float(metrics.get("train/loss", 0.0))

        # PHASE 2: PERSISTENT CHECKPOINT SYNCING
        last_pt = yolo_weights_dir / "last.pt"
        best_pt = yolo_weights_dir / "best.pt"
        # Always copy after each training cycle
        if last_pt.exists():
            shutil.copy2(last_pt, backup_dir / "last_crucible.pt")
        if best_pt.exists():
            shutil.copy2(best_pt, backup_dir / "best_crucible.pt")

        # Maintain legacy stable/best paths
        best_candidate = best_pt
        stamped = self.models_dir / f"best_realworld_ssl_cycle_{cycle}.pt"
        stable = self.models_dir / "best_realworld_ssl.pt"

        if best_candidate.exists():
            shutil.copy2(best_candidate, stamped)
            shutil.copy2(best_candidate, stable)
            best_path = str(stable)
        else:
            best_path = self.current_model_path

        return map50, train_loss, best_path

    @staticmethod
    def _extract_accuracy_proxy(report: Dict) -> Tuple[float, int, int]:
        summary = report.get("summary", {}) if isinstance(report, dict) else {}
        agreement = float(summary.get("agreement_rate", 0.0))
        verified = int(summary.get("total_verified_by_gemini", 0) or 0)
        detections = int(summary.get("total_yolo_detections", 0) or 0)
        return agreement, verified, detections

    @staticmethod
    def _summarize_false_positives(report: Dict) -> int:
        """Count YOLO positives rejected by Gemini in a verification report."""
        false_positives = 0
        videos = report.get("videos_processed", {}) if isinstance(report, dict) else {}

        for video_result in videos.values():
            for detection in video_result.get("detections", []):
                yolo_conf = float(detection.get("yolo_confidence", 0.0) or 0.0)
                gemini_verification = detection.get("gemini_verification", None)
                if yolo_conf >= 0.30 and gemini_verification is False:
                    false_positives += 1

        return false_positives

    @staticmethod
    def _class_label_from_detection(detection: Dict) -> str:
        raw_name = detection.get("class_name")
        if raw_name:
            return canonicalize_label(str(raw_name))
        return canonicalize_label(str(detection.get("class", "unknown")))

    @staticmethod
    def _normalize_hazard_type(value: Optional[str]) -> str:
        return canonicalize_label(value or "other_road_object")

    def _summarize_per_class_metrics(self, report: Dict) -> Dict[str, Dict[str, float]]:
        """Generate class-wise precision and recall proxies from Gemini-reviewed detections and background checks."""
        class_stats: Dict[str, Dict[str, float]] = {}
        videos = report.get("videos_processed", {}) if isinstance(report, dict) else {}

        def ensure_bucket(label: str) -> Dict[str, float]:
            if label not in class_stats:
                class_stats[label] = {
                    "tp": 0.0,
                    "fp": 0.0,
                    "fn_proxy": 0.0,
                    "precision": 0.0,
                    "recall_proxy": 0.0,
                    "f1_proxy": 0.0,
                }
            return class_stats[label]

        for video_result in videos.values():
            for detection in video_result.get("detections", []):
                pred_label = self._class_label_from_detection(detection)
                bucket = ensure_bucket(pred_label)
                pred_conf = float(detection.get("yolo_confidence", 0.0) or 0.0)
                gemini_type = self._normalize_hazard_type(detection.get("gemini_type"))
                gemini_ok = detection.get("gemini_verification", None) is True

                if gemini_ok and (gemini_type == pred_label or gemini_type == "unknown"):
                    bucket["tp"] += 1.0
                elif pred_conf >= 0.35:
                    bucket["fp"] += 1.0

            for background_check in video_result.get("background_checks", []):
                if not background_check.get("confirmed", False):
                    continue
                label = self._normalize_hazard_type(background_check.get("hazard_type"))
                ensure_bucket(label)["fn_proxy"] += 1.0

        for label in self.scene_classes:
            ensure_bucket(label)

        for bucket in class_stats.values():
            tp = bucket["tp"]
            fp = bucket["fp"]
            fn_proxy = bucket["fn_proxy"]
            bucket["precision"] = round((tp / (tp + fp)) if (tp + fp) > 0 else 0.0, 4)
            bucket["recall_proxy"] = round((tp / (tp + fn_proxy)) if (tp + fn_proxy) > 0 else 0.0, 4)
            denom = bucket["precision"] + bucket["recall_proxy"]
            bucket["f1_proxy"] = round((2 * bucket["precision"] * bucket["recall_proxy"] / denom) if denom > 0 else 0.0, 4)

        return class_stats

    def _export_best_checkpoint(self, source_path: Optional[str] = None) -> Optional[str]:
        """Export the best checkpoint to a stable deployable filename."""
        best = self.history.get("best", {}) if isinstance(self.history, dict) else {}
        candidate = source_path or best.get("model_path") or self.current_model_path
        if not candidate:
            return None

        candidate_path = Path(candidate)
        if not candidate_path.exists():
            return None

        deployable_path = self.models_dir / "best_deployable.pt"
        # Only copy if source and destination are not the same file
        try:
            if candidate_path.resolve() != deployable_path.resolve():
                shutil.copy2(candidate_path, deployable_path)
        except Exception as e:
            print(f"[WARN] Could not copy model to deployable: {e}")
        return str(deployable_path)

    def _write_cycle_summary(
        self,
        cycle: int,
        validation_metrics: Dict[str, float],
        per_class_metrics: Dict[str, Dict[str, float]],
        deployable_path: Optional[str],
        status: str,
    ) -> Optional[str]:
        """Write a compact JSON summary for fast run-to-run comparison."""
        summary_path = self.logs_dir / f"cycle_summary_{cycle:03d}.json"
        payload = {
            "cycle": cycle,
            "timestamp": datetime.now().isoformat(),
            "model_path": self.current_model_path,
            "deployable_path": deployable_path,
            "status": status,
            "validation": validation_metrics,
            "per_class_metrics": per_class_metrics,
        }
        summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(summary_path)

    def _score_validation_report(self, report: Dict) -> Dict[str, float]:
        """Create a composite score that rewards agreement and penalizes false positives."""
        agreement_rate, verified, detections = self._extract_accuracy_proxy(report)
        false_positives = self._summarize_false_positives(report)

        fp_rate = (false_positives / detections * 100.0) if detections > 0 else 0.0
        verification_bonus = min(10.0, verified * 0.15)
        score = agreement_rate + verification_bonus - (fp_rate * 0.75)

        return {
            "agreement_rate": agreement_rate,
            "verified": float(verified),
            "detections": float(detections),
            "false_positives": float(false_positives),
            "false_positive_rate": fp_rate,
            "score": score,
        }

    def run(self):
        self._wandb_init()
        self._ensure_val_sources()

        train_sources = self._read_sources(self.train_sources_file)
        val_sources = self._read_sources(self.val_sources_file)

        # De-duplicate while preserving order.
        train_sources = list(dict.fromkeys(train_sources))
        val_sources = list(dict.fromkeys(val_sources))

        if not train_sources:
            raise RuntimeError(
                f"No training dashcam sources found in {self.train_sources_file}. "
                "Add open-source URLs/files and re-run."
            )
        if not val_sources:
            raise RuntimeError(
                f"No validation dashcam sources found in {self.val_sources_file}."
            )

        self._validate_source_partitions(train_sources, val_sources)

        print("=" * 80)
        print("REAL-WORLD SSL GOAL LOOP STARTED")
        print(f"Target Accuracy: {self.target_accuracy:.1f}% agreement")
        print(f"Max Cycles: {self.max_cycles}")
        print(f"Train Sources: {len(train_sources)} | Val Sources: {len(val_sources)}")
        print(f"Initial Model: {self.current_model_path}")
        data_yaml = self._sync_ssl_training_manifests() or self._resolve_training_data_yaml()
        print(f"Training Dataset YAML: {data_yaml}")
        print("=" * 80)

        if self.auto_select_best_weight:
            self.current_model_path = self._select_best_weight(val_sources)

        for cycle in range(1, self.max_cycles + 1):
            started_at = datetime.now().isoformat()
            print(f"\n[Cycle {cycle}/{self.max_cycles}] -------------------------------")

            ssl_before = self._count_ssl_samples()

            # 0) Optional research refresh
            research_digest = self._run_research_refresh(cycle)
            if research_digest:
                print(f"Research digest saved: {research_digest}")

            # 1) Gather SSL labels from train dashcam sources
            train_report = self._run_ssl_verification(
                sources=train_sources,
                model_path=self.current_model_path,
                skip_processed=False,
                speed_kmh=self.speed_kmh,
            )

            # 2) Merge any self-labeled data
            merged = self._merge_self_labeled_into_ssl_dataset()
            hard_neg_merged = self._merge_hard_negatives_into_ssl_dataset()
            ssl_after = self._count_ssl_samples()
            data_yaml = self._sync_ssl_training_manifests() or self._resolve_training_data_yaml()
            print(
                f"SSL dataset growth this cycle: +{(ssl_after - ssl_before)} labels "
                f"(formatter merge +{merged}, hard negatives +{hard_neg_merged})"
            )

            # 3) Retrain model
            map50, train_loss, new_model = self._train_once(cycle, data_yaml=data_yaml)
            self.current_model_path = new_model
            print(f"Training metrics: mAP50={map50:.4f}, loss={train_loss:.4f}")
            self._wandb_log({
                "cycle": cycle,
                "train/map50": map50,
                "train/loss": train_loss,
                "ssl/samples_before": ssl_before,
                "ssl/samples_after": ssl_after,
                "ssl/hard_negatives_merged": hard_neg_merged,
            })

            # 4) Evaluate on validation sources across speed buckets.
            bucket_reports = self._evaluate_speed_buckets(val_sources, self.current_model_path)
            primary_bucket_label = f"{int(max(self.validation_speed_buckets))}kmh"
            primary_bucket_report = bucket_reports[primary_bucket_label]["report"]
            primary_bucket_metrics = bucket_reports[primary_bucket_label]["metrics"]
            bucket_summary = {
                label: {
                    "speed_kmh": bundle["speed_kmh"],
                    **bundle["metrics"],
                }
                for label, bundle in bucket_reports.items()
            }
            validation_metrics = primary_bucket_metrics
            val_agreement = validation_metrics["agreement_rate"]
            val_verified = int(validation_metrics["verified"])
            val_detections = int(validation_metrics["detections"])
            false_positives = int(validation_metrics["false_positives"])
            false_positive_rate = validation_metrics["false_positive_rate"]
            validation_score = self._weighted_bucket_score(bucket_reports)
            per_class_metrics = self._summarize_per_class_metrics(primary_bucket_report)
            self._wandb_log({
                "cycle": cycle,
                "val/agreement_rate": val_agreement,
                "val/verified": val_verified,
                "val/detections": val_detections,
                "val/false_positives": false_positives,
                "val/false_positive_rate": false_positive_rate,
                "val/composite_score": validation_score,
            })
            for bucket_label, metrics in bucket_summary.items():
                self._wandb_log({
                    f"val_bucket/{bucket_label}/speed_kmh": metrics["speed_kmh"],
                    f"val_bucket/{bucket_label}/agreement_rate": metrics["agreement_rate"],
                    f"val_bucket/{bucket_label}/verified": metrics["verified"],
                    f"val_bucket/{bucket_label}/detections": metrics["detections"],
                    f"val_bucket/{bucket_label}/false_positive_rate": metrics["false_positive_rate"],
                    f"val_bucket/{bucket_label}/score": metrics["score"],
                })
            for class_name, metrics in per_class_metrics.items():
                self._wandb_log({
                    f"val/class/{class_name}/precision": metrics["precision"],
                    f"val/class/{class_name}/recall_proxy": metrics["recall_proxy"],
                    f"val/class/{class_name}/f1_proxy": metrics["f1_proxy"],
                })

            reached = val_agreement >= self.target_accuracy and val_verified >= self.min_val_verified

            ended_at = datetime.now().isoformat()
            cycle_result = CycleResult(
                cycle=cycle,
                started_at=started_at,
                ended_at=ended_at,
                model_path=self.current_model_path,
                train_sources_count=len(train_sources),
                val_sources_count=len(val_sources),
                ssl_samples_before=ssl_before,
                ssl_samples_after=ssl_after,
                val_agreement_rate=val_agreement,
                val_verified=val_verified,
                val_detections=val_detections,
                train_map50=map50,
                train_loss=train_loss,
                reached_target=reached,
                notes="composite_score uses agreement, verification bonus, and false-positive penalty; speed buckets tracked separately",
            )

            self.history["cycles"].append(asdict(cycle_result))

            best = self.history.get("best", {})
            best_score = float(best.get("validation_score", float("-inf")))
            if validation_score > best_score:
                self.history["best"] = {
                    "cycle": cycle,
                    "val_agreement_rate": val_agreement,
                    "validation_score": validation_score,
                    "false_positive_rate": false_positive_rate,
                    "model_path": self.current_model_path,
                    "speed_bucket_summary": bucket_summary,
                }
                deployable = self._export_best_checkpoint(self.current_model_path)
                if deployable:
                    self._wandb_log({"best/deployable_path": deployable})
            else:
                deployable = self._export_best_checkpoint(best.get("model_path") or self.current_model_path)

            # Roll back if the new checkpoint regresses against the best-known score.
            if best_score != float("-inf") and validation_score < best_score - self.rollback_score_margin:
                restored = self._rollback_to_best_checkpoint()
                if restored:
                    print(
                        f"↩️ Regressed on validation score ({validation_score:.2f} < {best_score:.2f}); "
                        f"rolling back to {restored}"
                    )
                    self.current_model_path = restored

            if reached:
                self.history["status"] = "target_reached"
                self.history["completed_at"] = datetime.now().isoformat()
                self._save_history()
                print("\n✅ TARGET REACHED")
                print(
                    f"Validation agreement={val_agreement:.2f}% "
                    f"with verified={val_verified} (threshold={self.min_val_verified})"
                )
                print(f"Best model saved at: {self.current_model_path}")
                if self.wandb_run is not None:
                    try:
                        self.wandb_run.finish()
                    except Exception:
                        pass
                return

            self._save_history()
            print(
                f"Cycle result: val_agreement={val_agreement:.2f}% | "
                f"verified={val_verified} | detections={val_detections} | "
                f"fp={false_positives} | score={validation_score:.2f}"
            )

            if per_class_metrics:
                summary_line = ", ".join(
                    f"{name}:P={metrics['precision']:.2f}/R={metrics['recall_proxy']:.2f}"
                    for name, metrics in sorted(per_class_metrics.items())
                )
                print(f"Per-class metrics: {summary_line}")

            cycle_summary_path = self._write_cycle_summary(
                cycle=cycle,
                validation_metrics=validation_metrics,
                per_class_metrics=per_class_metrics,
                deployable_path=deployable,
                status="target_reached" if reached else "running",
            )
            if cycle_summary_path:
                print(f"🧾 Cycle summary saved: {cycle_summary_path}")
            bucket_report_path = self.logs_dir / f"cycle_speed_buckets_{cycle:03d}.json"
            bucket_report_path.write_text(json.dumps(bucket_summary, indent=2), encoding="utf-8")
            print(f"🧾 Speed bucket summary saved: {bucket_report_path}")

            # Keep long runs stable without reducing cooling cycles.
            if self.device_meta.get("cuda_available", False) and torch is not None:
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
            gc.collect()

            # If no verified samples, pause briefly to avoid rapid fail loops.
            if val_verified == 0:
                print("No Gemini-verified samples in validation; sleeping 20s before next cycle.")
                time.sleep(20)

        self.history["status"] = "max_cycles_reached"
        self.history["completed_at"] = datetime.now().isoformat()
        final_export = self._export_best_checkpoint(self.current_model_path)
        if final_export:
            print(f"📦 Deployable checkpoint exported: {final_export}")
        self._save_history()
        best = self.history.get("best", {})
        print("\n⚠️ MAX CYCLES REACHED BEFORE TARGET")
        print(
            f"Best validation agreement: {best.get('val_agreement_rate', 0.0):.2f}% "
            f"at cycle {best.get('cycle')}"
        )
        print(f"Best model path: {best.get('model_path')}" )
        if self.wandb_run is not None:
            try:
                self.wandb_run.finish()
            except Exception:
                pass

    def _rollback_to_best_checkpoint(self) -> Optional[str]:
        """Restore the best checkpoint discovered so far."""
        best = self.history.get("best", {}) if isinstance(self.history, dict) else {}
        best_model = best.get("model_path")
        if not best_model or not Path(best_model).exists():
            return None

        current = Path(self.current_model_path)
        try:
            shutil.copy2(best_model, current)
            self.current_model_path = str(current)
            return self.current_model_path
        except Exception:
            return best_model


def main():
    _acquire_single_instance_lock()

    parser = argparse.ArgumentParser(description="Run real-world SSL training loop until target accuracy")
    parser.add_argument("--target", type=float, default=95.0, help="Target real-world agreement accuracy (%%)")
    parser.add_argument("--max-cycles", type=int, default=20, help="Max loop iterations")
    parser.add_argument("--min-val-verified", type=int, default=30, help="Minimum verified detections required to accept target")
    parser.add_argument("--train-epochs", type=int, default=2, help="Training epochs per cycle")
    parser.add_argument("--train-sources", default="video_sources.txt", help="Training sources file")
    parser.add_argument("--val-sources", default="video_sources_val.txt", help="Validation sources file")
    parser.add_argument("--model", default="yolov8_pothole.pt", help="Seed model path")
    parser.add_argument("--speed-kmh", type=float, default=120.0, help="Operational speed profile")
    parser.add_argument("--max-videos-per-cycle", type=int, default=2, help="Video cap per cycle")
    parser.add_argument("--max-verifications-per-video", type=int, default=20, help="Gemini checks cap per video")
    parser.add_argument("--cooldown-sec", type=float, default=1.0, help="Cooldown between videos")
    parser.add_argument("--use-consortium", action="store_true", default=True, help="Use GODMOD3 Consortium hive-mind verifying")
    parser.add_argument("--gpu-only", dest="gpu_only", action="store_true", default=True, help="Fail fast unless CUDA is available")
    parser.add_argument("--allow-cpu", action="store_true", help="Temporarily allow CPU fallback (requires --override-password)")
    parser.add_argument("--override-password", default="", help="Password required for --allow-cpu")
    parser.add_argument("--gentle", action="store_true", help="Lower processing load")
    parser.add_argument("--disable-godmod3-research", action="store_true", help="Skip per-cycle G0DM0D3 hint query")
    parser.add_argument(
        "--godmod3-research-mode",
        choices=["classic", "ultraplinian"],
        default="classic",
        help="G0DM0D3 research mode used by per-cycle hint query",
    )
    parser.add_argument("--disable-wandb", action="store_true", help="Disable Weights & Biases logging")
    parser.add_argument("--disable-auto-weight-select", action="store_true", help="Disable automatic best-weight selection")
    parser.add_argument("--hf-discovery-limit", type=int, default=8, help="HF model discovery limit per query")
    parser.add_argument("--hf-download-limit", type=int, default=4, help="HF candidate download cap")
    parser.add_argument("--benchmark-videos-cap", type=int, default=1, help="Videos per candidate during weight benchmark")
    parser.add_argument(
        "--disable-yolo-proxy-backoff",
        action="store_true",
        help="Disable YOLO proxy verification when Gemini quota backoff is active",
    )
    parser.add_argument(
        "--yolo-proxy-min-conf",
        type=float,
        default=0.60,
        help="Minimum YOLO confidence for quota-backoff proxy verification",
    )
    parser.add_argument(
        "--real-dataset-yaml",
        default="",
        help=(
            "Optional real labeled dataset YAML (e.g. raw_data/pothole_dataset/data.yaml). "
            "If omitted, loop auto-detects common local real dataset configs."
        ),
    )

    args = parser.parse_args()
    effective_gpu_only = bool(args.gpu_only)
    if args.allow_cpu:
        password = (args.override_password or "").strip()
        if len(password) < 16:
            raise SystemExit("Invalid override password. CPU override denied.")
        expected = os.environ.get("GPU_OVERRIDE_PASSWORD", "").strip()
        if expected and not hmac.compare_digest(password, expected):
            raise SystemExit("Invalid override password. CPU override denied.")
        os.environ["GPU_OVERRIDE_ENABLE"] = "1"
        os.environ["GPU_OVERRIDE_PASSWORD"] = password
        effective_gpu_only = False

    loop = RealWorldSSLGoalLoop(
        target_accuracy=args.target,
        max_cycles=args.max_cycles,
        min_val_verified=args.min_val_verified,
        train_epochs=args.train_epochs,
        train_sources_file=args.train_sources,
        val_sources_file=args.val_sources,
        model_seed=args.model,
        speed_kmh=args.speed_kmh,
        max_videos_per_cycle=args.max_videos_per_cycle,
        max_verifications_per_video=args.max_verifications_per_video,
        cooldown_sec=args.cooldown_sec,
        gentle=args.gentle,
        enable_godmod3_research=not args.disable_godmod3_research,
        godmod3_research_mode=args.godmod3_research_mode,
        use_wandb=not args.disable_wandb,
        auto_select_best_weight=not args.disable_auto_weight_select,
        hf_discovery_limit=args.hf_discovery_limit,
        hf_download_limit=args.hf_download_limit,
        benchmark_videos_cap=args.benchmark_videos_cap,
        real_dataset_yaml=args.real_dataset_yaml,
        gpu_only=effective_gpu_only,
        allow_yolo_proxy_when_quota_backoff=not args.disable_yolo_proxy_backoff,
        yolo_proxy_min_conf=args.yolo_proxy_min_conf,
        use_consortium=args.use_consortium,
    )
    # 🛡️ SELF-CORRECTION: Zero-Cost Hardening
    # If consortium is enabled but no credits, it will auto-fallback to free tier or local
    logger.info("🛡️ [ZERO_COST_ACTIVE] Priority: Gemini Free > Local Ollama > Consortium Free")
    
    loop.run()


if __name__ == "__main__":
    main()
