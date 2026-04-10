import os
import subprocess
import time
from config import (
    get_small_job_python,
    HEAVY_TASK_EXECUTOR,
    WORKLOAD_POLICY,
    COLAB_ORDER,
    RTX_ORDER,
)

os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["GPU_ONLY"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:64,expandable_segments:True"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

import torch

def golden_restart():
    print("🛡️ AEGIS GOLDEN RESTART: Preparing RTX 3050 Swarm...")
    print(f"🔒 GPU policy: CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES')} | GPU_ONLY={os.environ.get('GPU_ONLY')}")

    launch_env = os.environ.copy()
    launch_env["HEAVY_TASK_EXECUTOR"] = HEAVY_TASK_EXECUTOR
    launch_env["WORKLOAD_POLICY"] = WORKLOAD_POLICY
    launch_env["COLAB_ORDER"] = COLAB_ORDER
    launch_env["RTX_ORDER"] = RTX_ORDER
    
    # 1. Clear VRAM
    if torch.cuda.is_available():
        print("🧹 Clearing CUDA Cache (VRAM Flush)...")
        torch.cuda.empty_cache()
    
    # 2. Launch Dashboard API
    print("🚀 Launching Dashboard API (Port 5555)...")
    python_exe = get_small_job_python()
    print(f"🐍 Small-job Python: {python_exe}")
    print(f"☁️ Heavy-task executor policy: {HEAVY_TASK_EXECUTOR}")
    print(f"📊 Workload policy: {WORKLOAD_POLICY} | colab_order={COLAB_ORDER} | rtx_order={RTX_ORDER}")
        
    subprocess.Popen([python_exe, "dashboard_api.py"], env=launch_env)
    
    # 3. Launch Continuous Training Loop (Aegis v9 Upgrade)
    print("🏋️ Launching Training Loop (Hardware-Locked to RTX 3050)...")
    subprocess.Popen([python_exe, "continuous_training_loop.py"], env=launch_env)
    
    # 4. Wait for stability
    time.sleep(5)
    
    # 5. Launch Swarm Orchestrator
    print("🌪️ Launching Sentinel Swarm (Orchestrator V2)...")
    subprocess.run([python_exe, "system_orchestrator_v2.py"], env=launch_env)

if __name__ == "__main__":
    golden_restart()
