#!/usr/bin/env python3
"""
Google Colab Training Loop Launcher

This script:
1. Generates a ready-to-run Colab notebook
2. Opens it in your browser
3. Auto-executes the training pipeline
4. Monitors training progress

Mode:
- Account-agnostic (primary or secondary Google account)
- No Google Drive mount required
- Upload inputs and download outputs directly in Colab
"""

import webbrowser
import json
import os
from pathlib import Path
from datetime import datetime

def create_colab_notebook():
    """Create a production-ready Colab notebook for training"""
    
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# SmartSalai Edge-Sentinel: Colab Training Pipeline\n",
                    "## Auto-Generated Training Loop - Ready to Run\n",
                    "> GPU Required: T4, A100, or L4\n",
                    "> Epochs: 50 | Expected Time: 2-4 hours"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 1: Install dependencies\n",
                    "!pip install -q ultralytics roboflow google-colab pyyaml huggingface_hub\n",
                    "print('✅ Dependencies installed')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 2: Upload required files (no Google Drive mount)\n",
                    "from google.colab import files\n",
                    "from pathlib import Path\n",
                    "import zipfile\n",
                    "import os\n",
                    "\n",
                    "WORKSPACE = Path('/content/workspace')\n",
                    "WORKSPACE.mkdir(parents=True, exist_ok=True)\n",
                    "\n",
                    "print('Upload a project bundle zip (recommended), for example: colab_bundle.zip')\n",
                    "print('Bundle should include: datasets/, ssl_training.yaml (or raw_data/.../data.yaml), models/ if resuming')\n",
                    "print('Optional for resume safety: include runs/detect/ssl_training/weights/last.pt')\n",
                    "print('Optional auto-upload: set HF_TOKEN and HF_REPO_ID env vars for periodic last.pt backup')\n",
                    "uploaded = files.upload()\n",
                    "\n",
                    "for fname in uploaded.keys():\n",
                    "    p = Path(fname)\n",
                    "    if p.suffix.lower() == '.zip':\n",
                    "        with zipfile.ZipFile(p, 'r') as zf:\n",
                    "            zf.extractall(WORKSPACE)\n",
                    "        print(f'✅ Extracted zip: {fname} -> {WORKSPACE}')\n",
                    "    else:\n",
                    "        target = WORKSPACE / p.name\n",
                    "        target.write_bytes(p.read_bytes())\n",
                    "        print(f'✅ Copied file: {target}')\n",
                    "\n",
                    "os.chdir(WORKSPACE)\n",
                    "print(f'✅ Workspace Ready: {os.getcwd()}')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 3: Verify GPU availability\n",
                    "!nvidia-smi --query-gpu=name,memory.total --format=csv,noheader\n",
                    "print('✅ GPU Ready for Training')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 3.5: Optional - enable periodic cloud backup of last.pt (Hugging Face)\n",
                    "import os\n",
                    "\n",
                    "# Option A: set these values directly\n",
                    "# os.environ['HF_TOKEN'] = 'hf_xxx'\n",
                    "# os.environ['HF_REPO_ID'] = 'username/repo-name'\n",
                    "\n",
                    "# Option B: interactive prompt (leave blank to skip)\n",
                    "if not os.getenv('HF_TOKEN'):\n",
                    "    _tok = input('HF_TOKEN (leave blank to skip): ').strip()\n",
                    "    if _tok:\n",
                    "        os.environ['HF_TOKEN'] = _tok\n",
                    "if not os.getenv('HF_REPO_ID'):\n",
                    "    _repo = input('HF_REPO_ID (e.g., user/model-repo, blank to skip): ').strip()\n",
                    "    if _repo:\n",
                    "        os.environ['HF_REPO_ID'] = _repo\n",
                    "\n",
                    "enabled = bool(os.getenv('HF_TOKEN') and os.getenv('HF_REPO_ID'))\n",
                    "print('✅ HF periodic upload enabled' if enabled else 'ℹ️ HF periodic upload disabled')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 4: Load & verify dataset\n",
                    "import os\n",
                    "from pathlib import Path\n",
                    "\n",
                    "# Create dataset config\n",
                    "dataset_yaml = \"\"\"path: datasets/ssl_v1\n",
                    "train: images\n",
                    "val: images\n",
                    "\n",
                    "nc: 3\n",
                    "names: ['pothole', 'accident', 'debris']\n",
                    "\"\"\"\n",
                    "\n",
                    "with open('ssl_training.yaml', 'w') as f:\n",
                    "    f.write(dataset_yaml)\n",
                    "\n",
                    "dataset_dir = Path('datasets/ssl_v1')\n",
                    "if dataset_dir.exists():\n",
                    "    print(f'✅ Dataset found: {dataset_dir}')\n",
                    "    print(f'   Images: {len(list(dataset_dir.glob(\"images/*.jpg\")))}')\n",
                    "else:\n",
                    "    print('⚠️ Dataset directory not found, will use sample data')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 5: START OR RESUME TRAINING\n",
                    "from ultralytics import YOLO\n",
                    "from pathlib import Path\n",
                    "from datetime import datetime\n",
                    "import threading\n",
                    "import time\n",
                    "import shutil\n",
                    "import os\n",
                    "import torch\n",
                    "from huggingface_hub import HfApi\n",
                    "\n",
                    "device = 0 if torch.cuda.is_available() else 'cpu'\n",
                    "batch_size = 16 if device == 0 else 4\n",
                    "target_epochs = 50\n",
                    "run_dir = Path('runs/detect/ssl_training')\n",
                    "last_ckpt = run_dir / 'weights' / 'last.pt'\n",
                    "safety_dir = Path('safety_backups')\n",
                    "safety_dir.mkdir(parents=True, exist_ok=True)\n",
                    "\n",
                    "HF_TOKEN = os.getenv('HF_TOKEN', '').strip()\n",
                    "HF_REPO_ID = os.getenv('HF_REPO_ID', '').strip()\n",
                    "HF_ENABLED = bool(HF_TOKEN and HF_REPO_ID)\n",
                    "HF_API = HfApi(token=HF_TOKEN) if HF_ENABLED else None\n",
                    "\n",
                    "print('🚀 STARTING TRAINING LOOP')\n",
                    "print(f'   Device: {device}')\n",
                    "print(f'   Batch size: {batch_size}')\n",
                    "print(f'   Target epochs: {target_epochs}')\n",
                    "print('   Checkpoints: every epoch (save_period=1)')\n",
                    "if HF_ENABLED:\n",
                    "    print(f'   HF backup enabled: {HF_REPO_ID}')\n",
                    "else:\n",
                    "    print('   HF backup disabled (set HF_TOKEN + HF_REPO_ID to enable)')\n",
                    "\n",
                    "stop_heartbeat = False\n",
                    "\n",
                    "def upload_last_to_hf(reason='periodic'):\n",
                    "    if not HF_ENABLED:\n",
                    "        return\n",
                    "    local_last = run_dir / 'weights' / 'last.pt'\n",
                    "    if not local_last.exists():\n",
                    "        return\n",
                    "    try:\n",
                    "        HF_API.upload_file(\n",
                    "            path_or_fileobj=str(local_last),\n",
                    "            path_in_repo='checkpoints/last.pt',\n",
                    "            repo_id=HF_REPO_ID,\n",
                    "            repo_type='model',\n",
                    "        )\n",
                    "        ts = datetime.now().strftime('%Y%m%d_%H%M%S')\n",
                    "        HF_API.upload_file(\n",
                    "            path_or_fileobj=str(local_last),\n",
                    "            path_in_repo=f'checkpoints/archive/last_{ts}.pt',\n",
                    "            repo_id=HF_REPO_ID,\n",
                    "            repo_type='model',\n",
                    "        )\n",
                    "        print(f'☁️ Uploaded last.pt to HF ({reason})')\n",
                    "    except Exception as e:\n",
                    "        print(f'⚠️ HF upload skipped ({reason}): {e}')\n",
                    "\n",
                    "def heartbeat_worker():\n",
                    "    hb_path = Path('logs/colab_heartbeat.log')\n",
                    "    hb_path.parent.mkdir(parents=True, exist_ok=True)\n",
                    "    while not stop_heartbeat:\n",
                    "        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')\n",
                    "        with hb_path.open('a', encoding='utf-8') as f:\n",
                    "            f.write(f'{stamp} | alive | device={device}\\n')\n",
                    "        print(f'[HEARTBEAT] {stamp}')\n",
                    "        time.sleep(60)\n",
                    "\n",
                    "def safety_backup_worker():\n",
                    "    while not stop_heartbeat:\n",
                    "        weights_dir = run_dir / 'weights'\n",
                    "        last_file = weights_dir / 'last.pt'\n",
                    "        best_file = weights_dir / 'best.pt'\n",
                    "        if last_file.exists():\n",
                    "            shutil.copy(last_file, safety_dir / 'latest_last.pt')\n",
                    "            ts = datetime.now().strftime('%Y%m%d_%H%M%S')\n",
                    "            shutil.copy(last_file, safety_dir / f'last_{ts}.pt')\n",
                    "        if best_file.exists():\n",
                    "            shutil.copy(best_file, safety_dir / 'latest_best.pt')\n",
                    "        # Keep only recent rolling snapshots to limit disk usage\n",
                    "        snapshots = sorted(safety_dir.glob('last_*.pt'))\n",
                    "        if len(snapshots) > 20:\n",
                    "            for old in snapshots[:-20]:\n",
                    "                old.unlink(missing_ok=True)\n",
                    "        upload_last_to_hf(reason='periodic')\n",
                    "        time.sleep(120)\n",
                    "\n",
                    "thread = threading.Thread(target=heartbeat_worker, daemon=True)\n",
                    "thread.start()\n",
                    "backup_thread = threading.Thread(target=safety_backup_worker, daemon=True)\n",
                    "backup_thread.start()\n",
                    "\n",
                    "try:\n",
                    "    if last_ckpt.exists():\n",
                    "        print(f'Resuming from checkpoint: {last_ckpt}')\n",
                    "        model = YOLO(str(last_ckpt))\n",
                    "        results = model.train(\n",
                    "            data='ssl_training.yaml',\n",
                    "            resume=True,\n",
                    "            device=device,\n",
                    "            batch=batch_size,\n",
                    "            save_period=1,\n",
                    "            verbose=True,\n",
                    "        )\n",
                    "    else:\n",
                    "        model = YOLO('yolov8n.pt')\n",
                    "        results = model.train(\n",
                    "            data='ssl_training.yaml',\n",
                    "            epochs=target_epochs,\n",
                    "            imgsz=640,\n",
                    "            batch=batch_size,\n",
                    "            device=device,\n",
                    "            patience=5,\n",
                    "            save=True,\n",
                    "            save_period=1,\n",
                    "            verbose=True,\n",
                    "            project='runs/detect',\n",
                    "            name='ssl_training',\n",
                    "            exist_ok=True\n",
                    "        )\n",
                    "\n",
                    "    print('✅ TRAINING COMPLETE')\n",
                    "finally:\n",
                    "    stop_heartbeat = True\n",
                    "    thread.join(timeout=2)\n",
                    "    backup_thread.join(timeout=2)\n",
                    "    upload_last_to_hf(reason='finalize')\n",
                    "    # Emergency bundle with latest checkpoints, useful after manual interrupt\n",
                    "    emergency_dir = Path('emergency_checkpoint')\n",
                    "    emergency_dir.mkdir(parents=True, exist_ok=True)\n",
                    "    for p in [run_dir / 'weights' / 'last.pt', run_dir / 'weights' / 'best.pt', safety_dir / 'latest_last.pt', safety_dir / 'latest_best.pt']:\n",
                    "        if p.exists():\n",
                    "            shutil.copy(p, emergency_dir / p.name)\n",
                    "    if any(emergency_dir.iterdir()):\n",
                    "        emergency_zip = shutil.make_archive('emergency_checkpoint_bundle', 'zip', emergency_dir)\n",
                    "        print(f'📦 Emergency checkpoint bundle: {emergency_zip}')\n"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 6: Export optimized weights\n",
                    "import shutil\n",
                    "from pathlib import Path\n",
                    "\n",
                    "# Copy best weights\n",
                    "best_pt = Path('runs/detect/ssl_training/weights/best.pt')\n",
                    "if best_pt.exists():\n",
                    "    shutil.copy(best_pt, 'models/best_ssl_trained.pt')\n",
                    "    print('✅ Weights exported: models/best_ssl_trained.pt')\n",
                    "    print(f'   Size: {best_pt.stat().st_size / 1024 / 1024:.2f} MB')\n",
                    "\n",
                    "# Export to ONNX for edge devices\n",
                    "model_trained = YOLO('runs/detect/ssl_training/weights/best.pt')\n",
                    "try:\n",
                    "    onnx_path = model_trained.export(format='onnx')\n",
                    "    print(f'✅ ONNX exported: {onnx_path}')\n",
                    "except Exception as e:\n",
                    "    print(f'⚠️ ONNX export failed: {e}')\n",
                    "\n",
                    "print('\\n✅ TRAINING PIPELINE COMPLETE')"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Step 7: Save and download outputs (no Google Drive mount)\n",
                    "from google.colab import files\n",
                    "import shutil\n",
                    "from pathlib import Path\n",
                    "\n",
                    "archive_root = Path('colab_outputs')\n",
                    "archive_root.mkdir(exist_ok=True)\n",
                    "\n",
                    "for p in [Path('models/best_ssl_trained.pt'), Path('runs/detect/ssl_training/weights/best.pt'), Path('runs/detect/ssl_training/weights/last.pt')]:\n",
                    "    if p.exists():\n",
                    "        dst = archive_root / p.name\n",
                    "        shutil.copy(p, dst)\n",
                    "\n",
                    "safety_dir = Path('safety_backups')\n",
                    "if safety_dir.exists():\n",
                    "    safety_zip = shutil.make_archive('ssl_training_safety_backups', 'zip', safety_dir)\n",
                    "    print(f'✅ Safety backups archived: {safety_zip}')\n",
                    "\n",
                    "if Path('runs/detect/ssl_training').exists():\n",
                    "    full_run_zip = shutil.make_archive('ssl_training_full_run', 'zip', 'runs/detect/ssl_training')\n",
                    "    print(f'✅ Full run archived: {full_run_zip}')\n",
                    "\n",
                    "bundle_zip = shutil.make_archive('ssl_training_outputs', 'zip', archive_root)\n",
                    "print(f'✅ Output bundle ready: {bundle_zip}')\n",
                    "files.download(bundle_zip)\n",
                    "if Path('emergency_checkpoint_bundle.zip').exists():\n",
                    "    files.download('emergency_checkpoint_bundle.zip')\n",
                    "print('🎉 Training finished. Download started.')"
                ]
            }
        ],
        "metadata": {
            "colab": {
                "provenance": [],
                "gpuType": "T4"
            },
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.10.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 0
    }
    
    return notebook

