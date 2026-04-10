import os
import zipfile
from pathlib import Path

# Final Submission Metadata
PROJECT_NAME = "SmartSalai_Edge-Sentinel_v1.2.3"
OUTPUT_ZIP = f"{PROJECT_NAME}_CoERS2026.zip"

# What to EXCLUDE (Heavy or Local-specific)
EXCLUDES = [
    "datasets",
    ".venv",
    "runs",
    "tmp",
    "__pycache__",
    ".git",
    ".gemini",
    "node_modules",
    "tmp_stress_data",
    "test_real_world.py",
    "unfiltered_identity_audit.md",
    ".dashboard_secret",
    "*.log",
    "*.pyc",
    "*.bak",
    "*.jpg", # Global image exclude for source zip
    "*.png",
    "*.mp4"
]

# What to INCLUDE (Core Source & Docs)
INCLUDES = [
    "agents",
    "core",
    "dashboard",
    "models",
    "dashboard_api.py",
    "system_orchestrator_v2.py",
    "continuous_training_loop.py",
    "requirements.txt",
    "README.md",
    "knowledge_ledger.db",
    ".env.example",
    "verify_firebase.py"
]

def make_zip():
    print(f"📦 Packaging {PROJECT_NAME} for CoERS 2026...")
    
    with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 1. Walk the directory
        for root, dirs, files in os.walk('.'):
            # Prune excluded directories in-place for os.walk
            dirs[:] = [d for d in dirs if d not in EXCLUDES and not d.startswith('.')]
            
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to('.')
                
                # Exclusion patterns (extensions)
                if any(file.endswith(ext.replace('*', '')) for ext in EXCLUDES if '*' in ext):
                    continue
                if file in EXCLUDES:
                    continue
                
                # [SECURITY & SIZE FIX]: Deep Models Exclusion
                # We only want top-level weights in 'models/', no nested datasets.
                if rel_path.parts[0] == "models" and len(rel_path.parts) > 2:
                    continue
                if rel_path.parts[0] == "models" and not (file.endswith(".pt") or file.endswith(".onnx")):
                    continue
                
                # Inclusion check
                # If it's in a top-level folder we want, include it.
                # If it's a top-level file we want, include it.
                parts = rel_path.parts
                if not parts: continue
                
                top_level = parts[0]
                if top_level in INCLUDES:
                    print(f"  + Adding {rel_path}")
                    zipf.write(file_path, rel_path)
                elif len(parts) == 1 and file in INCLUDES:
                     # Top level files
                    print(f"  + Adding {rel_path}")
                    zipf.write(file_path, rel_path)

    size_mb = os.path.getsize(OUTPUT_ZIP) / (1024 * 1024)
    print(f"\n✅ SUBMISSION READY: {OUTPUT_ZIP} ({size_mb:.2f} MB)")

if __name__ == "__main__":
    make_zip()
