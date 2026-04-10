import os
import shutil
from huggingface_hub import hf_hub_download
from dotenv import load_dotenv
from config import VISION_MODEL_DIR, LLM_MODEL_DIR

try:
    from roboflow import Roboflow
    _ROBOFLOW_AVAILABLE = True
except ImportError:
    _ROBOFLOW_AVAILABLE = False

try:
    from ultralytics import YOLO
    _YOLO_AVAILABLE = True
except ImportError:
    _YOLO_AVAILABLE = False

load_dotenv()
ROBO_KEY = os.getenv("ROBOFLOW_API_KEY")
HF_KEY = os.getenv("HF_TOKEN")

# Output directories — override via environment variables if needed
VISION_MODELS_DIR = os.getenv("VISION_MODELS_DIR", VISION_MODEL_DIR)
LLM_MODELS_DIR = os.getenv("LLM_MODELS_DIR", LLM_MODEL_DIR)

def finalize():
    print("FINALIZING_MODELS_FOR_EDGE_SENTINEL.")
    
    # 1. VISION: Signage
    if _ROBOFLOW_AVAILABLE and _YOLO_AVAILABLE:
        try:
            rf = Roboflow(api_key=ROBO_KEY)
            # Using the SDI workspace identified by browser subagent
            project1 = rf.workspace("sdi").project("indian-traffic-sign")
            dataset1 = project1.version(1).download("yolov8")
            src1 = os.path.join(dataset1.location, "weights", "best.pt")
            if os.path.exists(src1):
                model = YOLO(src1)
                model.export(format="onnx")
                onnx_src1 = src1.replace(".pt", ".onnx")
                os.makedirs(VISION_MODELS_DIR, exist_ok=True)
                shutil.copy(onnx_src1, os.path.join(VISION_MODELS_DIR, "indian_traffic_signs_yolov8n.onnx"))
                print("SUCCESS: Legal Signage Auditor (ONNX).")
        except Exception as e:
            print(f"ERR_SIGNAGE: {e}")

        # 2. VISION: Chaos (IDD-trained)
        try:
            rf = Roboflow(api_key=ROBO_KEY)
            # Using version 2 (IDD-trained) as identified in research
            project2 = rf.workspace("indian-road-dataset").project("indian-roads-detection")
            dataset2 = project2.version(2).download("yolov8")
            src2 = os.path.join(dataset2.location, "weights", "best.pt")
            if os.path.exists(src2):
                model = YOLO(src2)
                model.export(format="onnx")
                onnx_src2 = src2.replace(".pt", ".onnx")
                os.makedirs(VISION_MODELS_DIR, exist_ok=True)
                shutil.copy(onnx_src2, os.path.join(VISION_MODELS_DIR, "indian_vehicles_chaos_yolov8n.onnx"))
                print("SUCCESS: V2X Hazard Monitor (ONNX).")
        except Exception as e:
            print(f"ERR_CHAOS (IDD): {e}")
    else:
        print("SKIP_VISION: roboflow or ultralytics not installed.")

    # 3. LLM: Edge Legal
    try:
        os.makedirs(LLM_MODELS_DIR, exist_ok=True)
        path = hf_hub_download(
            repo_id="microsoft/Phi-3-mini-4k-instruct-gguf",
            filename="Phi-3-mini-4k-instruct-q4.gguf",
            local_dir=LLM_MODELS_DIR,
            token=HF_KEY
        )
        dest_llm = os.path.join(LLM_MODELS_DIR, "phi-3-mini-4k-instruct-q4.gguf")
        if os.path.exists(path) and path != dest_llm:
            shutil.copy(path, dest_llm)
        print(f"SUCCESS: Edge Legal Reasoner.")
    except Exception as e:
        print(f"ERR_LLM: {e}")

if __name__ == "__main__":
    finalize()
