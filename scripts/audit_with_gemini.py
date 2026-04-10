import os
import sys
# Inject root project directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import cv2
import google.generativeai as genai
from PIL import Image
import io
import time
import threading
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import requests
import base64

from core.unified_ai import UnifiedAI

# Global Locks
print_lock = threading.Lock()
dataset_lock = threading.Lock()

class AIAuditor:
    def __init__(self, manifest_path="Testing videos/process_manifest.json", dataset_dir="datasets/ssl_v1"):
        self.manifest_path = manifest_path
        self.dataset_dir = dataset_dir
        self.images_dir = os.path.join(dataset_dir, "images")
        self.labels_dir = os.path.join(dataset_dir, "labels")
        
        for d in [self.images_dir, self.labels_dir]:
            if not os.path.exists(d): os.makedirs(d)
        
        # Initialize Unified AI Engine
        self.ai = UnifiedAI()

    def _worker(self, candidate_batch, key_idx):
        prompt = """
        You are a high-fidelity Road Safety Auditor. 
        Identify if there is a 'pothole', 'accident', or 'major debris' in this road scene.
        Respond ONLY with a JSON object: {"hazard_confirmed": true/false, "hazard_type": "...", "bounding_box": [ymin, xmin, ymax, xmax]}
        """

        for cand in candidate_batch:
            video_path = cand["video_path"]
            frame_idx = cand["frame_idx"]
            video_id = os.path.basename(video_path).split('.')[0]
            base_name = f"{video_id}_{frame_idx}"
            
            label_path = os.path.join(self.labels_dir, f"{base_name}.txt")
            if os.path.exists(label_path): continue

            # Extract
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            cap.release()
            if not ret: continue

            # Attempt detection using Unified AI Engine (handles failover/rotation automatically)
            try:
                result = self.ai.generate_vision_completion(prompt, frame)
                
                if isinstance(result, dict) and result.get("hazard_confirmed"):
                    with dataset_lock:
                        cv2.imwrite(os.path.join(self.images_dir, f"{base_name}.jpg"), frame)
                        
                        ymin, xmin, ymax, xmax = result["bounding_box"]
                        class_map = {"pothole": 0, "accident": 1, "debris": 2}
                        cls_id = class_map.get(result["hazard_type"], 0)
                        dw, dh = 1./1000., 1./1000.
                        x = (xmin + xmax) / 2.0 * dw
                        y = (ymin + ymax) / 2.0 * dh
                        w = (xmax - xmin) * dw
                        h = (ymax - ymin) * dh
                        with open(label_path, 'w') as f:
                            f.write(f"{cls_id} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n")
                    
                    with print_lock: 
                        print(f"✅ AGENT {key_idx + 1}: Confirmed {base_name}")
                elif not isinstance(result, dict):
                    with print_lock:
                        print(f"⚠️ AGENT {key_idx + 1}: Non-JSON response received from AI engine.")
            except Exception as e:
                with print_lock: 
                    print(f"❌ AGENT {key_idx + 1}: Failure on {base_name}: {e}")
            
            time.sleep(1.0)

    def run_audit(self, limit=100):
        with open(self.manifest_path, 'r') as f:
            manifest = json.load(f)
        
        all_candidates = []
        for vp, data in manifest["videos"].items():
            for c in data.get("candidates", []):
                c["video_path"] = vp
                all_candidates.append(c)
        
        all_candidates = all_candidates[:limit]
        num_agents = len(self.api_keys)
        batch_size = (len(all_candidates) // num_agents) + 1
        batches = [all_candidates[i:i + batch_size] for i in range(0, len(all_candidates), batch_size)]
        
        print(f"🚀 SWARM AUDIT START: {len(all_candidates)} targets via {num_agents} Agents.")
        with ThreadPoolExecutor(max_workers=num_agents) as executor:
            for i in range(num_agents):
                if i < len(batches):
                    executor.submit(self._worker, batches[i], i)

if __name__ == "__main__":
    auditor = AIAuditor()
    auditor.run_audit(limit=100)
