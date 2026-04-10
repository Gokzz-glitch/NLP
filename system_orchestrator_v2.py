"""
System Orchestrator V2 — SmartSalai Edge-Sentinel
Runs all 14 agents concurrently on the asyncio event loop.
"""
import asyncio
import logging
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

# ── Apply RTX 3050 GPU-first config BEFORE any agent/torch imports ──
os.environ["SMARTSALAI_MOCK_GPU"] = "0" # Disable simulation mode
from core.gpu_config import apply as apply_gpu_config
GPU_DEVICE = apply_gpu_config()

# ── Aegis v3: Environment Hardening ──
if sys.prefix == sys.base_prefix:
    print("⚠️ WARNING: Running on System Python (CPU-Only). Swarm needs .venv for GPU/RTX 3050.")
    # We proceed but with a loud warning for the user to fix Windows Graphic Settings.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Orchestrator")
logger.info(f"Targeting Device: {GPU_DEVICE} (Forcing GPU 1 / Index 0)")

from agents.system_agents import (
    get_agents,
    ContextCuratorAgent,
    CoordinationPlannerAgent,
)
from agents.gpu_thermal_agent import GPUThermalAgent
from agents.sentinel_agent import SentinelGuardian
from agents.storage_agent import StorageSentinelAgent
from agents.ble_mesh_broker import BLEMeshBroker
from agents.irad_reporter_agent import IRADReporterAgent
from agents.firebase_bridge_agent import FirebaseBridgeAgent
from agents.hardware_sentinel_agent import HardwareSentinelAgent
from agents.voice_ui_agent import VoiceUIAgent
from core.knowledge_ledger import ledger


