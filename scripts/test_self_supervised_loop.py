import os
import cv2
import json
import logging
from pathlib import Path
from agents.learner_agent import SelfSupervisedLearner
from core.agent_bus import bus

# [PERSONA 8 INTEGRATION TEST - NO EMOJI EDITION]
# Force-triggers a self-supervised learning event from a real dashcam frame.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edge_sentinel.test")

def test_self_supervised_loop():
    print("=========================================================")
    print(" EDGE-SENTINEL: SELF-SUPERVISED INTEGRATION TEST ")
    print("=========================================================")
    
    # 1. Initialize Learner
    learner = SelfSupervisedLearner()
    
    # 2. Extract a frame from the dashcam video
    dashcam_path = Path("Testing videos/dashcam.mp4")
    if not dashcam_path.exists():
        print(f"Error: Dashcam video {dashcam_path} NOT found.")
        return
        
    cap = cv2.VideoCapture(str(dashcam_path))
    ret, frame = cap.read()
    if not ret:
        print("Error: Failed to read frame from dashcam.")
        cap.release()
        return
    cap.release()
    
    # 3. Save as a temporary jerk event frame
    Path("raw_data/self_labeled").mkdir(parents=True, exist_ok=True)
    test_frame_path = "raw_data/self_labeled/integration_test_jerk.jpg"
    cv2.imwrite(test_frame_path, frame)
    print(f"Success: Captured dashcam frame to: {test_frame_path}")
    
    # 4. Trigger Gemini Teacher Verification
    print("Directing Gemini Teacher (1.5 Flash) for multimodal verification...")
    imu_metadata = {"accel": {"z": 2.45}, "timestamp": 1775040814} # Simulated High-G
    
    verification = learner.audit_jerk_event(test_frame_path, imu_metadata)
    
    if verification:
        print("\nSELF-SUPERVISED RESPONSE RECEIVED:")
        print(json.dumps(verification, indent=2))
        print(f"\nSuccess: Logic Verified.")
    else:
        print("Error: Gemini Verification FAILED.")

if __name__ == "__main__":
    test_self_supervised_loop()
