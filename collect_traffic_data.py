import os
from roboflow import Roboflow
from dotenv import load_dotenv

# Load API Keys
load_dotenv()
api_key = os.getenv("ROBOFLOW_API_KEY")

if not api_key:
    print("ERR_CONFIG: [ROBOFLOW_API_KEY missing in .env]")
    exit(1)

def collect_indian_traffic_data():
    rf = Roboflow(api_key=api_key)
    
    # Example target: Road Signs Indian dataset (well known on Universe)
    # Search for project: road-signs-indian-p2kgu
    try:
        project = rf.workspace("viren-daultani-y0fio").project("road-signs-indian-p2kgu")
        dataset = project.version(1).download("yolov8")
        print(f"PERSONA_3_REPORT: COLLECTION_SUCCESS. Dataset path: {dataset.location}")
    except Exception as e:
        print(f"ERR_COLLECTION: [Roboflow Error: {str(e)}]")

if __name__ == "__main__":
    print("PERSONA_3_REPORT: INITIATING_TRAFFIC_DATA_COLLECTION.")
    collect_indian_traffic_data()
