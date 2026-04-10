import os
import shutil
from roboflow import Roboflow
from huggingface_hub import hf_hub_download
from dotenv import load_dotenv
from config import heavy_task

load_dotenv()
ROBO_KEY = os.getenv("ROBOFLOW_API_KEY")
HF_KEY = os.getenv("HF_TOKEN")

<<<<<<< HEAD:scripts/utils/finalize_models.py
@heavy_task("MODEL_FINALIZATION")
=======
# Output directories — override via environment variables if needed
_PROJECT_ROOT = os.path.dirname(__file__)
VISION_MODELS_DIR = os.getenv("VISION_MODELS_DIR", os.path.join(_PROJECT_ROOT, "models", "vision"))
LLM_MODELS_DIR = os.getenv("LLM_MODELS_DIR", os.path.join(_PROJECT_ROOT, "models", "llm"))

>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e:finalize_models.py
def finalize():
    print("FINALIZING_MODELS_FOR_EDGE_SENTINEL.")
    
    # 1. VISION: Signage
    try:
        rf = Roboflow(api_key=ROBO_KEY)
        # Using the SDI workspace identified by browser subagent
        project1 = rf.workspace("sdi").project("indian-traffic-sign")
        dataset1 = project1.version(1).download("yolov8")
        src1 = os.path.join(dataset1.location, "weights", "best.pt")
        if os.path.exists(src1):
            from ultralytics import YOLO
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
            from ultralytics import YOLO
            model = YOLO(src2)
            model.export(format="onnx")
            onnx_src2 = src2.replace(".pt", ".onnx")
<<<<<<< HEAD:scripts/utils/finalize_models.py
            # Final destination for ERR-001 resolution
            shutil.copy(onnx_src2, "g:/My Drive/NLP/models/vision/indian_vehicles_chaos_yolov8n.onnx")
            print("SUCCESS: V2X Hazard Monitor (IDD-ONNX).")
=======
            os.makedirs(VISION_MODELS_DIR, exist_ok=True)
            shutil.copy(onnx_src2, os.path.join(VISION_MODELS_DIR, "indian_vehicles_chaos_yolov8n.onnx"))
            print("SUCCESS: V2X Hazard Monitor (ONNX).")
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e:finalize_models.py
    except Exception as e:
        print(f"ERR_CHAOS (IDD): {e}")

    # 3. LLM: Edge Legal
    try:
<<<<<<< HEAD:scripts/utils/finalize_models.py
        # Public model, but passing token for safety
=======
        os.makedirs(LLM_MODELS_DIR, exist_ok=True)
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e:finalize_models.py
        path = hf_hub_download(
            repo_id="microsoft/Phi-3-mini-4k-instruct-gguf",
            filename="Phi-3-mini-4k-instruct-q4.gguf",
            local_dir=LLM_MODELS_DIR,
            token=HF_KEY
        )
<<<<<<< HEAD:scripts/utils/finalize_models.py
        dest_llm = "g:/My Drive/NLP/models/llm/phi-3-mini-4k-instruct-q4.gguf"
=======
        # Rename to user requested
        dest_llm = os.path.join(LLM_MODELS_DIR, "phi-3-mini-4k-instruct-q4.gguf")
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e:finalize_models.py
        if os.path.exists(path) and path != dest_llm:
             shutil.copy(path, dest_llm)
        print(f"SUCCESS: Edge Legal Reasoner.")
    except Exception as e:
        print(f"ERR_LLM: {e}")

if __name__ == "__main__":
    finalize()
