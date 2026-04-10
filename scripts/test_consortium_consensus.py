#!/usr/bin/env python3
import sys
import os
import json
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.learner_agent import SelfSupervisedLearner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_consortium")

def test_consortium():
    """Verify that the Hive-Mind consensus can reach a decision."""
    logger.info("🧪 Starting Consortium Consensus Test...")
    
    learner = SelfSupervisedLearner()
    
    # Mock IMU metadata for a potential pothole
    mock_imu = {
        "accel": {"x": 0.1, "y": 0.2, "z": 2.8},
        "speed_kmh": 45.0,
        "location": "test_coords"
    }
    
    # We use a dummy frame path (it shouldn't be read for consortium text-only synthesis, 
    # but the method requires it)
    dummy_frame = "raw_data/self_labeled/test_frame.jpg"
    
    logger.info("📡 Requesting consensus from GODMOD3 Consortium (Strictly FREE-tier)...")
    result = learner._consortium_verify(dummy_frame, mock_imu, use_free_tier=True)
    
    if result:
        logger.info("✅ CONSENSUS REACHED!")
        print(json.dumps(result, indent=2))
        
        if result.get("hazard_confirmed"):
            logger.info("🎯 Decision: HAZARD CONFIRMED")
        else:
            logger.info("🛡️ Decision: NO HAZARD")
    else:
        logger.error("❌ Consensus failed. Check if GODMOD3 API is running at http://127.0.0.1:7860")

if __name__ == "__main__":
    test_consortium()
