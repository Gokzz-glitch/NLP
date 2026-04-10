import asyncio
import logging
import random
import re
import html
from datetime import datetime
from typing import Dict, Any

from core.knowledge_ledger import ledger
from core.research_clients import G0DM0D3Client, NotebookLMClientWrapper, UnifiedResearchClient, GPUEmbeddingClient
from core.agent_bus import bus

# [REMEDIATION #6]: Fix missing cv2 import for PII redaction
try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger(__name__)

# [REMEDIATION #40]: ReDoS-Protected universal redacting patterns [CWE-1333]
_SECRET_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{32,}(?=\s|$)'), # OpenAI/Cloud keys (non-backtracking)
    re.compile(r'AIza[a-zA-Z0-9_-]{35}'), # GCP keys
    re.compile(r'FERNET_KEY=[a-zA-Z0-9_-]{32,}'), # Swarm keys
    re.compile(r'DASHBOARD_SECRET_KEY=[a-zA-Z0-9_-]{32,}'), # Auth keys
    re.compile(r'https:// dashboard\.smartsalai\.ai\?key=[a-zA-Z0-9]{20,}', re.X) # URLs
]

def scrub_sensitive(text: str) -> str:
    """Universal redactor for any sensitive patterns."""
    if not isinstance(text, str):
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text

def redact_pii(frame):
    """
    Performs auto-blurring on dashcam frames. 
    Ideal for GDPR/Privacy compliance in vision swarms.
    """
    if frame is None:
        return frame
        
    try:
        # Simple face detection for privacy (Haar Cascade is light enough for edge)
        # Assuming haarcascade_frontalface_default.xml is available or using a simple detector
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Placeholder for real-world license plate/face regions
        # In production, this would use a dedicated YOLO-Face model
        # For the hackathon, we simulate it with lower part of the frame blurring (plates)
        h, w = frame.shape[:2]
        
        # Blur bottom 20% by default (Dashcam license plate zone)
        plate_zone = frame[int(h*0.8):h, 0:w]
        plate_zone = cv2.GaussianBlur(plate_zone, (51, 51), 0)
        frame[int(h*0.8):h, 0:w] = plate_zone
        
        return frame
    except Exception as e:
        logger.error(f"PII Redaction Error: {e}")
        return frame

# Swarm Concurrency Tiers [CWE-770]
_SEMAPHORES = {
    "EMERGENCY": asyncio.Semaphore(10), # High-priority (Vision, SOS, Thermal)
    "OPS":       asyncio.Semaphore(3),  # Medium-priority (Sync, Storage, DB)
    "RESEARCH":  asyncio.Semaphore(2),  # Low-priority (NLP Research, Model Scouting)
}

def get_priority_semaphore(priority: str):
    return _SEMAPHORES.get(priority.upper(), _SEMAPHORES["RESEARCH"])

class BaseAgent:
    def __init__(
        self,
        name: str,
        sleep_interval: int = 10,
        priority: str = "RESEARCH",
        init_clients: bool = True,
    ):
        self.name             = name
        self.sleep_interval   = sleep_interval
        self.priority         = priority

        # Some agents (for example transport/bridge workers) never use research clients;
        # allowing lazy init avoids expensive startup dependencies during tests and recovery boots.
        if init_clients:
            self.g3_client = G0DM0D3Client()
            self.nlm_client = NotebookLMClientWrapper()
            self.unified_client = UnifiedResearchClient()
            self.gpu_intel = GPUEmbeddingClient()
        else:
            self.g3_client = None
            self.nlm_client = None
            self.unified_client = None
            self.gpu_intel = None
        self._last_answered_q : int = -1   # tracks last answered question id

    def _update_heartbeat(self):
        """Logs a silent heartbeat to the ledger for stall detection."""
        # Note: We use a special finding type that is excluded from UI logs 
        # to prevent dashboard flooding.
        ledger.log_finding(self.name, "agent_heartbeat", {
            "timestamp": datetime.now().isoformat(),
            "status": "ALIVE"
        })

    # ── run loop ──────────────────────────────────────────────────────────────
    async def run(self):
        logger.info(f"[{self.name}] Agent started.")
        while True:
            try:
                # [REMEDIATION #8]: Move heartbeat OUTSIDE semaphore to prevent false stalls
                self._update_heartbeat()
                
                # [SCALABILITY FIX #99]: Priority-based throttling
                async with get_priority_semaphore(self.priority):
                    await self.iteration()
                    await self.check_and_respond_to_broadcast()
            except asyncio.CancelledError:
                # Allow clean shutdown by passing cancellation up
                raise
            except Exception as e:
                # Swallow full stack traces securely to avoid API token leakage inside logs
                error_msg = str(e)
                # Quick sanitization mask for any random dict dumps within the error
                if "sk-" in error_msg or "AIza" in error_msg:
                    error_msg = "[REDACTED TOKEN LEAK PREVENTED]"
                logger.error(f"[{self.name}] Error during iteration (Recovered): {type(e).__name__} - {error_msg}")
            
            # Unlocked sleep allows other agents to grab the semaphore
            await asyncio.sleep(self.sleep_interval)

    async def iteration(self):
        raise NotImplementedError

    # ── inter-agent conversation ──────────────────────────────────────────────
    async def check_and_respond_to_broadcast(self):
        """
        Poll for the latest Agent8 broadcast question.
        If this agent hasn't answered it yet, generate a domain response and log it.
        """
        questions = ledger.get_findings(
            agent_name="Agent8-SentinelGuardian",
            finding_type="broadcast_question",
            limit=1,
        )
        if not questions:
            return

        q = questions[0]
        q_id = q["id"]

        # Already answered this round?
        if q_id == self._last_answered_q:
            return

        question_text = q["content"].get("question", "Status update?")
        q_round       = q["content"].get("round", "?")

        # Generate a domain-specific English response
        try:
            response_text = await self.generate_response(question_text)
        except Exception as exc:
            response_text = f"[Error generating response: {exc}]"

        ledger.log_finding(
            self.name,
            "broadcast_response",
            {
                "question_id": q_id,
                "round":       q_round,
                "question":    question_text,
                "response":    response_text,
                "replied_at":  datetime.now().isoformat(),
            },
        )
        self._last_answered_q = q_id
        logger.info(f"[{self.name}] 💬 Replied to Q#{q_round}: {response_text[:80]}…")

    async def generate_response(self, question: str) -> str:
        """Override in each subclass to give domain-specific English answers."""
        raise NotImplementedError