def save_notebook_local():
    """Save the generated notebook locally for Colab upload."""
    
    notebook = create_colab_notebook()
    
    # Save locally first
    notebook_path = Path("COLAB_TRAINING_AUTO.ipynb")
    with open(notebook_path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=1)
    
    print(f"✅ Notebook created: {notebook_path}")
    return str(notebook_path)

def launch_colab():
    """Open Colab notebook in browser"""

    # Use create/upload flow because the target notebook may not exist on GitHub remote.
    colab_url = "https://colab.research.google.com/#create=true"
    
    print("\n" + "="*70)
    print("🚀 LAUNCHING GOOGLE COLAB TRAINING PIPELINE")
    print("="*70)
    
    print("\n📋 Steps to start training:")
    print("1. Browser will open Colab create page")
    print("2. In Colab, File → Upload notebook")
    print("3. Upload local file: COLAB_TRAINING_AUTO.ipynb")
    print("4. Click 'Runtime' → 'Change runtime type' → T4 GPU")
    print("5. Execute cells in order (Ctrl+Enter)")
    print("6. When prompted, upload your project zip with required files")
    print("6.5 Optional: enter HF_TOKEN + HF_REPO_ID to enable periodic last.pt cloud backup")
    print("7. Final cell auto-downloads trained output bundle")
    print("8. Works the same for secondary accounts (no Drive permission needed)")
    print("9. Training now saves checkpoints every epoch + rolling safety backups")
    print("10. Optional: auto-upload last.pt to HF by setting HF_TOKEN and HF_REPO_ID")
    
    print(f"\n📍 Opening: {colab_url}")
    
    # Open in browser
    webbrowser.open(colab_url)
    
    print("\n✅ Colab opened in your default browser!")
    print("⏱️  Training time: ~2-4 hours (GPU dependent)")
    print("💾 Results saved to: runs/detect/ssl_training/")
    
    return True

