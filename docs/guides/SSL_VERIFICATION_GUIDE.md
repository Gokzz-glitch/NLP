# YouTube + YOLO + SSL Verification Pipeline

## Overview

This pipeline automatically:
1. **Downloads** videos from YouTube
2. **Analyzes** them with YOLO model for hazard detection
3. **Verifies** each detection with Gemini (Self-Supervised Learning)
4. **Compares** YOLO predictions vs Gemini verification
5. **Generates** comprehensive audit reports

## Quick Start

### Basic Usage

```bash
# Test mode with 2 default YouTube videos
python scripts/youtube_ssl_verification.py --test-mode

# Process URLs from a file
python scripts/youtube_ssl_verification.py --file video_sources.txt

# Process specific URLs
python scripts/youtube_ssl_verification.py --urls "https://www.youtube.com/watch?v=..." "https://www.youtube.com/watch?v=..."
```

## Pipeline Workflow

```
┌─────────────────┐
│  YouTube Video  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│  Download to Testing    │
│  videos/ (720p, <300MB) │
└────────┬────────────────┘
         │
         ▼
┌──────────────────────┐
│  YOLO Inference      │
│  (1 FPS sampling)    │
│  Filter: conf >= 0.3 │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│  For Each Detection:                 │
│  1. Extract frame                    │
│  2. Send to Gemini 1.5 Flash         │
│  3. Get verification + confidence    │
│  4. Check YOLO vs Gemini agreement   │
└────────┬─────────────────────────────┘
         │
         ▼
┌────────────────────────────────────┐
│  Generate Report:                  │
│  - Detections per video            │
│  - Verification rate               │
│  - Agreement rate (YOLO vs Gemini) │
│  - Confidence comparison           │
└────────────────────────────────────┘
```

## Output Structure

```
Testing videos/
├── video_1.mp4                    # Downloaded video
├── video_2.mp4
├── ssl_verification_results/
│   ├── verification_report.json   # Main report
│   └── frame_*.jpg                # Extracted frames (auto cleaned)
```

## Report Structure

### Main Report: `verification_report.json`

```json
{
  "session_id": "2026-04-03T...",
  "videos_processed": {
    "video_title.mp4": {
      "video_name": "...",
      "yolo_detections_count": 15,
      "gemini_verifications": 12,
      "agreement_count": 10,
      "avg_yolo_confidence": 0.752,
      "avg_gemini_confidence": 0.845,
      "agreement_rate_percent": 83.3,
      "detections": [
        {
          "frame_idx": 120,
          "timestamp": 4.0,
          "class_name": "pothole",
          "yolo_confidence": 0.85,
          "gemini_verification": true,
          "gemini_confidence": 0.92,
          "agreement": true
        }
      ]
    }
  },
  "summary": {
    "total_videos": 1,
    "total_frames_analyzed": 15,
    "total_yolo_detections": 15,
    "total_verified_by_gemini": 12,
    "avg_yolo_confidence": 0.752,
    "avg_gemini_confidence": 0.845,
    "agreement_rate": 83.3
  }
}
```

## Key Metrics Explained

| Metric | Meaning |
|--------|---------|
| `yolo_detections_count` | Total hazards detected by YOLO |
| `gemini_verifications` | Count successfully verified by Gemini |
| `agreement_count` | Detections where YOLO and Gemini agree |
| `agreement_rate` | % of verified detections that match |
| `avg_yolo_confidence` | Average YOLO detection confidence (0-1) |
| `avg_gemini_confidence` | Average Gemini verification confidence (0-1) |

## Requirements

```bash
pip install yt-dlp opencv-python ultralytics google-generativeai python-dotenv
```

## Environment Variables

Create `.env` file in project root:

```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

Get API key from: https://ai.google.dev/

## Advanced Options

```bash
# Use custom YOLO model
python scripts/youtube_ssl_verification.py --test-mode --model yolov8_pothole_refined.pt

# Save to custom directory
python scripts/youtube_ssl_verification.py --test-mode --videos-dir my_test_videos
```

## Understanding Results

### High Agreement Rate (90%+)
✅ YOLO model is well-trained. Minimal manual review needed.

### Medium Agreement Rate (70-90%)
⚠️ Some YOLO detections need manual validation. Consider retraining.

### Low Agreement Rate (<70%)
❌ YOLO model needs significant retraining. Gemini findings more reliable.

## Troubleshooting

### "GEMINI_API_KEY_MISSING"
```bash
# Verify .env file exists and has GEMINI_API_KEY
cat .env
```

### "yt-dlp not found"
```bash
pip install --upgrade yt-dlp
```

### "ModuleNotFoundError: No module named 'agents'"
```bash
# Run from project root, not from scripts/ folder
cd /path/to/NLP
python scripts/youtube_ssl_verification.py --test-mode
```

### Gemini API Rate Limit
The script throttles API calls (1 second between verifications). For large batches:
- Process fewer videos at a time
- Wait between runs
- Check Gemini API quota at https://ai.google.dev/

## Example Workflow

```bash
# Step 1: Download and verify 2 test videos
python scripts/youtube_ssl_verification.py --test-mode

# Step 2: Check results
cat "Testing videos/ssl_verification_results/verification_report.json" | jq '.summary'

# Step 3: If agreement rate is high (>80%), add more videos
echo "https://www.youtube.com/watch?v=..." >> video_sources.txt
python scripts/youtube_ssl_verification.py --file video_sources.txt

# Step 4: Retrain model if agreement is low
# (Use the low-confidence detections for manual labeling)
```

## Integration with Other Scripts

### Use verified detections for retraining
```python
import json

with open("Testing videos/ssl_verification_results/verification_report.json") as f:
    report = json.load(f)

# Extract high-confidence detections confirmed by Gemini
verified_samples = []
for video in report["videos_processed"].values():
    for detection in video["detections"]:
        if detection["gemini_verification"] and detection["agreement"]:
            verified_samples.append(detection)

print(f"Found {len(verified_samples)} verified training samples")
```

### Feed to batch_processor.py
```bash
# Process already-downloaded videos
cd scripts
python batch_processor.py
```

### Generate proof reels
```bash
# Create video compilations of high-confidence detections
python scripts/generate_proof_reels.py
```

## Performance Benchmarks

### Processing Speed
- YOLOv8-nano: ~100 detections/minute (CPU)
- Gemini verification: ~5-10 seconds per frame

### Cost Estimate (Gemini API)
- Per 1000 image verifications: ~$0.10-0.20 (input tokens)
- Per 1000 responses: ~$0.30-0.50 (output tokens)

## See Also

- [YouTube Testing Guide](YOUTUBE_TESTING_GUIDE.md) - Basic video download/testing
- [Self-Supervised Learning Docs](agents/learner_agent.py) - SSL learning details
- [Batch Processor Docs](scripts/batch_processor.py) - Video batch processing

---

**Need help?** Check logs in `logs/ssl_verify_*.log`
