import os
import sys
import gc
from pathlib import Path


def add_repo_root_to_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def force_offline_mode() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _override_enabled() -> bool:
    password_override = os.environ.get("GPU_OVERRIDE_PASSWORD", "").strip()
    return os.environ.get("GPU_OVERRIDE_ENABLE", "0").strip().lower() in {"1", "true", "yes", "on"} and len(password_override) >= 16


def enforce_strict_gpu_policy() -> None:
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

    if _override_enabled():
        os.environ["GPU_ONLY"] = "0"
        return

    if not torch.cuda.is_available():
        raise RuntimeError(
            "Strict GPU mode is enabled but CUDA is unavailable. CPU fallback is disabled."
        )

    torch.cuda.set_device(0)
    torch.cuda.empty_cache()
    gc.collect()
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = True


force_offline_mode()
enforce_strict_gpu_policy()
