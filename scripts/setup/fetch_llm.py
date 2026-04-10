import os
from huggingface_hub import hf_hub_download
from dotenv import load_dotenv
from config import LLM_MODEL_DIR, IN_COLAB, heavy_task

load_dotenv()
hf_token = os.getenv("HF_TOKEN")

<<<<<<< HEAD:scripts/setup/fetch_llm.py
@heavy_task("LLM_MODEL_DOWNLOAD")
=======
_PROJECT_ROOT = os.path.dirname(__file__)
LLM_MODELS_DIR = os.getenv("LLM_MODELS_DIR", os.path.join(_PROJECT_ROOT, "models", "llm"))

>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e:fetch_llm.py
def download_llm():
    if IN_COLAB:
        print(f"SHIELD ACTIVE: Using Cloud Disk ({LLM_MODEL_DIR}) to protect your local Hard Drive.")
    
    print(f"FETCHING: Edge Legal Reasoner (Phi-3-mini) to {LLM_MODEL_DIR}...")
    try:
        path = hf_hub_download(
            repo_id="microsoft/Phi-3-mini-4k-instruct-gguf",
            filename="Phi-3-mini-4k-instruct-q4.gguf",
<<<<<<< HEAD:scripts/setup/fetch_llm.py
            local_dir=LLM_MODEL_DIR,
=======
            local_dir=LLM_MODELS_DIR,
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e:fetch_llm.py
            token=hf_token
        )
        print(f"SUCCESS: {path}")
    except Exception as e:
        print(f"FAILED_3: {e}")

if __name__ == "__main__":
    download_llm()
