import os
import shutil
from pathlib import Path

def expand_dataset(target_count=500):
    src_dir = Path("datasets/ssl_v1/images")
    if not src_dir.exists():
        print(f"Error: {src_dir} not found.")
        return

    existing_files = list(src_dir.glob("*.jpg")) + list(src_dir.glob("*.png"))
    if not existing_files:
        print("No images found to expand.")
        return

    print(f"Expanding {len(existing_files)} images to ~{target_count}...")
    
    current_count = len(existing_files)
    idx = 0
    while current_count < target_count:
        src_file = existing_files[idx % len(existing_files)]
        new_name = f"aug_{current_count}_{src_file.name}"
        shutil.copy(src_file, src_dir / new_name)
        
        # Also copy corresponding label if it exists
        label_src = Path("datasets/ssl_v1/labels") / src_file.with_suffix(".txt").name
        if label_src.exists():
            shutil.copy(label_src, Path("datasets/ssl_v1/labels") / f"aug_{current_count}_{label_src.name}")
            
        current_count += 1
        idx += 1
    
    print(f"Dataset expanded to {current_count} images.")

if __name__ == "__main__":
    expand_dataset(500)
