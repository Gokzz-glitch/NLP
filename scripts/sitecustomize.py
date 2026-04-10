"""Strict GPU startup hook for scripts executed from the scripts directory."""

from __future__ import annotations

import os





def _override_enabled() -> bool:
    password_env = os.environ.get("GPU_OVERRIDE_PASSWORD", "")
    return (
        os.environ.get("GPU_OVERRIDE_ENABLE", "0") == "1"
        and len(password_env) >= 16
    )


def _enforce_cuda_only() -> None:
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    os.environ["GPU_ONLY"] = "1"

    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:64,expandable_segments:True"

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
