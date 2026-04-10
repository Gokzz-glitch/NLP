import os
import sys
from typing import Any, Callable, Iterable, List

# ---------------------------------------------------------------------------
# STRICT RULE: CLOUD-ONLY ARCHITECTURE
# ---------------------------------------------------------------------------
# Detect if we are running in Google Colab (Cloud)
try:
    import google.colab
    IN_COLAB = True
except ImportError:
    # Fallback to env var check for various Colab environments
    IN_COLAB = any(k in os.environ for k in ['COLAB_GPU', 'COLAB_JUPYTER_IP', 'COLAB_RELEASE_TAG'])

PROJECT_ROOT = "/content/drive/My Drive/NLP" if IN_COLAB else os.getcwd()

# Runtime policy: local small jobs use a dedicated interpreter, heavy jobs prefer Colab.
DEFAULT_SMALL_JOB_PYTHON = os.environ.get("SMALL_JOB_PYTHON", sys.executable)
SMALL_JOB_PYTHON = DEFAULT_SMALL_JOB_PYTHON
HEAVY_TASK_EXECUTOR = os.environ.get("HEAVY_TASK_EXECUTOR", "rtx").strip().lower()
WORKLOAD_POLICY = os.environ.get("WORKLOAD_POLICY", "rtx_only").strip().lower()
COLAB_ORDER = os.environ.get("COLAB_ORDER", "desc").strip().lower()
RTX_ORDER = os.environ.get("RTX_ORDER", "asc").strip().lower()


def _normalize_order(order: str, fallback: str) -> str:
    order = (order or "").strip().lower()
    return order if order in {"asc", "desc"} else fallback


COLAB_ORDER = _normalize_order(COLAB_ORDER, "desc")
RTX_ORDER = _normalize_order(RTX_ORDER, "asc")


def choose_executor_for_workload(weight: float) -> str:
    """Route workloads to maximize Colab usage and keep RTX for lighter jobs.

    Workload weight is expected in range [0.0, 1.0]. Values outside are clamped.
    """
    w = max(0.0, min(1.0, float(weight)))
    policy = WORKLOAD_POLICY

    # Force all workloads to local RTX when requested.
    if policy in {"rtx_only", "local_only"}:
        return "rtx"

    # Default policy pushes medium/heavy jobs to Colab.
    if policy == "colab_max":
        return "colab" if w >= 0.35 else "rtx"

    # Conservative fallback: only heavy jobs go to Colab.
    if policy == "balanced":
        return "colab" if w >= 0.65 else "rtx"

    return HEAVY_TASK_EXECUTOR if w >= 0.65 else "rtx"


def sort_by_executor_priority(
    items: Iterable[Any],
    weight_getter: Callable[[Any], float],
    executor: str,
) -> List[Any]:
    """Sort workloads by executor-specific order preference.

    - Colab: descending (heaviest first)
    - RTX: ascending (lightest first)
    """
    normalized = (executor or "").strip().lower()
    order = COLAB_ORDER if normalized == "colab" else RTX_ORDER
    reverse = order == "desc"
    return sorted(items, key=lambda x: float(weight_getter(x)), reverse=reverse)


def get_small_job_python() -> str:
    """Return the interpreter to use for local/small jobs with robust fallback."""
    if SMALL_JOB_PYTHON and os.path.exists(SMALL_JOB_PYTHON):
        return SMALL_JOB_PYTHON
    return sys.executable or "python"

def enforce_cloud_only(task_name: str):
    """
    Enforces the 'Hardware Shield' rule. If a heavy task (training, deep 
    embeddings, large downloads) is attempted on your laptop, it will
    be blocked to protect your RAM and SSD.
    """
    if not IN_COLAB:
        # Temporary local override for RTX-only training sessions.
        if HEAVY_TASK_EXECUTOR == "rtx" or WORKLOAD_POLICY in {"rtx_only", "local_only"}:
            return
        print(f"\n" + "="*60)
        print(f"!!! HARDWARE SHIELD BLOCK !!!")
        print(f"TASK:    {task_name}")
        print(f"REASON:  Resource-intensive 'Heavy Cloud Workload' detected.")
        print(f"PROTECT: Local RAM and SSD health.")
        print(f"ACTION:  Please run this task in your Colab Notebook: ")
        print(f"         https://colab.research.google.com/drive/18xidCygco7Zb11h2YQ-ZZnlUo3le7Z7a")
        print("="*60 + "\n")
        sys.exit(1)

def heavy_task(task_name: str):
    """Decorator to enforce Colab-only execution for heavy functions."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            enforce_cloud_only(task_name)
            return func(*args, **kwargs)
        return wrapper
    return decorator

# HARDWARE SHIELD: For Cloud use, we store heavy models in /content/ 
# to protect the user's local SSD and reduce sync overhead.
def get_model_dir(model_type):
    if IN_COLAB:
        path = f"/content/models/{model_type}"
    else:
        # Fallback for small local tests only
        path = os.path.join(PROJECT_ROOT, "models", model_type)
    os.makedirs(path, exist_ok=True)
    return path

# Data Paths
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
DB_PATH = os.path.join(PROJECT_ROOT, "legal_vector_store.db")

# Model Paths
VISION_MODEL_DIR = get_model_dir("vision")
LLM_MODEL_DIR = get_model_dir("llm")
EMBEDDER_MODEL_DIR = get_model_dir("embedder")

def get_path(relative_path):
    return os.path.join(PROJECT_ROOT, relative_path)
