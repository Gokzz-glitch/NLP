import os
import subprocess
from dotenv import load_dotenv
from config import heavy_task

load_dotenv()
# Using the user's provided token
os.environ["KAGGLE_USERNAME"] = "imgk311"
os.environ["KAGGLE_KEY"] = "KGAT_13d8e51ab23e77a0d8770bda2c41d0f4"

@heavy_task("SOTA_WEIGHTS_FETCH")
def fetch_sota():
    print("FETCHING: BharatPotHole SOTA weights via CLI...")
    k_exe = r"C:\Users\gokul\AppData\Roaming\Python\Python310\Scripts\kaggle.exe"
    
    try:
        # Download and unzip directly to target
        os.makedirs("g:/My Drive/NLP/models/vision/potholes", exist_ok=True)
        subprocess.run([k_exe, "datasets", "download", "-d", "surbhisaswatimohanty/bharatpothole", "--unzip", "-p", "g:/My Drive/NLP/models/vision/potholes"], check=True)
        print("SUCCESS: BharatPotHole extracted to models/vision/potholes")
    except Exception as e:
        print(f"FAILED_CLI: {e}")

if __name__ == "__main__":
    fetch_sota()
