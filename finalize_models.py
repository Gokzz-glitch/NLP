import os
import shutil
from roboflow import Roboflow
from huggingface_hub import hf_hub_download
from dotenv import load_dotenv

load_dotenv()
ROBO_KEY = os.getenv("ROBOFLOW_API_KEY")
HF_KEY = os.getenv("HF_TOKEN")

# Output directories — override via environment variables if needed
_PROJECT_ROOT = os.path.dirname(__file__)
VISION_MODELS_DIR = os.getenv("VISION_MODELS_DIR", os.path.join(_PROJECT_ROOT, "models", "vision"))
LLM_MODELS_DIR = os.getenv("LLM_MODELS_DIR", os.path.join(_PROJECT_ROOT, "models", "llm"))

def finalize():
    print("FINALIZING_MODELS_FOR_EDGE_SENTINEL.")
    
    # 1. VISION: Signage
    try:
        rf = Roboflow(api_key=ROBO_KEY)
        p1 = rf.workspace("viren-daultani-y0fio").project("road-signs-indian-p2kgu")
        d1 = p1.version(1).download("yolov8")
        # Moving best.pt (yolov8 weights)
        src1 = os.path.join(d1.location, "weights", "best.pt") # roboflow default
        if os.path.exists(src1):
            from ultralytics import YOLO
            model = YOLO(src1)
            model.export(format="onnx")
            # Move exported onnx
            onnx_src1 = src1.replace(".pt", ".onnx")
            os.makedirs(VISION_MODELS_DIR, exist_ok=True)
            shutil.copy(onnx_src1, os.path.join(VISION_MODELS_DIR, "indian_traffic_yolov8.onnx"))
            print("SUCCESS: Legal Signage Auditor (ONNX).")
    except Exception as e:
        print(f"ERR_1: {e}")

    # 2. VISION: Chaos
    try:
        rf = Roboflow(api_key=ROBO_KEY)
        p2 = rf.workspace("wirehead").project("indian-roads-detection")
        d2 = p2.version(2).download("yolov8")
        src2 = os.path.join(d2.location, "weights", "best.pt")
        if os.path.exists(src2):
            from ultralytics import YOLO
            model = YOLO(src2)
            model.export(format="onnx")
            onnx_src2 = src2.replace(".pt", ".onnx")
            os.makedirs(VISION_MODELS_DIR, exist_ok=True)
            shutil.copy(onnx_src2, os.path.join(VISION_MODELS_DIR, "indian_vehicles_chaos_yolov8n.onnx"))
            print("SUCCESS: V2X Hazard Monitor (ONNX).")
    except Exception as e:
        print(f"ERR_2: {e}")


    # 3. LLM: Edge Legal
    try:
        os.makedirs(LLM_MODELS_DIR, exist_ok=True)
        path = hf_hub_download(
            repo_id="microsoft/Phi-3-mini-4k-instruct-gguf",
            filename="Phi-3-mini-4k-instruct-q4.gguf",
            local_dir=LLM_MODELS_DIR,
            token=HF_KEY
        )
        # Rename to user requested
        dest_llm = os.path.join(LLM_MODELS_DIR, "phi-3-mini-4k-instruct-q4.gguf")
        if os.path.exists(path) and path != dest_llm:
             shutil.copy(path, dest_llm)
        print(f"SUCCESS: Edge Legal Reasoner.")
    except Exception as e:
        print(f"ERR_3: {e}")

if __name__ == "__main__":
    finalize()