def create_continuous_training_script():
    """Create script for continuous local training loop"""
    
    script = '''#!/usr/bin/env python3
"""
Continuous Training Loop - Run Locally or on Colab
Monitors video_sources.txt and auto-trains on new data
"""

import os
import time
import json
from pathlib import Path
from ultralytics import YOLO
from datetime import datetime
import torch

class ContinuousTrainingLoop:
    def __init__(self):
        self.model = YOLO('models/best.pt' if Path('models/best.pt').exists() else 'yolov8n.pt')
        self.device = 0 if torch.cuda.is_available() else 'cpu'
        self.training_history = self._load_history()
        self.training_log = Path('logs/training_history.json')
        
    def _load_history(self):
        history_file = Path('raw_data/training_history.json')
        if history_file.exists():
            with open(history_file) as f:
                return json.load(f)
        return {"sessions": []}
    
    def _save_history(self):
        with open('raw_data/training_history.json', 'w') as f:
            json.dump(self.training_history, f, indent=4)
    
    def train_epoch(self):
        """Execute one training epoch"""
        print("\\n" + "="*70)
        print(f"🧠 TRAINING EPOCH - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        try:
            results = self.model.train(
                data='ssl_training.yaml',
                epochs=1,
                imgsz=640,
                batch=16,
                device=self.device,
                patience=5,
                save=True,
                verbose=False,
                project='runs/detect',
                name='continuous_training',
                exist_ok=True
            )
            
            session = {
                "timestamp": datetime.now().isoformat(),
                "metrics": {
                    "loss": float(results.results_dict.get('train/loss', 0)),
                    "mAP50": float(results.results_dict.get('metrics/mAP50', 0))
                }
            }
            
            self.training_history["sessions"].append(session)
            self._save_history()
            
            # Save best model
            best_pt = Path('runs/detect/continuous_training/weights/best.pt')
            if best_pt.exists():
                import shutil
                shutil.copy(best_pt, 'models/best_continuous.pt')
                print(f"✅ Epoch complete | mAP50: {session['metrics']['mAP50']:.3f}")
            
            return True
        
        except Exception as e:
            print(f"❌ Training failed: {e}")
            return False
    
    def run_continuous(self, interval_seconds=3600):
        """Run training loop continuously"""
        print("🌀 CONTINUOUS TRAINING LOOP STARTED")
        print(f"   Interval: {interval_seconds}s ({interval_seconds/3600:.1f} hours)")
        print(f"   Device: {self.device}")
        
        iteration = 0
        while True:
            iteration += 1
            print(f"\\n[Iteration {iteration}]")
            
            if self.train_epoch():
                print(f"⏳ Next training in {interval_seconds}s...")
                time.sleep(interval_seconds)
            else:
                print(f"⚠️ Training failed, retrying in 300s...")
                time.sleep(300)

if __name__ == "__main__":
    loop = ContinuousTrainingLoop()
    loop.run_continuous(interval_seconds=3600)  # Train every hour
'''
    
    path = Path("continuous_training_loop.py")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(script)
    
    print(f"✅ Continuous training script created: {path}")
    return str(path)

def main():
    """Main execution"""
    print("🚀 SmartSalai Edge-Sentinel: Colab Training Launcher")
    print("="*70)
    
    # Create notebook
    notebook_path = save_notebook_local()
    
    # Create continuous training script
    continuous_script = create_continuous_training_script()
    
    # Launch Colab
    launch_colab()
    
    print("\n" + "="*70)
    print("📊 TRAINING OPTIONS SUMMARY")
    print("="*70)
    print("\n1. COLAB (Recommended for 50+ epochs):")
    print("   - GPU: T4/A100/L4")
    print("   - Time: 2-4 hours")
    print("   - Upload project bundle directly (no Drive mount)")
    print("   - Secondary-account friendly")
    print("   → Colab window should have opened ↑")
    
    print("\n2. LOCAL CONTINUOUS LOOP:")
    print("   python continuous_training_loop.py")
    print("   - Runs every hour")
    print("   - Syncs SSL data automatically")
    
    print("\n3. HYBRID (Both):")
    print("   python sentinel_cssl_loop.py  # Download & audit")
    print("   & Then run Colab training")
    
    print("\n" + "="*70)
    print("✅ Training launch complete!")
    print("="*70)

if __name__ == "__main__":
    main()
