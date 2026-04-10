import logging
from typing import Dict, Any
from agents.base import BaseAgent
from core.agent_bus import bus
from offline_tts_manager import OfflineTTSManager

logger = logging.getLogger("edge_sentinel.voice_ui")

class VoiceUIAgent(BaseAgent):
    """
    Agent 32 — Voice UI (Persona 4)
    Handles safety announcements, hazard warnings, and SOS countdown alerts.
    Supports offline-first low-latency TTS via pyttsx3.
    """
    def __init__(self):
        super().__init__("Agent32-VoiceUI", sleep_interval=120) # Low activity loop, mostly event-driven
        self.tts = OfflineTTSManager()
        
        # Subscribe to voice alert requests from other agents (e.g., RoadSoSAgent)
        bus.subscribe("VOICE_ALERT_REQUEST", self.handle_voice_request)
        logger.info(f"[{self.name}] Persona 4 Online — Listening for hazard alerts.")

    async def iteration(self):
        # The agent is mostly event-driven via the bus, but we can do a periodic health check
        pass

    def handle_voice_request(self, payload: Dict[str, Any]):
        text = payload.get("text", "")
        priority = payload.get("priority", "NORMAL")
        is_critical = (priority == "IMMEDIATE")
        
        if text:
            logger.info(f"[{self.name}] Speaking ({priority}): {text}")
            self.tts.announce_hazard(text, critical=is_critical)

    async def generate_response(self, question: str) -> str:
        return (
            f"I am Agent 32 — Voice UI. I manage the Edge-Sentinel's auditory interface. "
            f"Current status: READY. My primary objective is to keep the driver informed via "
            f"low-latency voice safety alerts, including SOS protocols and hazard warnings."
        )

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    agent = VoiceUIAgent()
    
    # Test alert
    bus.emit("VOICE_ALERT_REQUEST", {"text": "System check complete. Voice UI is operational.", "priority": "NORMAL"})
    
    loop = asyncio.get_event_loop()
    loop.run_forever()
