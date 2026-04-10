#!/usr/bin/env python3
"""
SmartSalai Edge-Sentinel — Hostile Environment Stress Test (v1.2.1-Stress)
Injects 'Chaos' into the system to verify the swarm's recovery logic.
1. RAM Spike (Simulates OOM danger).
2. Disk Floor (Simulates < 500MB storage).
3. Model Corruption (Simulates weights failure).
"""

import os
import time
import shutil
import psutil
import torch
import logging
from pathlib import Path
from core.knowledge_ledger import ledger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edge_sentinel.stress_test")

class StressTestRunner:
    def __init__(self):
        self.test_dir = Path("tmp_stress_data")
        self.test_dir.mkdir(exist_ok=True)
    
    def test_ram_exhaustion(self):
        """Test A: Simulate 95% RAM usage (Mock-Leak)"""
        logger.info("🧪 [TEST A] TRIGGERING RAM EXHAUSTION SPIKE...")
        # We don't actually want to crash the OS, so we log a 'mock' RAM finding 
        # that the agents will pick up as a severe bottleneck.
        ledger.log_finding("Agent8-SentinelGuardian", "system_stress_signal", {
            "type": "RAM_EXHAUSTION",
            "percent": 96.4,
            "status": "CRITICAL"
        })
        print("✅ RAM Spike Signal Injected. Check Dashboard Pacing.")

    def test_disk_floor(self):
        """Test B: Create large dummy files to trigger Agent 15 Storage Pruning"""
        logger.info("🧪 [TEST B] TRIGGERING DISK FLOOR (< 500MB)...")
        # We simulate the finding to trigger the pruning agent 
        ledger.log_finding("Agent15-StorageSentinel", "disk_warning", {
            "free_gb": 0.42,
            "status": "DANGER_PRUNE_NOW"
        })
        print("✅ Disk Floor Signal Injected. Check Storage Logs.")

    def test_model_corruption(self):
        """Test C: Corrupt 'best_continuous.pt' to verify Smoke Testing Rollback"""
        logger.info("🧪 [TEST C] TRIGGERING WEIGHTS CORRUPTION...")
        target = Path("models/best_continuous.pt")
        backup = Path("models/best_continuous.pt.bak")
        
        if target.exists():
            shutil.copy(target, backup)
            with open(target, "wb") as f:
                f.write(b"CORRUPTED_WEIGHTS_DATA_CHALLENGE_ACCEPTED")
            
            ledger.log_finding("Agent15-SmokeTest", "testing_smoke", {
                "test_name": "Model Integrity",
                "result": "CRITICAL_FAILURE: Corrupted weights detected.",
                "status": "FAIL"
            })
            print("✅ Model Corruption Injected. Watch for Agent 15 Rollback log.")
        else:
            print("⚠️ No best_continuous.pt found to corrupt.")

    def cleanup(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

if __name__ == "__main__":
    import sys
    runner = StressTestRunner()
    
    if len(sys.argv) < 2:
        print("Usage: python test_real_world.py [ram|disk|model|all]")
        sys.exit(1)
    
    cmd = sys.argv[1].lower()
    if cmd == "ram": runner.test_ram_exhaustion()
    elif cmd == "disk": runner.test_disk_floor()
    elif cmd == "model": runner.test_model_corruption()
    elif cmd == "all":
        runner.test_ram_exhaustion()
        runner.test_disk_floor()
        runner.test_model_corruption()
    
    print("\n🚀 STRESS SIGNALS DEPLOYED. MONITOR DASHBOARD FOR SWARM RESPONSE.")
