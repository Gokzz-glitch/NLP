#!/usr/bin/env python3
"""
YouTube Real-World Testing Framework for SmartSalai Edge-Sentinel

This script:
1. Downloads videos from YouTube using the provided URLs
2. Saves them to the "Testing videos" folder
3. Runs the full inference pipeline on downloaded videos
4. Generates audit reports and proof reels

Usage:
    python youtube_test_runner.py --urls https://www.youtube.com/watch?v=... https://www.youtube.com/watch?v=...
    python youtube_test_runner.py --file video_sources.txt
    python youtube_test_runner.py --test-mode  # Use default test YouTube URLs
"""

import os
import sys
import subprocess
import json
import cv2
import logging
from pathlib import Path
from ultralytics import YOLO
import asyncio
import websockets
from datetime import datetime
from core.model_registry import resolve_yolo_general_pt, resolve_yolo_pothole_pt

# Project Root Setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | [YOUTUBE_RUNNER] %(message)s",
    handlers=[
        logging.FileHandler(f"logs/youtube_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class YouTubeTestRunner:
    def __init__(self, videos_dir="Testing videos", model_path=None):
        """Initialize the YouTube test runner."""
        self.videos_dir = videos_dir
        self.model_path = model_path or str(resolve_yolo_pothole_pt())
        self.manifest_path = os.path.join(videos_dir, "test_manifest.json")
        self.results_dir = os.path.join(videos_dir, "results")
        
        # Create directories if they don't exist
        for directory in [videos_dir, self.results_dir]:
            os.makedirs(directory, exist_ok=True)
            logger.info(f"📁 Directory ready: {directory}")
        
        # Load or create manifest
        self.manifest = self._load_manifest()
        
        # Initialize model
        try:
            self.model = YOLO(self.model_path)
            logger.info(f"✅ Model loaded: {self.model_path}")
        except Exception as e:
            logger.warning(f"⚠️ Model loading failed: {e}")
            fallback_model = str(resolve_yolo_general_pt())
            self.model = YOLO(fallback_model)  # Fallback to standard YOLOv8
            logger.info(f"✅ Fallback model loaded: {fallback_model}")

    def _load_manifest(self):
        """Load test manifest or create new one."""
        if os.path.exists(self.manifest_path):
            with open(self.manifest_path, 'r') as f:
                logger.info(f"📋 Loaded existing manifest from {self.manifest_path}")
                return json.load(f)
        return {
            "session_id": datetime.now().isoformat(),
            "videos": {},
            "summary": {
                "total_downloaded": 0,
                "total_processed": 0,
                "total_detections": 0
            }
        }

    def _save_manifest(self):
        """Save manifest to disk."""
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=4)
            logger.info(f"💾 Manifest saved: {self.manifest_path}")

    def download_youtube_video(self, url):
        """Download a YouTube video using yt-dlp."""
        logger.info(f"📥 Downloading: {url}")
        
        try:
            # Use yt-dlp to download video
            cmd = [
                "yt-dlp",
                "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "--merge-output-format", "mp4",
                "-o", f"{self.videos_dir}/%(id)s_%(title)s.%(ext)s",
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.error(f"❌ Download failed: {result.stderr}")
                return None
            
            # Find the downloaded file
            video_id = subprocess.check_output(["yt-dlp", "--get-id", url]).decode().strip()
            import glob
            files = glob.glob(os.path.join(self.videos_dir, f"{video_id}*"))
            
            if files:
                video_path = files[0]
                video_size_mb = os.path.getsize(video_path) / (1024 * 1024)
                logger.info(f"✅ Downloaded: {os.path.basename(video_path)} ({video_size_mb:.2f} MB)")
                return video_path
            
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Download timeout: {url}")
        except FileNotFoundError:
            logger.error(f"❌ yt-dlp not found. Install it with: pip install yt-dlp")
        except Exception as e:
            logger.error(f"❌ Download error: {e}")
        
        return None

    def process_video(self, video_path):
        """Process a video with YOLO inference."""
        logger.info(f"🧠 Processing video: {os.path.basename(video_path)}")
        
        if not os.path.exists(video_path):
            logger.error(f"❌ Video not found: {video_path}")
            return None
        
        try:
            cap = cv2.VideoCapture(video_path)
            
            if not cap.isOpened():
                logger.error(f"❌ Cannot open video: {video_path}")
                return None
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            logger.info(f"📊 Video specs: {frame_count} frames @ {fps} FPS ({width}x{height})")
            
            detections = []
            frame_idx = 0
            processed_frames = 0
            
            # Process every Nth frame for efficiency
            sample_rate = max(1, int(fps))  # Process at 1 FPS
            
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Process sampled frames
                if frame_idx % sample_rate == 0:
                    try:
                        results = self.model(frame, verbose=False)[0]
                        
                        for box in results.boxes:
                            detection = {
                                "frame_idx": frame_idx,
                                "timestamp": frame_idx / fps,
                                "class": int(box.cls[0]),
                                "class_name": self.model.names.get(int(box.cls[0]), "unknown"),
                                "confidence": float(box.conf[0]),
                                "bbox": box.xyxy[0].tolist()
                            }
                            detections.append(detection)
                        
                        processed_frames += 1
                        if processed_frames % 10 == 0:
                            logger.info(f"   ⏳ Processed {processed_frames} frames ({frame_idx}/{frame_count})")
                    
                    except Exception as e:
                        logger.warning(f"   ⚠️ Frame {frame_idx} processing error: {e}")
                
                frame_idx += 1
            
            cap.release()
            
            # Log results
            logger.info(f"✅ Processing complete: {len(detections)} detections in {processed_frames} sampled frames")
            
            return {
                "video_path": video_path,
                "fps": fps,
                "total_frames": frame_count,
                "processed_frames": processed_frames,
                "video_duration_sec": frame_count / fps,
                "dimensions": f"{width}x{height}",
                "detections_count": len(detections),
                "detections": detections,
                "processed_at": datetime.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"❌ Video processing failed: {e}")
            return None

    def generate_audit_report(self, video_result):
        """Generate a detailed audit report for the processed video."""
        video_name = os.path.basename(video_result["video_path"])
        report_name = f"{os.path.splitext(video_name)[0]}_report.json"
        report_path = os.path.join(self.results_dir, report_name)
        
        # Prepare report
        report = {
            "video_file": video_name,
            "processing_time": video_result["processed_at"],
            "video_stats": {
                "duration_seconds": video_result["video_duration_sec"],
                "fps": video_result["fps"],
                "total_frames": video_result["total_frames"],
                "processed_frames": video_result["processed_frames"],
                "dimensions": video_result["dimensions"]
            },
            "detection_summary": {
                "total_detections": video_result["detections_count"],
                "detection_classes": {}
            },
            "detections": video_result["detections"]
        }
        
        # Count detections by class
        for detection in video_result["detections"]:
            class_name = detection["class_name"]
            if class_name not in report["detection_summary"]["detection_classes"]:
                report["detection_summary"]["detection_classes"][class_name] = {"count": 0, "avg_confidence": 0}
            
            report["detection_summary"]["detection_classes"][class_name]["count"] += 1
        
        # Calculate average confidence
        for class_name in report["detection_summary"]["detection_classes"]:
            class_detections = [d for d in video_result["detections"] if d["class_name"] == class_name]
            avg_conf = sum(d["confidence"] for d in class_detections) / len(class_detections)
            report["detection_summary"]["detection_classes"][class_name]["avg_confidence"] = round(avg_conf, 3)
        
        # Save report
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=4)
        
        logger.info(f"📄 Report generated: {report_path}")
        return report

    def run_batch_test(self, urls):
        """Run batch download and test on multiple YouTube URLs."""
        logger.info(f"🚀 Starting batch test with {len(urls)} videos")
        
        for url in urls:
            # Download video
            video_path = self.download_youtube_video(url)
            if not video_path:
                logger.warning(f"⏭️ Skipping {url}")
                continue
            
            # Process video
            result = self.process_video(video_path)
            if not result:
                logger.warning(f"⏭️ Skipping processing for {video_path}")
                continue
            
            # Generate report
            report = self.generate_audit_report(result)
            
            # Update manifest
            self.manifest["videos"][video_path] = {
                "url": url,
                "status": "PROCESSED",
                "detection_count": result["detections_count"],
                "processed_at": datetime.now().isoformat()
            }
            
            self.manifest["summary"]["total_downloaded"] += 1
            self.manifest["summary"]["total_processed"] += 1
            self.manifest["summary"]["total_detections"] += result["detections_count"]
            
            self._save_manifest()
            
            logger.info(f"=" * 60)
        
        logger.info(f"✅ Batch test complete!")
        logger.info(f"📊 Summary: Downloaded {self.manifest['summary']['total_downloaded']} "
                   f"| Processed {self.manifest['summary']['total_processed']} "
                   f"| Total detections {self.manifest['summary']['total_detections']}")

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="YouTube Real-World Testing for SmartSalai Edge-Sentinel")
    parser.add_argument("--urls", nargs="+", help="YouTube URLs to download and test")
    parser.add_argument("--file", help="File containing YouTube URLs (one per line)")
    parser.add_argument("--test-mode", action="store_true", help="Use default test YouTube URLs")
    parser.add_argument("--videos-dir", default="Testing videos", help="Directory to save videos")
    parser.add_argument("--model", default=str(resolve_yolo_pothole_pt()), help="YOLO model path")
    
    args = parser.parse_args()
    
    # Initialize runner
    runner = YouTubeTestRunner(videos_dir=args.videos_dir, model_path=args.model)
    
    # Determine URLs to process
    urls = []
    
    if args.test_mode:
        urls = [
            "https://www.youtube.com/watch?v=NFpo7_sAdWU",
            "https://www.youtube.com/watch?v=yP9v8KRym9c"
        ]
        logger.info("🧪 Test mode: Using default YouTube URLs")
    
    elif args.file:
        try:
            with open(args.file, 'r') as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            logger.info(f"📂 Loaded {len(urls)} URLs from {args.file}")
        except FileNotFoundError:
            logger.error(f"❌ File not found: {args.file}")
            sys.exit(1)
    
    elif args.urls:
        urls = args.urls
    
    else:
        parser.print_help()
        sys.exit(1)
    
    # Run batch test
    if urls:
        runner.run_batch_test(urls)
    else:
        logger.error("❌ No URLs provided")
        sys.exit(1)

if __name__ == "__main__":
    main()
