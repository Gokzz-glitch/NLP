import os
from roboflow import Roboflow
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ROBOFLOW_API_KEY")

def download_vision_models():
    rf = Roboflow(api_key=api_key)
    
    # Model 1: Legal Signage Auditor
    print("FETCHING: Legal Signage Auditor...")
    try:
        # Searching for road-signs-indian-p2kgu version 1
        project1 = rf.workspace("viren-daultani-y0fio").project("road-signs-indian-p2kgu")
        project1.version(1).download("yolov8") # This downloads the weights
        # Usually it comes in a folder. I'll need to move it to models/vision/
    except Exception as e:
        print(f"FAILED_1: {e}")

    # Model 2: V2X Hazard Monitor (Chaos)
    print("FETCHING: V2X Hazard Monitor...")
    try:
        # Searching for indian-roads-detection version 2
        project2 = rf.workspace("wirehead").project("indian-roads-detection")
        project2.version(2).download("yolov8")
    except Exception as e:
        print(f"FAILED_2: {e}")

if __name__ == "__main__":
    download_vision_models()
