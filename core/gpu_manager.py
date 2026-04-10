import asyncio
import gc
import torch
import logging
import os
import time
from collections import deque
from typing import Deque, Dict, Optional

# Configure indexing for RTX 3050
DEVICE_ID = 0 
DEVICE = torch.device(f"cuda:{DEVICE_ID}")

logger = logging.getLogger("GPUManager")


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

class GPUManager:
    """
    Centralized coordinator for RTX 3050 usage.
    Ensures 'Heavy Work' stays off CPU and RAM.
    """
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GPUManager, cls).__new__(cls)
            cls._instance.active_tasks = 0
            cls._instance._wait_queue = deque()
            cls._instance._current_token = None
            cls._instance._task_tickets: Dict[int, str] = {}
            cls._instance._turn_started_at = 0.0
            slice_ms = int(os.environ.get("GPU_TIMESLICE_MS", "250"))
            cls._instance._slice_seconds = max(0.05, slice_ms / 1000.0)
            cls._instance._handoff_seconds = 0.02
            cls._instance._setup_env()
        return cls._instance

    def _setup_env(self):
        """Forces the environment to recognize only the RTX 3050 for this process."""
        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        os.environ["CUDA_VISIBLE_DEVICES"] = str(DEVICE_ID)
        os.environ["GPU_ONLY"] = "1"
        # Optimized memory allocation for 4GB VRAM
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        
        if not torch.cuda.is_available():
            if _override_enabled():
                os.environ["GPU_ONLY"] = "0"
                logger.warning("GPU override enabled: CPU fallback temporarily permitted.")
                return
            logger.error("🛑 CRITICAL: RTX 3050 NOT DETECTED VIA TORCH. Check drivers.")
            raise RuntimeError("Strict GPU policy active: CUDA unavailable and CPU fallback disabled.")
        else:
            torch.cuda.set_device(0)
            self._prime_cuda_runtime()
            logger.info(f"✅ Aegis GPU Manager: Forced to {torch.cuda.get_device_name(0)}")

    def _prime_cuda_runtime(self) -> None:
        """Prime CUDA runtime for stable long-running sessions on low VRAM cards."""
        if not torch.cuda.is_available():
            return
        torch.cuda.empty_cache()
        gc.collect()
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = True

    def _task_key(self) -> int:
        task = asyncio.current_task()
        return id(task) if task is not None else -1

    async def _wait_for_turn(self, ticket: str, task_name: str, vram_limit_mb: int) -> None:
        while True:
            at_front = len(self._wait_queue) > 0 and self._wait_queue[0] == ticket
            reserved_mb = torch.cuda.memory_reserved(0) / (1024 * 1024) if torch.cuda.is_available() else 0

            if at_front and reserved_mb < vram_limit_mb and not self._lock.locked():
                await self._lock.acquire()
                self._current_token = ticket
                self._turn_started_at = time.monotonic()
                self.active_tasks += 1
                logger.info(f"🚀 GPU_ACTIVE: Task '{task_name}' now running on RTX 3050.")
                return

            if at_front and reserved_mb >= vram_limit_mb:
                logger.warning(
                    f"🚨 VRAM CRITICAL: {reserved_mb:.0f}MB > {vram_limit_mb}MB. Task '{task_name}' waiting in queue..."
                )

            await asyncio.sleep(0.05)

    async def acquire(self, task_name="Unknown"):
        """
        Aegis v5 VRAM Governor:
        Queues the task if VRAM > 75% (3.07 GB).
        Ensures the mission-critical Vision System has priority.
        """
        if not torch.cuda.is_available() and not _override_enabled():
            raise RuntimeError("Strict GPU policy active: CUDA unavailable and CPU fallback disabled.")

        VRAM_LIMIT_MB = 3072 # 75% of 4096MB
        task_key = self._task_key()
        ticket = self._task_tickets.get(task_key)
        if ticket is None:
            ticket = f"{task_name}:{task_key}:{time.monotonic_ns()}"
            self._task_tickets[task_key] = ticket
            self._wait_queue.append(ticket)

        logger.info(f"⏳ QUEUE: Task '{task_name}' waiting for GPU Lock...")
        await self._wait_for_turn(ticket, task_name, VRAM_LIMIT_MB)

    async def checkpoint(self, task_name="Unknown") -> bool:
        """Cooperative time-slicing checkpoint for long-running GPU tasks.

        Call this inside training/inference loops to share RTX 3050 fairly.
        Returns True when the task yielded and reacquired on a new slice.
        """
        task_key = self._task_key()
        ticket = self._task_tickets.get(task_key)
        if ticket is None or self._current_token != ticket:
            return False

        elapsed = time.monotonic() - self._turn_started_at
        if elapsed < self._slice_seconds:
            return False

        if self._lock.locked():
            self._lock.release()
            self.active_tasks = max(0, self.active_tasks - 1)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

        if self._wait_queue and self._wait_queue[0] == ticket:
            self._wait_queue.popleft()
            self._wait_queue.append(ticket)

        self._current_token = None
        logger.info(
            "⏱️ GPU TIMESLICE: Task '%s' yielded after %.0fms and re-queued.",
            task_name,
            elapsed * 1000.0,
        )
        await asyncio.sleep(self._handoff_seconds)
        await self._wait_for_turn(ticket, task_name, 3072)
        return True

    def release(self, task_name="Unknown"):
        """Releases the GPU lock and clears cache for next task."""
        task_key = self._task_key()
        ticket = self._task_tickets.pop(task_key, None)
        if ticket is None:
            ticket = self._current_token

        if self._lock.locked():
            self._lock.release()
            self.active_tasks = max(0, self.active_tasks - 1)
            # Proactive cleanup to keep VRAM < 75%
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            logger.info(f"✅ GPU_RELEASED: Task '{task_name}' completed. Cache cleared.")

        if ticket is not None:
            try:
                if self._wait_queue and self._wait_queue[0] == ticket:
                    self._wait_queue.popleft()
                else:
                    self._wait_queue.remove(ticket)
            except ValueError:
                pass

        if self._current_token == ticket:
            self._current_token = None

    def get_device_string(self):
        """Zero-Fallback Policy: CUDA or Die."""
        if not torch.cuda.is_available() and not _override_enabled():
            raise RuntimeError("🛑 AEGIS ERROR: GPU-LOCK ENFORCED. No CUDA device detected.")
        if not torch.cuda.is_available() and _override_enabled():
            return "cpu"
        return f"cuda:{DEVICE_ID}"

    # ── Shared Intelligence Tiers (Aegis Hardening v4) ──
    _shared_models = {}

    def get_shared_model(self, model_name="all-MiniLM-L6-v2"):
        """
        Swarm Intelligence Singleton:
        Prevents 25 agents from loading separate embedders.
        Returns the single GPU-resident instance of the model.
        """
        if model_name not in self._shared_models:
            logger.info(f"🧠 Aegis Intelligence: Moving '{model_name}' to RTX 3050...")
            try:
                from sentence_transformers import SentenceTransformer
                device = self.get_device_string()
                model = SentenceTransformer(model_name, device=device)
                if device.startswith("cuda"):
                    model.half()  # Force FP16 only on CUDA
                self._shared_models[model_name] = model
                logger.info(f"✅ Aegis GPU Embedding Service Online: {model_name}")
            except Exception as e:
                logger.error(f"❌ Failed to load shared model {model_name} on GPU: {e}")
                return None
        return self._shared_models[model_name]

    def optimize_model(self, model):
        """Standard optimization for 4GB VRAM."""
        try:
            device = self.get_device_string()
            model.to(device)
            if device.startswith("cuda") and hasattr(model, "half"):
                model.half()  # Force FP16 only on CUDA
            return model
        except Exception as e:
            logger.error(f"Failed to optimize model on GPU: {e}")
            return model

    def emergency_vram_cleanup(self, *objects_to_release):
        """Best-effort emergency cleanup after OOM or unexpected GPU failures."""
        for obj in objects_to_release:
            try:
                if hasattr(obj, "clear"):
                    obj.clear()
            except Exception:
                pass
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

gpu_manager = GPUManager()
