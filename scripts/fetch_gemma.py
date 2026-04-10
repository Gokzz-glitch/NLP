import os
import shutil
from pathlib import Path
from huggingface_hub import hf_hub_download
from dotenv import load_dotenv

load_dotenv()
hf_token = os.getenv("HF_TOKEN")

def download_gemma():
    print("FETCHING: gemma-2b-it-q4_k_m.gguf...")
    try:
        target_dir = Path("models/llm")
        target_dir.mkdir(parents=True, exist_ok=True)
        canonical_path = target_dir / "gemma-2-2b-it-q4_k_m.gguf"

        # Using a reliable community repo for Gemma GGUF
        path = hf_hub_download(
            repo_id="bartowski/gemma-2b-it-GGUF",
            filename="gemma-2b-it-q4_k_m.gguf",
            local_dir=str(target_dir),
            token=hf_token
        )

        downloaded = Path(path)
        if downloaded.resolve() != canonical_path.resolve():
            shutil.copy2(downloaded, canonical_path)

        print(f"SUCCESS: {canonical_path}")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    download_gemma()
