# make_submission_zip.py
"""
CoERS Hackathon 2026 — Official Submission Packager
SmartSalai Edge-Sentinel V4.2 Hardened
"""
import zipfile
import os
from pathlib import Path

SUBMISSION_NAME = "SmartSalai_EdgeSentinel_V4.2_Final.zip"

INCLUDE_DIRS = [
    "agents",
    "core",
    "dashboard",
    "models", # Will be filtered
    "scripts",
    "tests",
    "mobile",
    "mobile_app",
    "config",
    "docs",
]

INCLUDE_FILES = [
    "README.md",
    "requirements.txt",
    "dashboard_api.py",
    "system_orchestrator_v2.py",
    "knowledge_ledger.db", # "Golden Run" findings
    ".env.example",
    "ultimate_test_suite_50.md",
    "manifest.json",
]

EXCLUDE_EXTENSIONS = [".pyc", ".log", ".tmp", ".err", ".db-journal", ".db-wal"]
EXCLUDE_DIRS = ["__pycache__", ".git", ".venv", ".agents", "runs", "tmp", "backups"]

def package():
    print(f"📦 Starting Submission Packaging: {SUBMISSION_NAME}")
    
    with zipfile.ZipFile(SUBMISSION_NAME, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 1. Package Files
        for f in INCLUDE_FILES:
            if os.path.exists(f):
                print(f"  + Adding File: {f}")
                zipf.write(f)
            else:
                print(f"  ! Missing File: {f}")

        # 2. Package Directories
        for d in INCLUDE_DIRS:
            if not os.path.exists(d):
                continue
            
            print(f"  + Traversing Dir: {d}")
            for root, dirs, files in os.walk(d):
                # Filter Dirs
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                
                for file in files:
                    if any(file.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
                        continue
                    
                    # Size Limit: 50MB for single files in zip
                    file_path = os.path.join(root, file)
                    if os.path.getsize(file_path) > 100 * 1024 * 1024:
                        print(f"  ! Skipping Large File: {file_path}")
                        continue
                        
                    zipf.write(file_path)

    print(f"\n✅ Submission Ready -> {SUBMISSION_NAME}")
    size_mb = os.path.getsize(SUBMISSION_NAME) / (1024 * 1024)
    print(f"📦 Archive Size: {size_mb:.2f} MB")

if __name__ == "__main__":
    package()
