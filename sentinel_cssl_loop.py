import time
import os
import json
import sys
from scripts.batch_processor import BatchVideoProcessor
from scripts.audit_with_gemini import AIAuditor

# Configuration
SOURCE_LIST = "video_sources.txt"
HISTORY_FILE = "raw_data/cssl_history.json"
COOLDOWN_SECONDS = 300 # 5-minute breather between clips

class ContinuousSentinelLoop:
    def __init__(self):
        self.processor = BatchVideoProcessor()
        self.auditor = AIAuditor()
        self.history = self._load_history()
        
        if not os.path.exists(SOURCE_LIST):
            with open(SOURCE_LIST, 'w') as f:
                f.write("# Add YouTube URLs here, one per line\n")
        
    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        return {"processed_urls": []}

    def _save_history(self):
        with open(HISTORY_FILE, 'w') as f:
            json.dump(self.history, f, indent=4)

    def run_infinite(self):
        print("🌀 SENTINEL CONTINUOUS EVOLUTION (CSSL) DEPLOYED.")
        print("🚀 MISSION: Self-Upgrade the Vision Brain indefinitely.")
        
        while True:
            # 1. Fetch Fresh URL
            with open(SOURCE_LIST, 'r') as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            
            target_url = None
            for url in urls:
                if url not in self.history["processed_urls"]:
                    target_url = url
                    break
            
            if not target_url:
                print("💤 NO NEW CLIPS in source list. Waiting for Research Team (User) to add links...")
                time.sleep(300)
                continue

            print(f"\n🧠 DIGESTING NEW CLIP: {target_url}")
            
            # 2. Ingest & Detect (YOLO Student)
            video_path = self.processor.download_video(target_url)
            if video_path:
                self.processor.process_video(video_path)
                
                # 3. Audit (Gemini Multi-Agent Swarm)
                print("🔬 LAUNCHING MULTI-AGENT TEACHER AUDIT...")
                self.auditor.run_audit(limit=100) # Process up to 100 candidates from this clip
                
                # 4. Cleanup (Safety & Space)
                print(f"🧹 RECYCLING RAW DATA: Deleting {video_path}")
                try:
                    os.remove(video_path)
                except Exception as e:
                    print(f"⚠️ Cleanup failed: {e}")
                    
                # 5. Mark as Digested
                self.history["processed_urls"].append(target_url)
                self._save_history()
                
                print("✅ CLIP FULLY DIGESTED. Intelligence Synced.")
                print(f"⏳ COOLDOWN: Resuming in {COOLDOWN_SECONDS}s to protect API Quotas...")
                time.sleep(COOLDOWN_SECONDS)
            else:
                print(f"⚠️ FAILED to digest {target_url}. Moving next.")
                self.history["processed_urls"].append(target_url)
                self._save_history()

if __name__ == "__main__":
    loop = ContinuousSentinelLoop()
    loop.run_infinite()
