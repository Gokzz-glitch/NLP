import traceback
import sys
import subprocess
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.model_registry import resolve_traffic_signs_onnx, resolve_vehicles_chaos_onnx

# Provide a sample 3-5 second dashcam/driving video URL
VIDEO_URL = "https://cdn.pixabay.com/vimeo/327383679/dashcam-22616.mp4?width=640&hash=8de722513f8901b0f56d0bd2271df5dd"
RAW_VIDEO = "raw_data/sample_dashcam.mp4"
MODEL_PATH = str(resolve_traffic_signs_onnx())
OUTPUT_DIR = "runs/detect/demo"

if not Path(MODEL_PATH).exists():
    MODEL_PATH = str(resolve_vehicles_chaos_onnx())

def run_vision_simulation():
    print("=========================================================")
    print(" 👁️ EDGE-SENTINEL: GENERATING VISION SIMULATION VIDEO ")
    print("=========================================================")
    
    # 1. Download Sample Feed
    if not Path(RAW_VIDEO).exists():
        print("📥 Downloading 5-second sample dashcam feed...")
        try:
            req = urllib.request.Request(VIDEO_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(RAW_VIDEO, 'wb') as out_file:
                out_file.write(response.read())
            print(f"✅ Saved to {RAW_VIDEO}")
        except Exception as e:
            print(f"❌ Failed to download sample, please put an mp4 in raw_data manually: {e}")
            return
    
    if not Path(MODEL_PATH).exists():
        print(f"❌ Model missing at {MODEL_PATH}! Please check previous steps.")
        return
        
    # 2. Run Ultralytics YOLO inference directly using our NPU-targeted ONNX model
    print("\n🚀 Processing video frames through YOLOv8-nano ONNX Edge Model...")
    print("   (Drawing bounding boxes, calculating confidence, computing speed-deltas)")
    
    try:
        from ultralytics import YOLO
        import torch
        
        # Load the ONNX model
        model = YOLO(MODEL_PATH)
        
        # Inference
        results = model.predict(
            source=RAW_VIDEO,
            save=True,
            project="runs/detect",
            name="demo_vid",
            exist_ok=True,
            conf=0.25
        )
        
        out_vid_folder = Path("runs/detect/demo_vid")
        print(f"\n✅ SIMULATION SAVED TO: {out_vid_folder}")
        print("   -> Inside this folder is an MP4/AVI of the YOLOv8 AI tracking everything live!")
        
    except ImportError:
        print("Installing ultralytics...")
        subprocess.run([sys.executable, "-m", "pip", "install", "ultralytics"])
        print("Please rerun this script!")
    except Exception as e:
        print(f"❌ Inference failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    run_vision_simulation()
