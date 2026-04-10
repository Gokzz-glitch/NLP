import os
import time
import logging
from typing import Dict, Any
from agents.base import BaseAgent
from core.knowledge_ledger import ledger
from core.secret_manager import get_manager

logger = logging.getLogger("edge_sentinel.active_learning")

class ActiveLearningAgent(BaseAgent):
    """
    Agent 31 — Active Learning (Roboflow Bridge)
    Monitors hazard detections, identifies "Uncertain" cases (Conf < 0.6),
    and auto-uploads them to Roboflow for manual re-labeling. 
    Implements daily quota throttling (Max 5 images/day) to conserve bandwidth.
    """
    
    UNCERTAINTY_THRESHOLD = 0.6
    DAILY_QUOTA = 5
    
    def __init__(self):
        super().__init__("Agent31-ActiveLearning", sleep_interval=300) # Check every 5 mins
        self.workspace_id = "viren-daultani-y0fio"
        self.project_id   = "road-signs-indian-p2kgu"
        self._uploads_today = 0
        self._last_reset_day = time.strftime("%Y-%m-%d")

    def _reset_quota_if_needed(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._last_reset_day:
            self._last_reset_day = today
            self._uploads_today = 0
            logger.info(f"[{self.name}] Daily upload quota reset.")

    async def iteration(self):
        self._reset_quota_if_needed()
        
        if self._uploads_today >= self.DAILY_QUOTA:
            logger.info(f"[{self.name}] Daily upload quota ({self.DAILY_QUOTA}) reached. Sleeping.")
            return

        # 1. Fetch potential Active Learning candidates from the ledger
        # Looking for 'road_hazard' finding types with low confidence
        # Note: We filter for findings that haven't been uploaded yet
        candidates = ledger.get_findings(finding_type="road_hazard", limit=10)
        
        for cand in candidates:
            if self._uploads_today >= self.DAILY_QUOTA: break
            
            content = cand.get("content", {})
            conf = content.get("confidence", 1.0)
            img_path = content.get("image_path")
            
            # Already uploaded or high confidence? Skip.
            if content.get("uploaded_to_roboflow") or conf > self.UNCERTAINTY_THRESHOLD:
                continue
                
            if img_path and os.path.exists(img_path):
                success = await self._upload_to_roboflow(img_path, content)
                if success:
                    self._uploads_today += 1
                    # Mark as uploaded in the ledger content
                    content["uploaded_to_roboflow"] = True
                    ledger.log_finding(self.name, "active_learning_sync", {
                        "image": os.path.basename(img_path),
                        "conf": conf,
                        "status": "UPLOADED",
                        "project": self.project_id
                    })
            else:
                logger.warning(f"[{self.name}] Candidate image missing or invalid: {img_path}")

    async def _upload_to_roboflow(self, image_path: str, metadata: Dict) -> bool:
        """Performs the actual SDK upload using SecretManager."""
        try:
            from roboflow import Roboflow
            
            sm = get_manager(strict_mode=False)
            api_key = sm.get("ROBOFLOW_API_KEY")
            if not api_key:
                logger.error(f"[{self.name}] ROBOFLOW_API_KEY not found in environment. Set ROBOFLOW_API_KEY to enable uploads.")
                return False

            rf = Roboflow(api_key=api_key)
            project = rf.workspace(self.workspace_id).project(self.project_id)
            
            logger.info(f"[{self.name}] Uploading uncertain frame ({metadata.get('confidence')}): {image_path}")
            
            # SDK Upload
            project.upload(
                image_path=image_path,
                tag="edge_sentinel_uncertainty"
            )
            return True
        except ImportError:
            logger.error(f"[{self.name}] 'roboflow' library not found. Skipping upload.")
            return False
        except Exception as e:
            logger.error(f"[{self.name}] Roboflow upload failed: {e}")
            return False

    async def generate_response(self, question: str) -> str:
        return (
            f"I am Agent 31 — Active Learning. I bridge the gap between edge inference and cloud refinement. "
            f"Uploads today: {self._uploads_today}/{self.DAILY_QUOTA}. "
            f"Currently monitoring detections below {self.UNCERTAINTY_THRESHOLD*100}% confidence "
            f"for auto-sync to Roboflow project '{self.project_id}'."
        )

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    agent = ActiveLearningAgent()
    # Mock some data for testing
    ledger.log_finding("Agent28-RoadWatch", "road_hazard", {
        "image_path": "data/mock_fuzzy_pothole.jpg", # Needs to exist
        "confidence": 0.45,
        "class": "pothole"
    })
    loop = asyncio.get_event_loop()
    loop.run_until_complete(agent.iteration())
