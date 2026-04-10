# YouTube Real-World Testing Guide

## Overview
This guide demonstrates how to download YouTube videos and test the SmartSalai Edge-Sentinel app with real-world video data. All videos are saved to the **Testing videos** folder.

## Setup Requirements

### 1. Install Dependencies
```bash
pip install yt-dlp opencv-python ultralytics
```

### 2. Verify Testing videos Folder
```bash
# The Testing videos folder should exist in your workspace
# If it doesn't exist, create it:
mkdir "Testing videos"
```

## Usage Methods

### Method 1: Download and Test Using Default YouTube URLs
```bash
cd scripts
python youtube_test_runner.py --test-mode
```

This will:
- Download 2 default test videos from YouTube
- Save them to `Testing videos/`
- Run YOLO inference on all frames
- Generate detailed audit reports in `Testing videos/results/`

### Method 2: Download and Test From URL List File
First, create a file with YouTube URLs:

```bash
# Create videos list (e.g., video_sources.txt in project root)
cat > video_sources.txt << EOF
https://www.youtube.com/watch?v=NFpo7_sAdWU
https://www.youtube.com/watch?v=yP9v8KRym9c
https://www.youtube.com/watch?v=1zxNwZkiazc
EOF

# Run test
cd scripts
python youtube_test_runner.py --file ../video_sources.txt
```

### Method 3: Direct URL Input
```bash
cd scripts
python youtube_test_runner.py --urls "https://www.youtube.com/watch?v=..." "https://www.youtube.com/watch?v=..."
```

### Method 4: Process Existing Videos in Testing videos Folder
```bash
cd scripts
python batch_processor.py --test-mode
```

This will:
- Auto-detect videos in `Testing videos/` folder
- Run inference on each video
- Create `process_manifest.json` with all detections

## Output Structure

After running tests, you'll find:

```
Testing videos/
├── video_id_1_title.mp4        # Downloaded video 1
├── video_id_2_title.mp4        # Downloaded video 2
├── process_manifest.json       # Batch processing log
├── test_manifest.json          # YouTube test runner log
└── results/
    ├── video_id_1_report.json  # Detailed findings for video 1
    ├── video_id_2_report.json  # Detailed findings for video 2
    └── ...
```

## Viewing Results

### 1. Check Manifest for Overview
```python
import json

with open("Testing videos/test_manifest.json", 'r') as f:
    manifest = json.load(f)
    
print(f"Total videos processed: {manifest['summary']['total_processed']}")
print(f"Total detections found: {manifest['summary']['total_detections']}")
```

### 2. Analyze Detailed Reports
```python
import json

with open("Testing videos/results/video_id_1_report.json", 'r') as f:
    report = json.load(f)
    
print(f"Duration: {report['video_stats']['duration_seconds']} seconds")
print(f"Detections: {report['detection_summary']['total_detections']}")
print(f"Classes found: {list(report['detection_summary']['detection_classes'].keys())}")
```

## Testing the Full Pipeline with WebSocket

Once videos are in `Testing videos/`, test the real-time pipeline:

```bash
# Terminal 1: Start Macha Service Gateway
cd scripts
python sentinel_hub.py

# Terminal 2: Run real-world auditor
python real_world_test.py
```

The auditor will:
- Auto-detect first video in `Testing videos/` folder
- Stream frame detections to the WebSocket service
- Generate live alerts for high-confidence detections

## Performance Benchmarks

### Sample Download Sizes (for 720p videos)
- Short clips (30 sec): ~30-50 MB
- Medium clips (2-5 min): ~100-300 MB
- Longer videos (10+ min): ~500+ MB

### Processing Speed (on CPU)
- YOLOv8-nano: ~15-20 FPS (CPU)
- YOLOv8-small: ~5-10 FPS (CPU)
- Full frame every second: ~1-2 detections per second

## Troubleshooting

### yt-dlp Installation Issues
```bash
# Update yt-dlp
pip install --upgrade yt-dlp

# Verify installation
yt-dlp --version
```

### Video Download Fails
- Check internet connection
- YouTube video might be restricted (age-gated, private, etc.)
- Try a different video URL
- Some regions may have restrictions

### Out of Memory
- Process shorter video clips
- Reduce frame sampling rate (modify `sample_rate` in youtube_test_runner.py)
- Use smaller model (yolov8n instead of yolov8m)

### Model Loading Issues
```bash
# Download default YOLO model
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

## Script Modifications

### Change model in batch_processor.py
```python
# Edit line in batch_processor.py
processor = BatchVideoProcessor(model_path="yolov8_pothole.pt")
```

### Change sampling rate
```python
# In youtube_test_runner.py, modify line ~165
sample_rate = max(1, int(fps) // 2)  # Process every 0.5 FPS instead of 1 FPS
```

### Change output directory
```bash
# Specify different directory
python youtube_test_runner.py --test-mode --videos-dir "my_test_videos"
```

## Next Steps

1. **Download and test** initial YouTube videos for baseline
2. **Analyze results** to understand detection quality
3. **Fine-tune** model thresholds based on results
4. **Generate proof reels** with high-confidence detections
5. **Validate** with the mobile app on actual Android devices

## Example Workflow

```bash
# 1. Download test videos
python youtube_test_runner.py --test-mode

# 2. Check results
cat "Testing videos/test_manifest.json"

# 3. View detailed report
python -c "import json; print(json.dumps(json.load(open('Testing videos/results/*_report.json')), indent=2))"

# 4. Generate proof reels
python generate_proof_reels.py

# 5. Test with live service
python real_world_test.py
```

---

**Questions?** Check logs in:
- `logs/youtube_test_*.log` - Test runner logs
- `Testing videos/results/*.json` - Detailed detection reports
