from __future__ import annotations

import gc
import os
from typing import Any, Dict, Tuple


def _gpu_required(require_gpu: bool) -> bool:
    if require_gpu:
        return True
    env_flag = os.environ.get("GPU_ONLY", "0").strip().lower()
    return env_flag in {"1", "true", "yes", "on"}


def _override_enabled() -> bool:
    password_override = os.environ.get("GPU_OVERRIDE_PASSWORD", "").strip()
    return os.environ.get("GPU_OVERRIDE_ENABLE", "0").strip().lower() in {"1", "true", "yes", "on"} and len(password_override) >= 16


def resolve_ultralytics_device(
    torch_module: Any,
    prefer_index: int = 0,
    require_gpu: bool = False,
) -> Tuple[Any, str, Dict[str, Any]]:
    """Return an Ultralytics-compatible device selector and runtime metadata.

    The first return value is either an integer CUDA index or the string "cpu".
    """
    meta: Dict[str, Any] = {
        "torch_imported": torch_module is not None,
        "cuda_available": False,
        "device_name": "cpu",
        "cuda_index": None,
        "override_cpu": False,
    }
    if _override_enabled():
        meta["override_cpu"] = True
        return "cpu", "cpu", meta

    gpu_required = _gpu_required(require_gpu)

    if torch_module is None:
        if gpu_required:
            raise RuntimeError("GPU_ONLY enforced but torch is unavailable")
        return "cpu", "cpu", meta

    try:
        cuda_available = bool(torch_module.cuda.is_available())
    except Exception:
        cuda_available = False

    meta["cuda_available"] = cuda_available
    if not cuda_available:
        if gpu_required:
            raise RuntimeError("GPU_ONLY enforced but CUDA is unavailable")
        return "cpu", "cpu", meta

    try:
        count = int(torch_module.cuda.device_count())
    except Exception:
        count = 0

    if count <= 0:
        if gpu_required:
            raise RuntimeError("GPU_ONLY enforced but no CUDA devices were detected")
        return "cpu", "cpu", meta

    index = min(max(int(prefer_index), 0), count - 1)
    meta["cuda_index"] = index

    try:
        name = str(torch_module.cuda.get_device_name(index))
    except Exception:
        name = f"cuda:{index}"

    meta["device_name"] = name

    # Prime CUDA allocator/runtime for better stability on low VRAM GPUs.
    try:
        torch_module.cuda.set_device(index)
        torch_module.cuda.empty_cache()
        gc.collect()
        if hasattr(torch_module.backends, "cudnn"):
            torch_module.backends.cudnn.benchmark = True
    except Exception:
        pass

    return index, f"cuda:{index}", meta


def log_runtime(logger: Any, runtime_name: str, selector: Any, meta: Dict[str, Any]) -> None:
    if meta.get("override_cpu", False):
        logger.warning("%s runtime: CPU override enabled via password", runtime_name)
        return

    if not meta.get("torch_imported", False):
        logger.warning("%s runtime: torch unavailable, falling back to CPU", runtime_name)
        return

    if meta.get("cuda_available", False):
        logger.info(
            "%s runtime: CUDA enabled | device=%s | ultralytics_device=%s",
            runtime_name,
            meta.get("device_name", "unknown"),
            selector,
        )
        return

    logger.warning("%s runtime: CUDA not available, falling back to CPU", runtime_name)
