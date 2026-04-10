import os
from dotenv import load_dotenv
from roboflow import Roboflow

# [PERSONA 3: UNBLOCKING ERR-001]
# Specialized weights downloader for Indian Potholes and Traffic.

def download_specialized_weights():
    # 1. Load config
    load_dotenv()
    api_key = os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        print("❌ Error: ROBOFLOW_API_KEY not found in .env!")
        return

    rf = Roboflow(api_key=api_key)
    
    # 2. Download Pothole Weights (Intel Unnati / Indian Roads)
    print("\nFetching Pothole Detection model (pothole-detection-bqu6s)...")
    pothole_workspace = "intel-unnati-training-program"
    pothole_project = "pothole-detection-bqu6s"
    pothole_version = 1
    
    try:
        project = rf.workspace(pothole_workspace).project(pothole_project)
        # Use .download("yolov8") to get the format we can convert to ONNX if needed
        # Or check if there is an exported model directly
        model = project.version(pothole_version).model
        # For simplicity, we download the weights (.pt) and convert to .onnx locally
        project.version(pothole_version).download("yolov8", location="raw_data/pothole_dl")
        print("Pothole weights downloaded to raw_data/pothole_dl/")
    except Exception as e:
        print(f"Failed to download pothole model: {e}")

    # 3. Download Indian Traffic Signs (MVA 2019)
    print("\nFetching Indian Traffic Signs model (indian-traffic-signs-yolov8)...")
    traffic_workspace = "as-u7s8u" # Standard ID for this popular project
    traffic_project = "indian-traffic-signs-yolov8"
    traffic_version = 1
    
    try:
        project = rf.workspace("as-u7s8u").project(traffic_project)
        project.version(traffic_version).download("yolov8", location="raw_data/traffic_dl")
        print("Traffic weights downloaded to raw_data/traffic_dl/")
    except Exception as e:
        # Fallback to search if the workspace ID changed
        print(f"Failed to download traffic model: {e}")
        print("Tip: Manually verify the Project ID on Roboflow Universe.")

if __name__ == "__main__":
    download_specialized_weights()
