#!/usr/bin/env python3
"""
YouTube Video Download + YOLO Testing + Self-Supervised Verification Pipeline

This script orchestrates the complete testing workflow:
1. Download YouTube videos
2. Run YOLO inference to detect hazards
3. Verify detections with Gemini (Self-Supervised Learning)
4. Compare YOLO confidence vs Gemini verification
5. Generate comprehensive audit report

Usage:
    python youtube_ssl_verification.py --test-mode
    python youtube_ssl_verification.py --file video_sources.txt
    python youtube_ssl_verification.py --urls https://www.youtube.com/watch?v=...
"""

import os
import sys
import subprocess
import json
import cv2
import logging
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import time
import hashlib

try:
    import torch
except Exception:
    torch = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Project imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ultralytics import YOLO
from agents.learner_agent import SelfSupervisedLearner
from core.model_registry import resolve_yolo_general_pt, resolve_yolo_pothole_pt
from scripts.utils.gpu_runtime import resolve_ultralytics_device, log_runtime

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | [SSL_VERIFY] %(message)s",
    handlers=[
        logging.FileHandler(
            f"logs/ssl_verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class YouTubeSSLVerificationPipeline:
    """Complete pipeline for YouTube -> YOLO -> SSL Verification"""
    
    def __init__(
        self,
        videos_dir="Testing videos",
        model_path=None,
        gentle_mode: bool = False,
        cooldown_sec: float = 1.0,
        max_videos_per_cycle: int = 0,
        max_verifications_per_video: int = 12,
        gpu_only: bool = True,
        allow_yolo_proxy_on_quota_backoff: bool = True,
        yolo_proxy_min_conf: float = 0.60,
        use_consortium: bool = True,
    ):
        self.videos_dir = videos_dir
        self.model_path = model_path or str(resolve_yolo_pothole_pt())
        self.results_dir = os.path.join(videos_dir, "ssl_verification_results")
        self.verification_report_path = os.path.join(self.results_dir, "verification_report.json")
        self.state_path = os.path.join(self.results_dir, "loop_state.json")
        self.gentle_mode = gentle_mode
        self.cooldown_sec = max(0.0, cooldown_sec)
        self.max_videos_per_cycle = max(0, max_videos_per_cycle)
        self.max_verifications_per_video = max(1, max_verifications_per_video)
        self.gpu_only = bool(gpu_only)
        self.allow_yolo_proxy_on_quota_backoff = bool(allow_yolo_proxy_on_quota_backoff)
        self.yolo_proxy_min_conf = float(max(0.0, min(1.0, yolo_proxy_min_conf)))
        self.temporal_context_frames = max(3, int(os.getenv("SSL_TEMPORAL_CONTEXT_FRAMES", "3")))
        self.downloader_cmd = self._resolve_downloader_cmd()
        self.ffmpeg_path = None
        self.ffmpeg_available = self._check_ffmpeg()
        self.ultralytics_device, self.runtime_device, self.device_meta = resolve_ultralytics_device(
            torch,
            require_gpu=self.gpu_only,
        )
        log_runtime(logger, "YouTubeSSLVerification", self.ultralytics_device, self.device_meta)
        
        # Create directories
        for directory in [videos_dir, self.results_dir]:
            os.makedirs(directory, exist_ok=True)
        
        # Initialize YOLO model
        try:
            self.model = YOLO(self.model_path)
            if self.device_meta.get("cuda_available", False):
                try:
                    self.model.to(self.runtime_device)
                    logger.info("✅ YOLO Model moved to GPU: %s", self.runtime_device)
                except Exception:
                    pass
            logger.info(f"✅ YOLO Model loaded: {self.model_path}")
        except Exception as e:
            logger.warning(f"⚠️ Model loading failed: {e}, using fallback")
            self.model = YOLO(str(resolve_yolo_general_pt()))
        
        # Initialize SSL Learner with Gemini (Optional Multi-Model Consortium)
        if use_consortium:
            os.environ["CONSORTIUM_ENABLED"] = "1"
        else:
            os.environ["CONSORTIUM_ENABLED"] = "0"
            
        self.learner = SelfSupervisedLearner()
        logger.info("✅ Self-Supervised Learner initialized (Consortium: %s)", use_consortium)
        
        # Initialize report
        self.verification_report = {
            "session_id": datetime.now().isoformat(),
            "videos_processed": {},
            "summary": {
                "total_videos": 0,
                "total_frames_analyzed": 0,
                "total_yolo_detections": 0,
                "total_verified_by_gemini": 0,
                "avg_yolo_confidence": 0,
                "avg_gemini_confidence": 0,
                "total_hard_negatives": 0,
                "agreement_rate": 0  # % of YOLO detections confirmed by Gemini
            }
        }

        self.loop_state = self._load_loop_state()

    def _apply_yolo_proxy_verification(self, detection: Dict[str, Any]) -> bool:
        """Use a conservative YOLO-only proxy when Gemini quota backoff is active."""
        yolo_conf = float(detection.get("yolo_confidence", 0.0) or 0.0)
        accepted = yolo_conf >= self.yolo_proxy_min_conf

        detection["gemini_confidence"] = yolo_conf if accepted else 0.0
        detection["gemini_verification"] = bool(accepted)
        detection["gemini_type"] = detection.get("class_name") if accepted else "unknown"
        detection["agreement"] = bool(accepted)
        detection["verification_source"] = "yolo_proxy_quota_backoff"

        return bool(accepted)

    def _check_ffmpeg(self) -> bool:
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            self.ffmpeg_path = ffmpeg_bin
            logger.info(f"✅ ffmpeg ready: {ffmpeg_bin}")
            return True

        try:
            import imageio_ffmpeg
            bundled = imageio_ffmpeg.get_ffmpeg_exe()
            if bundled and os.path.exists(bundled):
                self.ffmpeg_path = bundled
                logger.info(f"✅ ffmpeg ready (bundled): {bundled}")
                return True
        except Exception:
            pass

        logger.warning(
            "⚠️ ffmpeg not found. Downloads may merge less reliably and frame extraction may be slower."
        )
        return False

    def _install_yt_dlp(self) -> bool:
        """Try to install yt-dlp in the current Python environment."""
        try:
            logger.info("📦 yt-dlp not found. Attempting auto-install via pip...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "yt-dlp"],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode == 0:
                logger.info("✅ Auto-installed yt-dlp")
                return True
            logger.error(f"❌ yt-dlp install failed: {result.stderr.strip()}")
            return False
        except Exception as e:
            logger.error(f"❌ yt-dlp install error: {e}")
            return False

    def _resolve_downloader_cmd(self) -> Optional[List[str]]:
        """Resolve a working downloader command.

        Order:
        1) yt-dlp executable in PATH
        2) python -m yt_dlp module
        3) attempt pip install then python -m yt_dlp
        """
        yt_dlp_bin = shutil.which("yt-dlp")
        if yt_dlp_bin:
            logger.info(f"✅ Downloader ready: {yt_dlp_bin}")
            return [yt_dlp_bin]

        # Check module availability without importing.
        probe = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode == 0:
            logger.info("✅ Downloader ready: python -m yt_dlp")
            return [sys.executable, "-m", "yt_dlp"]

        if self._install_yt_dlp():
            probe_after = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe_after.returncode == 0:
                logger.info("✅ Downloader ready after install: python -m yt_dlp")
                return [sys.executable, "-m", "yt_dlp"]

        logger.error("❌ No working downloader found (yt-dlp unavailable)")
        return None

    def _latest_cached_video(self) -> Optional[str]:
        exts = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
        candidates = [
            p for p in Path(self.videos_dir).glob("*")
            if p.is_file() and p.suffix.lower() in exts
        ]
        if not candidates:
            return None
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        return str(newest)

    def _is_youtube_url(self, url: str) -> bool:
        u = url.lower()
        return "youtube.com" in u or "youtu.be" in u or u.startswith("ytsearch")

    def _download_direct_video(self, url: str) -> Optional[str]:
        """Download direct HTTP(S) video links (non-YouTube)."""
        try:
            parsed = urllib.parse.urlparse(url)
            suffix = Path(parsed.path).suffix.lower()
            if suffix not in {".mp4", ".webm", ".mkv", ".avi", ".mov"}:
                suffix = ".mp4"

            file_name = f"http_{int(time.time())}{suffix}"
            dst = Path(self.videos_dir) / file_name

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
            )

            with urllib.request.urlopen(req, timeout=120) as response, open(dst, "wb") as f:
                shutil.copyfileobj(response, f)

            if dst.exists() and dst.stat().st_size > 0:
                size_mb = dst.stat().st_size / (1024 * 1024)
                logger.info(f"✅ Direct video downloaded: {dst.name} ({size_mb:.2f} MB)")
                return str(dst)
        except Exception as e:
            logger.error(f"❌ Direct HTTP download failed: {e}")

        return None

    def _resolve_source_video(self, source: str) -> Optional[str]:
        """Resolve input source into a local video path.

        Supported input types:
        - YouTube URLs
        - Direct HTTP(S) video links
        - Existing local file paths
        """
        source = source.strip()
        if not source:
            return None

        # Local file path source.
        if os.path.exists(source):
            return source

        # URL source.
        if source.lower().startswith("ytsearch"):
            return self.download_youtube_video(source)

        if source.lower().startswith(("http://", "https://")):
            if self._is_youtube_url(source):
                return self.download_youtube_video(source)
            return self._download_direct_video(source)

        return None

    def _load_loop_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data.setdefault("processed_url_hashes", [])
                        return data
            except Exception:
                pass
        return {
            "processed_url_hashes": [],
            "last_cycle_at": None,
            "cycles_completed": 0
        }

    def _save_loop_state(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.loop_state, f, indent=2)

    def _mark_activity(self, phase: str):
        self.loop_state["current_phase"] = phase
        self.loop_state["last_activity_at"] = datetime.now().isoformat()
        self._save_loop_state()

    def _url_hash(self, url: str) -> str:
        return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()

    def _speed_profile(self, speed_kmh: float) -> Dict[str, Any]:
        # Higher speeds require denser temporal sampling to reduce miss risk.
        # Gentle mode intentionally lowers processing load to avoid stressing hardware.
        # For large-batch validation runs, prioritize throughput over dense sampling.
        if self.max_videos_per_cycle >= 100:
            if speed_kmh >= 100:
                return {"process_fps": 2.0, "yolo_min_conf": 0.40}
            return {"process_fps": 1.5, "yolo_min_conf": 0.42}

        if self.gentle_mode:
            if speed_kmh >= 150:
                return {"process_fps": 3.0, "yolo_min_conf": 0.35}
            if speed_kmh >= 100:
                return {"process_fps": 2.0, "yolo_min_conf": 0.38}
            return {"process_fps": 1.0, "yolo_min_conf": 0.40}

        if speed_kmh >= 150:
            return {"process_fps": 8.0, "yolo_min_conf": 0.25}
        if speed_kmh >= 100:
            return {"process_fps": 5.0, "yolo_min_conf": 0.28}
        return {"process_fps": 2.0, "yolo_min_conf": 0.30}

    @staticmethod
    def _speed_bucket_label(speed_kmh: float) -> str:
        if speed_kmh < 30:
            return "low"
        if speed_kmh < 90:
            return "mid"
        return "high"

    def _temporal_context_span(self, speed_kmh: float) -> int:
        if speed_kmh >= 120:
            return 3
        if speed_kmh >= 60:
            return 2
        return 1

    def _build_temporal_context_frame(self, video_path: str, frame_idx: int, speed_kmh: float) -> Optional[str]:
        """Build a small contact sheet around the detection frame to provide temporal context."""
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None

            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if frame_count <= 0:
                cap.release()
                return None

            span = self._temporal_context_span(speed_kmh)
            offsets = [-span, 0, span]
            frames = []
            for offset in offsets:
                target_idx = max(0, min(frame_count - 1, frame_idx + offset))
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                frame = cv2.resize(frame, (384, 216), interpolation=cv2.INTER_AREA)
                frames.append(frame)

            cap.release()

            if not frames:
                return None
            if len(frames) == 1:
                single_path = os.path.join(self.results_dir, f"temporal_{int(time.time())}_{frame_idx}.jpg")
                cv2.imwrite(single_path, frames[0])
                return single_path

            contact_sheet = cv2.hconcat(frames)
            sheet_path = os.path.join(self.results_dir, f"temporal_{int(time.time())}_{frame_idx}.jpg")
            cv2.imwrite(sheet_path, contact_sheet)
            return sheet_path
        except Exception as e:
            logger.warning(f"⚠️ Temporal context frame creation failed: {e}")
            return None

    @staticmethod
    def _frame_focus_score(frame) -> float:
        """Return a simple blur/focus score; higher is sharper."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _is_frame_usable(self, frame, speed_kmh: float) -> bool:
        """Skip heavily blurred frames to improve precision and speed."""
        focus = self._frame_focus_score(frame)
        if self.gentle_mode and speed_kmh >= 100:
            return focus >= 55.0
        if speed_kmh >= 150:
            return focus >= 45.0
        return focus >= 35.0

    def download_youtube_video(self, url: str) -> str:
        """Download YouTube video to Testing videos folder"""
        logger.info(f"📥 Downloading: {url}")

        if not self.downloader_cmd:
            logger.error("❌ Download skipped: yt-dlp unavailable")
            return None
        
        try:
            video_id = ""
            try:
                video_id = subprocess.check_output([*self.downloader_cmd, "--get-id", url], text=True).strip()
            except Exception:
                video_id = ""

            if video_id:
                existing_files = [
                    p for p in Path(self.videos_dir).glob(f"{video_id}*")
                    if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".avi", ".mov"}
                ]
                if existing_files:
                    cached = max(existing_files, key=lambda p: p.stat().st_mtime)
                    logger.info(f"✅ Reusing cached video: {cached.name}")
                    return str(cached)

            cmd = [
                *self.downloader_cmd,
                "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "--extractor-args", "youtube:player_client=android",
                "--merge-output-format", "mp4",
                "--restrict-filenames",
                "-o", f"{self.videos_dir}/%(id)s_%(title)s.%(ext)s",
                url
            ]
            if self.ffmpeg_path:
                cmd.extend(["--ffmpeg-location", str(Path(self.ffmpeg_path).parent)])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.error(f"❌ Download failed: {result.stderr}")
                return None
            
            import glob
            files = glob.glob(os.path.join(self.videos_dir, f"{video_id}*")) if video_id else []
            if not files:
                # Fallback for ytsearch/direct downloads where id probing may differ.
                exts = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
                candidates = [
                    p for p in Path(self.videos_dir).glob("*")
                    if p.is_file() and p.suffix.lower() in exts
                ]
                if candidates:
                    newest = max(candidates, key=lambda p: p.stat().st_mtime)
                    files = [str(newest)]

            if files:
                video_path = files[0]
                video_size_mb = os.path.getsize(video_path) / (1024 * 1024)
                logger.info(f"✅ Downloaded: {os.path.basename(video_path)} ({video_size_mb:.2f} MB)")
                return video_path
        
        except Exception as e:
            logger.error(f"❌ Download error: {e}")
        
        return None

    def extract_frame(self, video_path: str, frame_idx: int) -> tuple[bool, str]:
        """Extract a single frame from video"""
        try:
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            cap.release()
            
            if ret:
                frame_path = os.path.join(self.results_dir, f"frame_{int(time.time())}_{frame_idx}.jpg")
                cv2.imwrite(frame_path, frame)
                return True, frame_path
            return False, ""
        except Exception as e:
            logger.error(f"❌ Frame extraction error: {e}")
            return False, ""

    def analyze_yolo_detections(self, video_path: str, speed_kmh: float = 60.0) -> List[Dict[str, Any]]:
        """Run YOLO inference with speed-aware frame sampling."""
        logger.info(f"🧠 Running YOLO inference: {os.path.basename(video_path)}")
        
        detections = []
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if fps <= 0:
                fps = 25.0
            
            frame_idx = 0
            profile = self._speed_profile(speed_kmh)
            process_fps = profile["process_fps"]
            yolo_min_conf = profile["yolo_min_conf"]
            sample_rate = max(1, int(round(fps / process_fps)))
            scan_started = time.time()
            heartbeat_every_frames = max(sample_rate * 250, int(frame_count * 0.05), 500)
            logger.info(
                f"   ⚙️ Speed profile: {speed_kmh} km/h | sample every {sample_rate} frame(s) | min_conf={yolo_min_conf}"
            )
            logger.info(
                f"   ▶️ Inference scan started: total_frames={frame_count} | heartbeat_every={heartbeat_every_frames}"
            )
            
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx > 0 and frame_idx % heartbeat_every_frames == 0:
                    elapsed = max(1e-6, time.time() - scan_started)
                    frames_per_sec = frame_idx / elapsed
                    logger.info(
                        f"   ⏱️ Inference heartbeat: frame={frame_idx}/{frame_count} | "
                        f"detections={len(detections)} | scan_fps={frames_per_sec:.2f}"
                    )
                
                if frame_idx % sample_rate == 0:
                    if not self._is_frame_usable(frame, speed_kmh):
                        frame_idx += 1
                        continue

                    try:
                        results = self.model.predict(frame, verbose=False, device=self.ultralytics_device)[0]
                        
                        for box in results.boxes:
                            confidence = float(box.conf[0])
                            
                            # Only keep moderate to high confidence detections for verification
                            if confidence >= yolo_min_conf:
                                detection = {
                                    "frame_idx": frame_idx,
                                    "timestamp": frame_idx / fps,
                                    "class": int(box.cls[0]),
                                    "class_name": self.model.names.get(int(box.cls[0]), "unknown"),
                                    "yolo_confidence": confidence,
                                    "bbox": box.xyxy[0].tolist(),
                                    "gemini_verification": None,
                                    "gemini_confidence": None,
                                    "agreement": False
                                }
                                detections.append(detection)
                    
                    except Exception as e:
                        logger.warning(f"⚠️ Frame {frame_idx} processing error: {e}")
                
                frame_idx += 1
            
            cap.release()
            elapsed_total = max(1e-6, time.time() - scan_started)
            logger.info(
                f"   ✅ Inference scan completed: processed_frames={frame_idx} | "
                f"elapsed={elapsed_total:.1f}s | avg_scan_fps={frame_idx/elapsed_total:.2f}"
            )
            logger.info(f"✅ YOLO found {len(detections)} candidate detections (confidence >= {yolo_min_conf})")
            return detections
        
        except Exception as e:
            logger.error(f"❌ YOLO analysis failed: {e}")
            return []

    def verify_detection_with_gemini(self, video_path: str, detection: Dict[str, Any], speed_kmh: float = 60.0) -> bool:
        """Send detection to Gemini for verification"""
        try:
            context_frame_path = self._build_temporal_context_frame(video_path, detection["frame_idx"], speed_kmh)
            frame_path = context_frame_path

            if not frame_path:
                # Fallback to the detection frame if temporal context could not be built.
                success, fallback_frame_path = self.extract_frame(video_path, detection["frame_idx"])
                if not success:
                    logger.warning(f"⚠️ Could not extract frame {detection['frame_idx']}")
                    return False
                frame_path = fallback_frame_path

            if not frame_path:
                return False
            
            # Prepare IMU metadata (simulated from detection confidence)
            imu_metadata = {
                "accel": {"z": detection["yolo_confidence"] * 2.5},  # Simulate impact based on confidence
                "timestamp": int(time.time()),
                "source": "yolo_detection",
                "speed_kmh": float(speed_kmh),
                "speed_bucket": self._speed_bucket_label(speed_kmh),
                "temporal_context_frames": self.temporal_context_frames,
            }
            
            # Get Gemini verification
            logger.info(f"   🔬 Verifying with Gemini: {detection['class_name']} (YOLO conf: {detection['yolo_confidence']:.2f})")
            verification = self.learner.audit_jerk_event(frame_path, imu_metadata)
            
            if verification:
                detection["gemini_verification"] = verification.get("hazard_confirmed", False)
                detection["gemini_confidence"] = verification.get("confidence", 0)
                detection["gemini_type"] = verification.get("type", "unknown")
                
                # Check agreement between YOLO and Gemini
                if verification.get("hazard_confirmed") and detection["yolo_confidence"] >= 0.5:
                    detection["agreement"] = True
                    logger.info(f"   ✅ AGREEMENT: Both YOLO and Gemini confirm hazard")
                elif not verification.get("hazard_confirmed") and detection["yolo_confidence"] < 0.5:
                    detection["agreement"] = True
                    logger.info(f"   ✅ AGREEMENT: Both YOLO and Gemini say no hazard")
                else:
                    logger.info(f"   ⚠️ DISAGREEMENT: YOLO={detection['yolo_confidence']:.2f}, Gemini={verification.get('confidence', 0):.2f}")

                if not verification.get("hazard_confirmed", False):
                    self._save_hard_negative(frame_path, video_path, detection, speed_kmh=speed_kmh)
                
                # Try to clean up frame file
                try:
                    if context_frame_path and os.path.exists(context_frame_path):
                        os.remove(context_frame_path)
                    elif os.path.exists(frame_path):
                        os.remove(frame_path)
                except Exception:
                    pass
                
                return True
            
            return False
        except Exception as e:
            logger.warning(f"⚠️ Gemini verification failed: {e}")
            return False

    def _save_hard_negative(self, frame_path: str, video_path: str, detection: Dict[str, Any], speed_kmh: float = 0.0):
        """Persist false positives as empty-label samples for future training."""
        try:
            neg_dir = Path("raw_data") / "hard_negatives"
            neg_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{Path(video_path).stem}_{detection.get('frame_idx', 0)}_neg"
            img_dst = neg_dir / f"{stem}.jpg"
            txt_dst = neg_dir / f"{stem}.txt"
            meta_dst = neg_dir / f"{stem}.json"
            shutil.copy2(frame_path, img_dst)
            txt_dst.write_text("", encoding="utf-8")
            meta_dst.write_text(
                json.dumps({
                    "source_video": os.path.basename(video_path),
                    "frame_idx": int(detection.get("frame_idx", 0) or 0),
                    "yolo_confidence": float(detection.get("yolo_confidence", 0.0) or 0.0),
                    "speed_kmh": float(speed_kmh),
                    "speed_bucket": self._speed_bucket_label(speed_kmh),
                    "class_name": detection.get("class_name", "unknown"),
                }, indent=2),
                encoding="utf-8",
            )
            logger.info(f"   🧱 Hard negative saved: {img_dst.name}")
        except Exception as e:
            logger.warning(f"   ⚠️ Hard negative save failed: {e}")

    def process_video_complete(self, video_path: str, speed_kmh: float = 60.0) -> Dict[str, Any]:
        """Complete processing: YOLO -> Gemini verification -> Report."""
        logger.info(f"\n{'='*70}")
        logger.info(f"Processing video: {os.path.basename(video_path)}")
        logger.info(f"{'='*70}")
        
        # Step 1: YOLO inference
        yolo_detections = self.analyze_yolo_detections(video_path, speed_kmh=speed_kmh)
        
        if not yolo_detections:
            logger.warning(f"⚠️ No detections found in {video_path}")
            return {
                "video_path": video_path,
                "video_name": os.path.basename(video_path),
                "yolo_detections_count": 0,
                "gemini_verifications": 0,
                "detections": []
            }
        
        # Step 2: Verify each detection with Gemini
        logger.info(f"\n🔬 Starting Gemini verification for {len(yolo_detections)} detections...")
        verified_count = 0
        agreement_count = 0

        verify_limit = min(len(yolo_detections), self.max_verifications_per_video)
        if verify_limit < len(yolo_detections):
            logger.info(
                f"   ⚡ Verification cap active: {verify_limit}/{len(yolo_detections)} detections this cycle"
            )
        
        for idx, detection in enumerate(yolo_detections[:verify_limit]):
            logger.info(f"[{idx+1}/{verify_limit}] Verifying detection...")

            if hasattr(self.learner, "is_quota_backoff_active") and self.learner.is_quota_backoff_active():
                if self.allow_yolo_proxy_on_quota_backoff:
                    remaining = yolo_detections[idx:verify_limit]
                    logger.warning(
                        "⏭️ Gemini backoff active; applying YOLO proxy verification "
                        f"for remaining {len(remaining)} detections (min_conf={self.yolo_proxy_min_conf:.2f})"
                    )
                    for proxy_detection in remaining:
                        if self._apply_yolo_proxy_verification(proxy_detection):
                            verified_count += 1
                            agreement_count += 1
                else:
                    logger.warning("⏭️ Gemini backoff active; skipping remaining verifications in this video")
                break
            
            if self.verify_detection_with_gemini(video_path, detection, speed_kmh=speed_kmh):
                verified_count += 1
                if detection["agreement"]:
                    agreement_count += 1
            
            # Throttle Gemini API calls (Slow Method)
            if idx < verify_limit - 1:
                time.sleep(3.5)

        # Step 2b: Sample background only when we actually got Gemini signal.
        background_checks = []
        if verified_count > 0:
            background_checks = self._run_background_checks(video_path, yolo_detections, speed_kmh=speed_kmh)
        
        # Step 3: Calculate statistics
        avg_yolo_conf = sum(d["yolo_confidence"] for d in yolo_detections) / len(yolo_detections) if yolo_detections else 0
        verified_detections = [d for d in yolo_detections if d["gemini_verification"] is not None]
        avg_gemini_conf = sum(d["gemini_confidence"] for d in verified_detections) / len(verified_detections) if verified_detections else 0
        agreement_rate = (agreement_count / verified_count * 100) if verified_count > 0 else 0
        
        result = {
            "video_path": video_path,
            "video_name": os.path.basename(video_path),
            "speed_kmh": float(speed_kmh),
            "speed_bucket": self._speed_bucket_label(speed_kmh),
            "yolo_detections_count": len(yolo_detections),
            "gemini_verifications": verified_count,
            "agreement_count": agreement_count,
            "avg_yolo_confidence": round(avg_yolo_conf, 3),
            "avg_gemini_confidence": round(avg_gemini_conf, 3),
            "agreement_rate_percent": round(agreement_rate, 1),
            "background_checks": background_checks,
            "processed_at": datetime.now().isoformat(),
            "detections": yolo_detections
        }
        
        logger.info(f"\n📊 Video Summary:")
        logger.info(f"   YOLO Detections: {len(yolo_detections)}")
        logger.info(f"   Gemini Verifications: {verified_count}")
        logger.info(f"   Agreement Rate: {agreement_rate:.1f}%")
        logger.info(f"   Avg YOLO Confidence: {avg_yolo_conf:.3f}")
        logger.info(f"   Avg Gemini Confidence: {avg_gemini_conf:.3f}")
        
        return result

    def _run_background_checks(self, video_path: str, detections: List[Dict[str, Any]], sample_count: int = 3, speed_kmh: float = 0.0) -> List[Dict[str, Any]]:
        """Run a few Gemini checks on frames without using YOLO detections, to estimate recall."""
        checks: List[Dict[str, Any]] = []
        if hasattr(self.learner, "is_quota_backoff_active") and self.learner.is_quota_backoff_active():
            return checks
        try:
            cap = cv2.VideoCapture(video_path)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            if frame_count <= 0:
                return checks

            detection_frames = {int(d.get("frame_idx", -1)) for d in detections}
            if speed_kmh >= 120:
                sample_count = max(sample_count, 4)
            elif speed_kmh < 30:
                sample_count = max(2, sample_count - 1)
            candidate_frames = []
            for idx in range(1, sample_count + 1):
                frame_idx = int(frame_count * idx / (sample_count + 1))
                if frame_idx not in detection_frames:
                    candidate_frames.append(frame_idx)

            for frame_idx in candidate_frames[:sample_count]:
                success, frame_path = self.extract_frame(video_path, frame_idx)
                if not success:
                    continue

                try:
                    verification = self.learner.audit_jerk_event(
                        frame_path,
                        {
                            "timestamp": int(time.time()),
                            "source": "background_check",
                            "speed_kmh": float(speed_kmh),
                            "speed_bucket": self._speed_bucket_label(speed_kmh),
                        },
                    )
                    if verification and verification.get("hazard_confirmed", False):
                        checks.append({
                            "frame_idx": frame_idx,
                            "hazard_type": verification.get("type", "unknown"),
                            "confidence": verification.get("confidence", 0),
                            "confirmed": True,
                        })
                    else:
                        checks.append({
                            "frame_idx": frame_idx,
                            "hazard_type": "none",
                            "confidence": 0,
                            "confirmed": False,
                        })
                finally:
                    try:
                        os.remove(frame_path)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"⚠️ Background recall checks failed: {e}")

        return checks

    def run_batch_youtube_verification(self, urls: List[str], speed_kmh: float = 60.0, skip_processed: bool = True):
        """Download/resolve and verify multiple video sources."""
        logger.info(f"\n🚀 Starting YouTube SSL Verification Pipeline")
        logger.info(f"Processing {len(urls)} video(s) at target speed {speed_kmh} km/h...")
        self._mark_activity("batch_start")
        
        processed_this_cycle = 0
        for url in urls:
            try:
                if self.max_videos_per_cycle > 0 and processed_this_cycle >= self.max_videos_per_cycle:
                    logger.info(f"⏸️ Reached max_videos_per_cycle={self.max_videos_per_cycle}, ending cycle early")
                    self._mark_activity("batch_capped")
                    break

                url_key = self._url_hash(url)
                if skip_processed and url_key in self.loop_state["processed_url_hashes"]:
                    logger.info(f"⏭️ Already processed URL, skipping: {url}")
                    self._mark_activity("url_skipped")
                    continue

                # Resolve source (YouTube URL, direct HTTP URL, or local file path)
                video_path = self._resolve_source_video(url)
                if not video_path:
                    logger.error(f"⏭️ Skipping unresolved source: {url}")
                    self._mark_activity("url_failed_resolve")
                    continue
                
                # Process video
                self._mark_activity("processing_video")
                result = self.process_video_complete(video_path, speed_kmh=speed_kmh)
                
                # Update report
                self.verification_report["videos_processed"][result["video_name"]] = result
                self.verification_report["summary"]["total_videos"] += 1
                self.verification_report["summary"]["total_yolo_detections"] += result["yolo_detections_count"]
                self.verification_report["summary"]["total_verified_by_gemini"] += result["gemini_verifications"]
                self.verification_report["summary"].setdefault("speed_buckets", {})
                bucket = result.get("speed_bucket", "unknown")
                bucket_entry = self.verification_report["summary"]["speed_buckets"].setdefault(bucket, {"videos": 0, "detections": 0, "verified": 0, "agreements": 0})
                bucket_entry["videos"] += 1
                bucket_entry["detections"] += result["yolo_detections_count"]
                bucket_entry["verified"] += result["gemini_verifications"]
                bucket_entry["agreements"] += result.get("agreement_count", 0)
                if url_key not in self.loop_state["processed_url_hashes"]:
                    self.loop_state["processed_url_hashes"].append(url_key)
                    self._save_loop_state()

                processed_this_cycle += 1
                if self.cooldown_sec > 0:
                    logger.info(f"🧊 Cooling down for {self.cooldown_sec}s")
                    time.sleep(self.cooldown_sec)
                
            except Exception as e:
                logger.error(f"❌ Error processing {url}: {e}")
                continue

        # Last-resort no-stop behavior: process cached footage if nothing was processed this cycle.
        if processed_this_cycle == 0:
            cached = self._latest_cached_video()
            if cached:
                logger.warning("⚠️ No sources processed this cycle. Running cached fallback clip.")
                try:
                    self._mark_activity("cached_fallback_processing")
                    result = self.process_video_complete(cached, speed_kmh=speed_kmh)
                    self.verification_report["videos_processed"][result["video_name"]] = result
                    self.verification_report["summary"]["total_videos"] += 1
                    self.verification_report["summary"]["total_yolo_detections"] += result["yolo_detections_count"]
                    self.verification_report["summary"]["total_verified_by_gemini"] += result["gemini_verifications"]
                    self.verification_report["summary"].setdefault("speed_buckets", {})
                    bucket = result.get("speed_bucket", "unknown")
                    bucket_entry = self.verification_report["summary"]["speed_buckets"].setdefault(bucket, {"videos": 0, "detections": 0, "verified": 0, "agreements": 0})
                    bucket_entry["videos"] += 1
                    bucket_entry["detections"] += result["yolo_detections_count"]
                    bucket_entry["verified"] += result["gemini_verifications"]
                    bucket_entry["agreements"] += result.get("agreement_count", 0)
                except Exception as e:
                    logger.error(f"❌ Cached fallback processing failed: {e}")
                    self._mark_activity("cached_fallback_failed")
        
        # Calculate final statistics
        if self.verification_report["summary"]["total_videos"] > 0:
            total_yolo = self.verification_report["summary"]["total_yolo_detections"]
            total_verified = self.verification_report["summary"]["total_verified_by_gemini"]

            processed_values = list(self.verification_report["videos_processed"].values())
            denom = len(processed_values) if processed_values else 1

            avg_yolo_conf = sum(
                float(v.get("avg_yolo_confidence", 0.0) or 0.0) for v in processed_values
            ) / denom

            avg_gemini_conf = sum(
                float(v.get("avg_gemini_confidence", 0.0) or 0.0) for v in processed_values
            ) / denom
            
            total_agreements = sum(
                v.get("agreement_count", 0) for v in self.verification_report["videos_processed"].values()
            )
            
            self.verification_report["summary"]["total_frames_analyzed"] = total_yolo
            self.verification_report["summary"]["avg_yolo_confidence"] = round(avg_yolo_conf, 3)
            self.verification_report["summary"]["avg_gemini_confidence"] = round(avg_gemini_conf, 3)
            self.verification_report["summary"]["total_hard_negatives"] = len(list((Path("raw_data") / "hard_negatives").glob("*.jpg")))
            self.verification_report["summary"]["agreement_rate"] = round(
                (total_agreements / total_verified * 100) if total_verified > 0 else 0, 1
            )
        
        # Save report
        self._save_report()
        
        # Print summary
        logger.info(f"\n{'='*70}")
        logger.info(f"✅ BATCH VERIFICATION COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(json.dumps(self.verification_report["summary"], indent=2))
        self._mark_activity("batch_complete")

    def run_realtime_loop(self, url_file: str, speed_kmh: float = 150.0, poll_interval_sec: int = 60):
        """Continuously ingest URLs and verify new videos in cycles."""
        logger.info("\n🚦 Starting real-world SSL loop mode")
        logger.info(f"Target speed profile: {speed_kmh} km/h")
        logger.info(f"Polling URL file: {url_file} every {poll_interval_sec}s")

        while True:
            try:
                if not os.path.exists(url_file):
                    logger.warning(f"URL file not found yet: {url_file}")
                    time.sleep(poll_interval_sec)
                    continue

                with open(url_file, "r", encoding="utf-8") as f:
                    urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

                self._mark_activity("cycle_running")

                if not urls:
                    logger.warning("No URLs found in source file this cycle; trying cached fallback")
                    cached = self._latest_cached_video()
                    if cached:
                        self.run_batch_youtube_verification([cached], speed_kmh=speed_kmh, skip_processed=False)
                    else:
                        logger.warning("No cached videos available yet")
                else:
                    self.run_batch_youtube_verification(urls, speed_kmh=speed_kmh, skip_processed=True)

                self.loop_state["cycles_completed"] += 1
                self.loop_state["last_cycle_at"] = datetime.now().isoformat()
                self.loop_state["current_phase"] = "cycle_complete"
                self.loop_state["last_activity_at"] = datetime.now().isoformat()
                self._save_loop_state()

            except KeyboardInterrupt:
                logger.info("\n🛑 Loop stopped by user")
                break
            except Exception as e:
                logger.error(f"❌ Loop cycle error: {e}")

            logger.info(f"⏳ Sleeping {poll_interval_sec}s before next cycle...")
            time.sleep(poll_interval_sec)

    def _save_report(self):
        """Save verification report to JSON"""
        with open(self.verification_report_path, 'w') as f:
            json.dump(self.verification_report, f, indent=2)
        logger.info(f"💾 Report saved: {self.verification_report_path}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="YouTube SSL Verification Pipeline")
    parser.add_argument("--urls", nargs="+", help="YouTube URLs")
    parser.add_argument("--file", help="File with YouTube URLs")
    parser.add_argument("--test-mode", action="store_true", help="Use default test URLs")
    parser.add_argument("--videos-dir", default="Testing videos", help="Videos directory")
    parser.add_argument("--model", default=str(resolve_yolo_pothole_pt()), help="YOLO model")
    parser.add_argument("--loop", action="store_true", help="Run continuous real-world loop mode")
    parser.add_argument("--poll-interval", type=int, default=60, help="Loop poll interval in seconds")
    parser.add_argument("--speed-kmh", type=float, default=150.0, help="Target operational speed profile")
    parser.add_argument("--path", choices=["old", "new"], default="new", help="old=classic single-pass, new=speed-aware pipeline")
    parser.add_argument("--gentle", action="store_true", help="Lower processing load to avoid stressing hardware")
    parser.add_argument("--cooldown-sec", type=float, default=2.0, help="Pause between videos")
    parser.add_argument("--max-videos-per-cycle", type=int, default=1, help="Cap processed videos per cycle (0 = no cap)")
    parser.add_argument("--max-verifications-per-video", type=int, default=12, help="Cap Gemini checks per video to keep loop responsive")
    parser.add_argument("--gpu-only", action="store_true", default=True, help="Fail fast unless CUDA is available")
    
    args = parser.parse_args()
    
    # Initialize pipeline
    pipeline = YouTubeSSLVerificationPipeline(
        videos_dir=args.videos_dir,
        model_path=args.model,
        gentle_mode=args.gentle,
        cooldown_sec=args.cooldown_sec,
        max_videos_per_cycle=args.max_videos_per_cycle,
        max_verifications_per_video=args.max_verifications_per_video,
        gpu_only=True,
    )
    
    # New path supports loop mode for continuous operation.
    if args.path == "new" and args.loop:
        url_file = args.file if args.file else "video_sources.txt"
        pipeline.run_realtime_loop(
            url_file=url_file,
            speed_kmh=args.speed_kmh,
            poll_interval_sec=args.poll_interval,
        )
        return

    # Determine URLs
    urls = []
    
    if args.test_mode:
        urls = [
            "https://www.youtube.com/watch?v=NFpo7_sAdWU",
            "https://www.youtube.com/watch?v=yP9v8KRym9c"
        ]
        logger.info("🧪 Test mode: Using default URLs")
    
    elif args.file:
        try:
            with open(args.file, 'r') as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            logger.info(f"📂 Loaded {len(urls)} URLs from {args.file}")
        except FileNotFoundError:
            logger.error(f"❌ File not found: {args.file}")
            sys.exit(1)
    
    elif args.urls:
        urls = args.urls
    
    else:
        parser.print_help()
        sys.exit(1)
    
    # Run pipeline
    if urls:
        if args.path == "old":
            # Classic one-pass behavior with conservative speed profile and no dedupe skip.
            old_speed = min(args.speed_kmh, 60.0)
            pipeline.run_batch_youtube_verification(urls, speed_kmh=old_speed, skip_processed=False)
        else:
            pipeline.run_batch_youtube_verification(urls, speed_kmh=args.speed_kmh, skip_processed=True)
    else:
        logger.error("❌ No URLs provided")
        sys.exit(1)


if __name__ == "__main__":
    main()
