import os
from huggingface_hub import hf_hub_download
from dotenv import load_dotenv

load_dotenv()
hf_token = os.getenv("HF_TOKEN")

def download_gemma_bafs():
    repo_id = "BafS/gemma-2-2b-it-Q4_K_M-GGUF"
    filename = "gemma-2-2b-it-q4_k_m.gguf"
    local_dir = "models/llm"
    
    print(f"FETCHING: {filename} from {repo_id}...")
    try:
        path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=local_dir,
            token=hf_token
        )
        print(f"SUCCESS: {path}")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    download_gemma_bafs()
