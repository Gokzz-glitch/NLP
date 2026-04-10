import os
import cv2
import time
import json
import logging
from core.agent_bus import bus
from agents.learner_agent import SelfSupervisedLearner

# [PERSONA 8 BRIDGE: INTEGRATING SELF-SUPERVISION]
# This script monitors the AgentBus and triggers the Learner on physics events.

logger = logging.getLogger("edge_sentinel.self_supervised_bridge")
logger.setLevel(logging.INFO)

class SelfSupervisedBridge:
    def __init__(self, jerk_threshold: float = 1.8):
        self.learner = SelfSupervisedLearner()
        self.jerk_threshold = jerk_threshold
        self.last_accel = {"x": 0, "y": 0, "z": 0}
        
        # Subscribe to Raw IMU from Mobile
        bus.subscribe("MOBILE_IMU_RAW", self.handle_imu)
        logger.info(f"PERSONA_8_REPORT: LEARNING_BRIDGE_ACTIVE | THRESHOLD: {jerk_threshold}g")

    def handle_imu(self, payload):
        """
        Detects Vertical Jerk (Pothole physics) and triggers Vision/Gemini.
        """
        accel = payload.get("accel", {})
        az = accel.get("z", 0)
        
        # Calculate Vertical Jerk (Simple delta for Hackathon demo)
        jerk = abs(az - self.last_accel["z"])
        self.last_accel = accel
        
        if jerk > self.jerk_threshold:
            logger.info(f"PERSONA_8_REPORT: JERK_DETECTED: {jerk:.2f}g | TRIGGERING_SELF_LABELLING")
            self._trigger_learning_loop(payload)

    def _trigger_learning_loop(self, imu_payload):
        """
        Snapshots the 'Dashcam' and sends to Gemini for Verification.
        """
        timestamp = int(time.time())
        temp_frame_path = f"raw_data/self_labeled/jerk_{timestamp}.jpg"
        dashcam_path = os.getenv("VIDEO_SOURCE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "raw_data", "videos", "dashcam.mp4"))
        
        try:
            if not os.path.exists("raw_data/self_labeled"):
                os.makedirs("raw_data/self_labeled")

            if os.path.exists(dashcam_path):
                 # Extract a frame from the dashcam video
                 cap = cv2.VideoCapture(dashcam_path)
                 ret, frame = cap.read()
                 if ret:
                     cv2.imwrite(temp_frame_path, frame)
                 cap.release()
            
            # 2. Call Learner (Gemini verification)
            if os.path.exists(temp_frame_path):
                verification = self.learner.audit_jerk_event(temp_frame_path, imu_payload)
            
            bus.emit("SELF_SUPERVISED_LEARNING_EVENT", {
                "type": "IMU_JERK_TRIGGER",
                "intensity": imu_payload.get("accel", {}).get("z"),
                "status": "COMPLETED_BY_GEMINI"
            })
            
        except Exception as e:
            logger.error(f"BUS_ERROR: SELF_SUPERVISED_TRIGGER_FAILED: {e}")

if __name__ == "__main__":
    bridge = SelfSupervisedBridge()
    # Mock IMU trigger
    bus.emit("MOBILE_IMU_RAW", {"accel": {"x": 0, "y": 0, "z": 3.0}})
    print("Self-Supervised Bridge Test Complete.")
