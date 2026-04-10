import os
import subprocess
import json
import time
import cv2
from ultralytics import YOLO
import sys
from core.model_registry import resolve_yolo_pothole_pt

class BatchVideoProcessor:
    def __init__(self, model_path=None, output_dir="Testing videos"):
        resolved_model = model_path or str(resolve_yolo_pothole_pt())
        self.model = YOLO(resolved_model)
        self.output_dir = output_dir
        self.manifest_path = os.path.join(output_dir, "process_manifest.json")
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
        self.manifest = self._load_manifest()

    def _load_manifest(self):
        if os.path.exists(self.manifest_path):
            with open(self.manifest_path, 'r') as f:
                return json.load(f)
        return {"videos": {}}

    def _save_manifest(self):
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=4)

    def download_video(self, url):
        """Downloads a YouTube video/short using yt-dlp."""
        print(f"📥 REQUESTED: {url}")
        
        # Use yt-dlp to get a unique ID/filename
        try:
            # We want high quality but manageable for inference
            cmd = [
                "yt-dlp",
                "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "--merge-output-format", "mp4",
                "-o", f"{self.output_dir}/%(id)s.%(ext)s",
                url
            ]
            subprocess.run(cmd, check=True)
            
            # Find the actual file starting with its ID
            import glob
            video_id = subprocess.check_output(["yt-dlp", "--get-id", url]).decode().strip()
            files = glob.glob(os.path.join(self.output_dir, f"{video_id}.*"))
            
            if files:
                video_path = files[0]
                print(f"✅ DOWNLOADED: {video_path}")
                return video_path
        except Exception as e:
            print(f"❌ FAILED DOWNLOAD: {url} | Error: {e}")
            return None

    def process_video(self, video_path):
        """Runs initial inference to find candidates for SSL."""
        if video_path in self.manifest["videos"] and self.manifest["videos"][video_path]["status"] == "PROCESSED":
            print(f"⏭️ SKIPPING (Already Processed): {video_path}")
            return

        print(f"🧠 INFERENCE: {video_path}")
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        candidates = []
        frame_idx = 0
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            # Sample at 1 FPS for efficiency and SSL diversity
            if frame_idx % int(max(1, fps)) == 0:
                results = self.model(frame, verbose=False)[0]
                
                # Identify high-confidence and low-confidence candidates
                for box in results.boxes:
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    
                    # Store candidate for Gemini Audit if relevant
                    candidates.append({
                        "frame_idx": frame_idx,
                        "timestamp": frame_idx / fps,
                        "class": cls,
                        "confidence": conf,
                        "box": box.xyxy[0].tolist()
                    })
            
            frame_idx += 1
            if frame_idx % 100 == 0:
                print(f"   Progress: {frame_idx}/{frame_count} frames", end='\r')

        cap.release()
        
        self.manifest["videos"][video_path] = {
            "status": "PROCESSED",
            "fps": fps,
            "total_frames": frame_count,
            "candidates_count": len(candidates),
            "candidates": candidates,
            "last_audit": time.time()
        }
        self._save_manifest()
        print(f"\n📊 SUMMARY: Found {len(candidates)} candidates in {video_path}")

if __name__ == "__main__":
    processor = BatchVideoProcessor()
    urls = []
    
    # Check if command line args provided
    if len(sys.argv) > 1:
        if sys.argv[1] == "--file" and len(sys.argv) > 2:
            with open(sys.argv[2], 'r') as f:
                urls = [line.strip() for line in f if line.strip()]
            print(f"🚀 BATCH FILE MODE: Ingernesting {len(urls)} URLs")
        elif sys.argv[1] == "--test-mode":
            urls = ["https://www.youtube.com/watch?v=yP9v8KRym9c"]
            
    for url in urls:
        path = processor.download_video(url)
        if path:
            processor.process_video(path)
