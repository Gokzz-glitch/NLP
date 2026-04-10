import os
from roboflow import Roboflow
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ROBOFLOW_API_KEY")

def download():
    rf = Roboflow(api_key=api_key)
    project = rf.workspace("indian-road-dataset").project("indian-roads-detection")
    dataset = project.version(2).download("yolov8")
    
    # The SDK downloads a .zip or a folder containing 'weights/best.pt'
    # Since we need ONNX and don't want to install ultralytics locally (Heavy),
    # we will rely on the user having the ONNX file or we instructions to export it in Colab.
    
    print(f"Dataset downloaded to: {dataset.location}")
    print("ACTION REQUIRED: Export the best.pt to ONNX using Ultralytics in Colab.")

if __name__ == "__main__":
    download()
