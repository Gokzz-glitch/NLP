import os
import sys
import time
import cv2
import numpy as np
from ultralytics import YOLO
from core.model_registry import resolve_yolo_pothole_pt

def benchmark_model(model_path, frame_count=100):
    """Benchmarks the model performance in FPS."""
    print(f"⏱️ BENCHMARKING: {model_path}")
    try:
        model = YOLO(model_path, task='detect')
    except Exception as e:
        print(f"❌ FAILED TO LOAD MODEL: {e}")
        return 0
        
    # Dummy frame (representative of Indian road conditions)
    dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)
    # Attempt to load a real SSL image for accurate benchmarking
    ssl_img_path = "datasets/ssl_v1/images/yP9v8KRym9c_2550.jpg"
    if os.path.exists(ssl_img_path):
        dummy_frame = cv2.imread(ssl_img_path)
    
    if dummy_frame is None:
        dummy_frame = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)

    # Warmup
    for _ in range(10):
        model(dummy_frame, verbose=False)
        
    start_time = time.time()
    for _ in range(frame_count):
        model(dummy_frame, verbose=False)
    end_time = time.time()
    
    fps = frame_count / (end_time - start_time)
    print(f"🚀 PERFORMANCE: {fps:.2f} FPS")
    return fps

def optimize_sentinel(model_path=None):
    model_path = model_path or str(resolve_yolo_pothole_pt())
    print(f"🛠️ OPTIMIZING SENTINEL EDGE-BRAIN: {model_path}")
    
    if not os.path.exists(model_path):
        print(f"❌ ERROR: Original weights '{model_path}' not found. Run Colab Training Hub first.")
        return

    model = YOLO(model_path)
    
    # 1. Export to ONNX (Cross-platform baseline)
    if not os.path.exists(model_path.replace('.pt', '.onnx')):
        print("📦 Exporting to ONNX...")
        model.export(format='onnx', opset=12, simplify=True)
    
    # 2. Export to OpenVINO (Intel CPU Gold Standard)
    ov_path = model_path.replace('.pt', '_openvino_model')
    if not os.path.exists(ov_path):
        print("📦 Exporting to OpenVINO (FP16)...")
        model.export(format='openvino', half=True)
    
    print("\n✅ OPTIMIZATION COMPLETE.")
    
    # 3. Macha Benchmark Comparison
    pt_fps = benchmark_model(model_path)
    
    if os.path.exists(ov_path):
        ov_fps = benchmark_model(ov_path)
        gain = (ov_fps / pt_fps) if pt_fps > 0 else 0
        print(f"\n📈 EDGE ACCELERATION GAIN: {gain:.2f}x")
    else:
        print("⚠️ OpenVINO Export skipped or failed. Using ONNX fallback.")

if __name__ == "__main__":
    model_arg = str(resolve_yolo_pothole_pt())
    if len(sys.argv) > 1:
        model_arg = sys.argv[1]
        
    optimize_sentinel(model_arg)
