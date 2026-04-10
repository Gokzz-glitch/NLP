#!/usr/bin/env python3
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
        print("\n" + "="*70)
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
            print(f"\n[Iteration {iteration}]")
            
            if self.train_epoch():
                print(f"⏳ Next training in {interval_seconds}s...")
                time.sleep(interval_seconds)
            else:
                print(f"⚠️ Training failed, retrying in 300s...")
                time.sleep(300)

if __name__ == "__main__":
    loop = ContinuousTrainingLoop()
    loop.run_continuous(interval_seconds=3600)  # Train every hour
