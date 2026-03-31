import os
from roboflow import Roboflow
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ROBOFLOW_API_KEY")

def download():
    print(f"USING_ROBO_KEY: {api_key}")
    try:
        rf = Roboflow(api_key=api_key)
        p = rf.workspace("viren-daultani-y0fio").project("road-signs-indian-p2kgu")
        d = p.version(1).download("yolov8")
        print(f"DOWNLOAD_LOCATION: {d.location}")
    except Exception as e:
        print(f"ERR: {e}")

if __name__ == "__main__":
    download()
