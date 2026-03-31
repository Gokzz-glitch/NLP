import os
from huggingface_hub import hf_hub_download
from dotenv import load_dotenv

load_dotenv()
hf_token = os.getenv("HF_TOKEN")

def download_llm():
    print("FETCHING: Edge Legal Reasoner (Phi-3-mini)...")
    try:
        # phi-3-mini-4k-instruct-q4.gguf
        # Using bartowski's repo as it's the standard for GGUF/K-Quants
        path = hf_hub_download(
            repo_id="microsoft/Phi-3-mini-4k-instruct-gguf",
            filename="Phi-3-mini-4k-instruct-q4.gguf",
            local_dir="g:/My Drive/NLP/models/llm",
            token=hf_token
        )
        print(f"SUCCESS: {path}")
    except Exception as e:
        print(f"FAILED_3: {e}")

if __name__ == "__main__":
    download_llm()
