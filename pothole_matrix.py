# [PERSONA 3: THE EDGE-VISION & KINETIC ENGINEER]
# ALGORITHM_NODE: IMU_VISION_POTHOLE_MATRIX
# logic: Dual-Verification Pipeline to eliminate false-positives (road noise vs physical crater)

"""
IMU_VISION_POTHOLE_MATRIX Logic:

1. KINETIC TRIGGER (IMU Z-Axis): 
   - Monitor Linear Acceleration Z-axis at 100Hz.
   - Define TRIGGER_THRESHOLD = 1.5G deviation from baseline (9.81 m/s^2).
   - If deviation > TRIGGER_THRESHOLD: Set KINETIC_INTERRUPT = True

2. BUFFER LOOKBACK (Vision):
   - Maintain 10-frame Ring Buffer of last processed CV frames (indian_potholes_yolov8n.onnx).
   - If KINETIC_INTERRUPT:
     - Halt new frame ingestion.
     - Scan N-10 to N buffer for entity_class 'pothole' with confidence > 0.65.
     
3. DECISION MATRIX:
   - IF (KINETIC_INTERRUPT == True) AND (VISION_VERIFICATION == True):
     - Log to spatial_ground_truth.db
     - Execute BLE_SWARM_BROADCAST
     - Trigger Persona 4 TTS: "Macha, severe pothole 50m ahead"
   - ELSE:
     - Discard as transient road vibration or ghost detection.
"""

import numpy as np
from collections import deque

class PotholeVerificationMatrix:
    def __init__(self, z_threshold=14.7, vision_conf_threshold=0.65):
        self.z_threshold = z_threshold # ~1.5G
        self.vision_conf_threshold = vision_conf_threshold
        self.cv_ring_buffer = [] # Holds last 10 detections: [{'class': 'pothole', 'conf': 0.8}, ...]
        self.imu_baseline_buffer = deque(maxlen=50) # Authentic Rolling Calibration

    def process_frame(self, imu_z_val, vision_detections):
        """
        imu_z_val: current instantaneous Z-axis acceleration (m/s^2)
        vision_detections: list of dictionaries from YOLOv8n-pothole
        """
        # Update Ring Buffer
        self.cv_ring_buffer.append(vision_detections)
        if len(self.cv_ring_buffer) > 10:
            self.cv_ring_buffer.pop(0)
            
        # Authentic Dynamic Calibration: Rolling Average Base Computation
        self.imu_baseline_buffer.append(imu_z_val)
        dynamic_baseline = np.mean(self.imu_baseline_buffer) if len(self.imu_baseline_buffer) >= 10 else imu_z_val
        
        # Kinetic Check against dynamic topology
        kinetic_interrupt = abs(imu_z_val - dynamic_baseline) > self.z_threshold
        
        if kinetic_interrupt:
            print("PERSONA_3_REPORT: KINETIC_INTERRUPT_DETECTED. SCANNING_CV_BUFFER.")
            # Vision Verification Lookback
            is_verified = False
            for detections in self.cv_ring_buffer:
                for obj in detections:
                    if obj['class'] == 'pothole' and obj['conf'] >= self.vision_conf_threshold:
                        is_verified = True
                        break
            
            if is_verified:
                print("PERSONA_3_REPORT: POTHOLE_VERIFIED. TRIGGERING_SWARM_STATE.")
                return True # Signal for broadcast/log
        
        return False

# PSEUDOCODE_COMPLETED_NODE_03
