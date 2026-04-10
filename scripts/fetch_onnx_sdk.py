import os
from roboflow import Roboflow
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ROBOFLOW_API_KEY")

def fetch():
    rf = Roboflow(api_key=api_key)
    project = rf.workspace("indian-road-dataset").project("indian-roads-detection")
    
    # Download ONNX archive (this bypasses .pt -> .onnx export step)
    dataset = project.version(2).download("onnx")
    onnx_candidates = [
        os.path.join(dataset.location, name)
        for name in os.listdir(dataset.location)
        if name.lower().endswith(".onnx")
    ]
    on_nx_path = onnx_candidates[0] if onnx_candidates else None
    
    if on_nx_path and os.path.exists(on_nx_path):
        import shutil
        dest = "g:/My Drive/NLP/models/vision/indian_vehicles_chaos_yolov8n.onnx"
        shutil.copy(on_nx_path, dest)
        print(f"SUCCESS: Weight-sync complete to {dest}")
    else:
        print(f"ERROR: No ONNX found in {dataset.location}")
        # List files to help me debug
        print(f"Contents: {os.listdir(dataset.location)}")

if __name__ == "__main__":
    fetch()
