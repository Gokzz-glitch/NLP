import logging
import psutil
from typing import Dict, Any
from agents.base import BaseAgent
from core.agent_bus import bus

logger = logging.getLogger("edge_sentinel.hardware_sentinel")

class HardwareSentinelAgent(BaseAgent):
    """
    Agent 33 — Hardware Sentinel
    Monitors physical system constraints (Battery, AC Power, Disk Space).
    Policy: High-intensity vision training (Agent 7) MUST be suspended 
    when the device is running on battery to preserve life-safety cycles.
    """
    
    def __init__(self):
        super().__init__("Agent33-HardwareSentinel", sleep_interval=60) # Check power every minute
        self._on_battery = False
        self._last_battery_pct = 100

    async def iteration(self):
        battery = psutil.sensors_battery()
        if not battery:
            logger.info(f"[{self.name}] No battery detected (Desktop/Server mode). AC Power assumed.")
            return

        is_plugged = battery.power_plugged
        pct = battery.percent
        self._last_battery_pct = pct

        # 1. Logic for Power Transition
        if not is_plugged and not self._on_battery:
            # Transition to Battery
            self._on_battery = True
            logger.warning(f"[{self.name}] !!! AC POWER DISCONNECTED !!! Battery at {pct}%. Suspending heavy AI tasks.")
            bus.emit("SYSTEM_LOW_POWER_SUSPEND", {
                "source": self.name,
                "battery_pct": pct,
                "reason": "AC_DISCONNECTED"
            })
            
        elif is_plugged and self._on_battery:
            # Transition to AC
            self._on_battery = False
            logger.info(f"[{self.name}] AC Power Restored. Resuming pending AI tasks.")
            bus.emit("SYSTEM_POWER_RESTORED", {
                "source": self.name,
                "battery_pct": pct
            })

        # 2. Logic for Critical Low Battery (<20%)
        if not is_plugged and pct < 20:
            logger.critical(f"[{self.name}] CRITICAL BATTERY: {pct}%. Emergency notification requested.")
            bus.emit("VOICE_ALERT_REQUEST", {
                "text": f"Warning: Critical Battery at {pct} percent. Please connect charger to maintain Road Safety Sentinel.",
                "priority": "IMMEDIATE"
            })

    async def generate_response(self, question: str) -> str:
        status = "ON_BATTERY" if self._on_battery else "AC_POWER"
        return (
            f"I am Agent 33 — Hardware Sentinel. Current status: {status} ({self._last_battery_pct}%). "
            f"I ensure the Edge-Sentinel system respects physical limits by throttling "
            f"non-essential AI training to prioritize safety during low-power states."
        )

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    agent = HardwareSentinelAgent()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(agent.iteration())
