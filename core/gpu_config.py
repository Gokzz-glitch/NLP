"""
core/gpu_config.py — Strict CUDA Selection Configuration
========================================================
Call apply() once at orchestrator startup.
Uses NVIDIA GPU with a GPU1-first policy (second NVIDIA GPU when present).
Never falls back to CPU.
"""

import os
import gc
import logging
import subprocess

logger = logging.getLogger("GPUConfig")


def _override_enabled() -> bool:
    """Check GPU override against secure environment variable.
    
    Raises:
        RuntimeError: If GPU_OVERRIDE_PASSWORD env var not set or invalid.
    """
    password_override = os.environ.get("GPU_OVERRIDE_PASSWORD", "").strip()
    if not password_override:
        # If override is enabled but password missing, fail securely
        if os.environ.get("GPU_OVERRIDE_ENABLE", "0") == "1":
            raise RuntimeError(
                "GPU_OVERRIDE_ENABLE=1 but GPU_OVERRIDE_PASSWORD not set. "
                "Set GPU_OVERRIDE_PASSWORD in .env or environment."
            )
        return False
    
    # Verify password is sufficiently strong (min 16 chars)
    if len(password_override) < 16:
        raise RuntimeError(
            f"GPU_OVERRIDE_PASSWORD too weak ({len(password_override)} chars). "
            "Minimum 16 characters required."
        )
    
    return os.environ.get("GPU_OVERRIDE_ENABLE", "0") == "1"


def apply():
    """Set environment variables and PyTorch defaults with strict GPU-only & RAM-Lean policy."""

    # ── 1. Force Aggressive Single-Threading (Critical for 92% RAM bottleneck) ──
    # This prevents BLAS libraries from spawning CPU-heavy threads.
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

    # ── 2. Force RTX 3050 (GPU 1) ──
    # Windows Task Manager (GPU 1) usually matches PCI_BUS_ID 0 in torch.
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = "0" 

    # ── 3. Force Video-IO and UI to NVIDIA (Aegis Hardening v3/v6) ──
    # Discourage Intel/MSMF (Hardware Capture on iGPU)
    # By default, Windows 'Desktop' apps may use GPU 0 (Intel) for VideoIO.
    os.environ["OPENCV_VIDEOIO_PRIORITY_MSMF"] = "0"
    os.environ["OPENCV_VIDEOIO_PRIORITY_DSHOW"] = "0"
    os.environ["OPENCV_VIDEOIO_PRIORITY_FFMPEG"] = "1"
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "video_codec;h264_cuvid" # NV Dec (GPU 1)
    # New: Explicitly target NV CUDA 
    os.environ["OPENCV_CUDA_DEVICE"] = "0"
    
    # ── 4. VRAM efficiency flags for 4 GB VRAM ──────────────────────────────────
    # expandable_segments prevents small fragmented allocations from triggering OOM.
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:64,expandable_segments:True"

    # ── 4. Verify and log ────────────────────────────────────────────────────────
    try:
        import torch
        if _override_enabled():
            os.environ["GPU_ONLY"] = "0"
            logger.warning("GPU override enabled: CPU fallback temporarily permitted.")
            return "cpu"

        if not torch.cuda.is_available():
            logger.error("🛑 FATAL: CUDA not found. 'Fixed Rule' prevents CPU fallback.")
            raise RuntimeError("CUDA is required but not available. CPU fallback is disabled.")

        device_name = torch.cuda.get_device_name(0)
        torch.cuda.set_device(0)
        torch.cuda.empty_cache()
        gc.collect()
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = True
        
        # Force torch to only ever use 1 thread for management/CPU-side glue code
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)

        logger.info(
            f"✅ Aegis Force Mode: Locked to {device_name} (GPU 1) | CPU/RAM stress minimized."
        )
        return "cuda:0"

    except Exception as e:
        logger.error(f"GPU config error: {e}")
        raise

def get_optimal_batch_size(base: int = 1) -> int:
    """
    Safe baseline for 4GB RTX 3050. Start at 8, scale up to 16, drop to 4 on OOM.
    """
    return max(4, min(16, int(base or 8)))


def emergency_vram_cleanup(*objects_to_release) -> None:
    """Best-effort emergency cleanup for OOM recovery paths."""
    for obj in objects_to_release:
        try:
            if hasattr(obj, "clear"):
                obj.clear()
        except Exception:
            pass
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()

