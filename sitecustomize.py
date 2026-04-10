"""Global Python startup hook for strict CUDA-only execution.

Loaded automatically by Python when this directory is on sys.path.
"""

from __future__ import annotations

import os


def _override_enabled() -> bool:
    password_override = os.environ.get("GPU_OVERRIDE_PASSWORD", "").strip()
    return os.environ.get("GPU_OVERRIDE_ENABLE", "0").strip().lower() in {"1", "true", "yes", "on"} and len(password_override) >= 16


def _enforce_cuda_only() -> None:
    # Hard pin to the NVIDIA adapter expected by this workspace.
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    os.environ["GPU_ONLY"] = "1"

    # Reduce CPU worker/thread activity to avoid CPU-heavy fallback behavior.
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

    # Prefer deterministic CUDA allocator settings for a 4GB card.
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:64,expandable_segments:True"

    # Optional hints for other runtimes.
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

    try:
        import torch  # type: ignore
    except Exception as exc:
        if _override_enabled():
            os.environ["GPU_ONLY"] = "0"
            return
        raise RuntimeError(
            "Strict GPU mode is enabled but PyTorch is unavailable. CPU fallback is disabled."
        ) from exc

    if not torch.cuda.is_available():
        if _override_enabled():
            os.environ["GPU_ONLY"] = "0"
            return
        raise RuntimeError(
            "Strict GPU mode is enabled but CUDA is unavailable. CPU fallback is disabled."
        )

    torch.cuda.set_device(0)


_enforce_cuda_only()