class MasterOrchestrator:
    def __init__(self):
        self.agents = get_agents()
        
        # High-Priority EMERGENCY Agents (Must always run)
        self.emergency_agents = [
            GPUThermalAgent(),
            SentinelGuardian(),
            HardwareSentinelAgent()
        ]
        
        # Supporting Agents (Lite/Swarm)
        self.lite_agents = [
            StorageSentinelAgent(),
            BLEMeshBroker(),
            FirebaseBridgeAgent(),
            IRADReporterAgent(),
            ContextCuratorAgent(),
            CoordinationPlannerAgent(),
            VoiceUIAgent() # Integrated into swarm
        ]
        # Add all get_agents() results to lite_agents for consolidation
        self.lite_agents.extend(self.agents)

        self.report_dir = Path("logs/reports")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.degraded_mode = False

    async def _supervised_run(self, agent):
        """Infinite-Uptime Wrapper [CWE-662]"""
        backoff = 2
        while True:
            try:
                await agent.run()
            except asyncio.CancelledError:
                logger.info(f"[{agent.name}] Canceled.")
                break
            except Exception as e:
                logger.error(f"[{agent.name}] CRASHED! Restarting in {backoff}s... Error: {e}")
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2) # Exponential backoff up to 1m

    async def report_generator(self):
        while True:
            await asyncio.sleep(120)
            logger.info("Generating Unified Report…")
            
            # [REMEDIATION #39]: Non-blocking DB query
            findings = await asyncio.to_thread(ledger.get_findings, limit=100)

            report = {
                "timestamp":      datetime.now().isoformat(),
                "total_findings": len(findings),
                "hardware_status": {},
                "insights":        [],
                "conversation":    [],
            }

            for f in findings:
                if f["agent_name"] == "Agent7-GPUThermal":
                    report["hardware_status"]["latest_event"] = f
                elif f["finding_type"] in ("broadcast_question", "broadcast_response"):
                    report["conversation"].append(f)
                else:
                    report["insights"].append(f)


            report_file = self.report_dir / f"unified_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            # [REMEDIATION #26]: Atomic write via temporary file [CWE-367]
            # Prevents zero-byte files if system loses power during JSON dump
            import tempfile
            def atomic_report_write():
                with tempfile.NamedTemporaryFile("w", dir=self.report_dir, delete=False, suffix=".json") as tf:
                    json.dump(report, tf, indent=4)
                    temp_name = tf.name
                # OS-level atomic rename/replace
                os.replace(temp_name, report_file)
                    
            await asyncio.to_thread(atomic_report_write)
            logger.info(f"Report saved → {report_file}")

    async def run(self):
        import psutil
        try:
            import GPUtil
            HAS_GPUTIL = True
        except ImportError:
            HAS_GPUTIL = False

        logger.info(f"Starting Consolidated Orchestrator with {len(self.emergency_agents) + len(self.lite_agents)} agents…")
        
        # Launch Emergency tasks (Independent)
        self.emergency_tasks = [asyncio.create_task(self._supervised_run(a)) for a in self.emergency_agents]
        
        # Launch Lite tasks
        self.lite_tasks = [asyncio.create_task(self._supervised_run(a)) for a in self.lite_agents]
        
        # Admin tasks
        admin_tasks = [asyncio.create_task(self.report_generator())]
        
        loop_counter = 0
        while True:
            # [REMEDIATION #17]: AEGIS Resource Governor (v2.1)
            # Only check hardware every 4 cycles (20s) to save CPU
            if loop_counter % 4 == 0:
                ram_pct = psutil.virtual_memory().percent
                gpu_util = 0
                if HAS_GPUTIL:
                    try:
                        gpus = GPUtil.getGPUs()
                        if gpus:
                            # Monitor RTX 3050 (usually index 0 or 1, matching our config)
                            gpu_util = gpus[0].load * 100
                    except: pass

                # Throttling Logic
                critical_ram = ram_pct > 92
                critical_gpu = gpu_util > 75 # Don't starve vision with research
                
                if (critical_ram or critical_gpu) and not self.degraded_mode:
                    reason = "RAM" if critical_ram else "GPU"
                    logger.error(f"🚨 RESOURCE CRITICAL ({reason}). Activating Aegis Throttling: Pausing {len(self.lite_tasks)} agents.")
                    for t in self.lite_tasks: t.cancel()
                    self.degraded_mode = True
                    ledger.log_finding("MasterOrchestrator", "resource_degradation", {
                        "ram_pct": ram_pct, "gpu_util": gpu_util, "mode": "DEGRADED", "action": "PAUSE_LITE_SWARM"
                    })
                elif not (critical_ram or critical_gpu) and self.degraded_mode:
                    # Hysteresis: only restore if well below limit
                    if ram_pct < 80 and gpu_util < 50:
                        logger.info(f"🟢 Resource Normal (RAM:{ram_pct}% GPU:{gpu_util}%). Restoring full swarm.")
                        self.lite_tasks = [asyncio.create_task(self._supervised_run(a)) for a in self.lite_agents]
                        self.degraded_mode = False
            
            await asyncio.sleep(5)
            loop_counter += 1
            # Break check: if emergency tasks all die
            if all(t.done() for t in self.emergency_tasks):
                break

    async def shutdown(self):
        """Cancels all tasks and ensures ledger/reports are saved."""
        logger.info("Stopping all agents and saving final states…")
        all_tasks = self.emergency_tasks + (self.lite_tasks if not self.degraded_mode else [])
        for task in all_tasks:
            task.cancel()
        
        await asyncio.gather(*all_tasks, return_exceptions=True)
        
        try:
            ledger.close()
            logger.info("Knowledge Ledger closed cleanly.")
        except: pass
        logger.info("Graceful shutdown complete.")
        
        logger.info("Graceful shutdown complete.")


if __name__ == "__main__":
    try:
        orchestrator = MasterOrchestrator()
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        # Handled by asyncio.run() throwing CancelledError into run()
        pass
    except Exception as e:
        logger.error(f"Fatal Orchestrator error: {e}")
        sys.exit(1)
