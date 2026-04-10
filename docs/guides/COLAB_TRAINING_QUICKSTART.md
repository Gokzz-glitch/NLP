# Colab Training Launch Guide

## Quick Start (Using Your Colab Extension)

### Option 1: Run Launcher Script (Easiest)
```bash
python colab_training_launcher.py
```

This will:
1. ✅ Generate `COLAB_TRAINING_AUTO.ipynb` 
2. ✅ Open Colab in your browser
3. ✅ Display training instructions
4. ✅ GPU: T4/A100/L4 supported
5. ✅ Training time: 2-4 hours (50 epochs)

### Option 2: Use Colab Extension Directly
1. Open VS Code Command Palette: `Ctrl+Shift+P`
2. Search for "Colab" or "Google Colaboratory"
3. Select notebook to open in Colab
4. Your extension will handle the connection

### Option 3: Manual Colab Connection
1. Open [Google Colab](https://colab.research.google.com)
2. File → Open notebook → GitHub tab
3. Search: `Gokzz-glitch/NLP`
4. Select `SENTINEL_COLAB_RUNNER.ipynb`
5. Click Play button to execute

---

## Training Pipeline Steps

### Cell 1: Dependencies
```python
!pip install -q ultralytics roboflow google-colab pyyaml
```

### Cell 2: Mount Drive
```python
drive.mount('/content/drive')
# Connects to your Google Drive with NLP project
```

### Cell 3: GPU Check
```python
!nvidia-smi
# Verifies T4/A100/L4 GPU is available
```

### Cell 4: Dataset Configuration
```yaml
path: datasets/ssl_v1
train: images
val: images
nc: 3
names: ['pothole', 'accident', 'debris']
```

### Cell 5: Start Training (Main Loop)
```python
model = YOLO('yolov8n.pt')
results = model.train(
    data='ssl_training.yaml',
    epochs=50,
    imgsz=640,
    batch=16,
    device=0,
    patience=5
)
```
⏱️ **Expected duration: 2-4 hours**

### Cell 6: Export Weights
```python
# Saves to:
# - models/best_ssl_trained.pt (PyTorch)
# - models/best_ssl_trained.onnx (Edge devices)
```

### Cell 7: Sync Back
```python
# Auto-syncs trained models to your local Drive
# Available in: runs/detect/ssl_training/
```

---

## Local Continuous Training

For non-stop training loop on local machine:
```bash
python continuous_training_loop.py
```

Trains every 1 hour, saves checkpoints, logs metrics.

---

## Important Notes

⚠️ **GPU Requirements:**
- Minimum: T4 (12GB)
- Recommended: A100 (40GB)
- Colab free T4 is sufficient for 50 epochs

🔗 **Drive Sync:**
- Project must be in: `/content/drive/My Drive/NLP`
- Models auto-sync back after training

📊 **Monitoring:**
- Watch TensorBoard metrics in Colab
- Results saved to `runs/detect/ssl_training/`
- Best weights: `weights/best.pt`

🛑 **If Training Stops:**
1. Check GPU memory: `!nvidia-smi`
2. Reduce batch size in Cell 5 (try 8 instead of 16)
3. Restart runtime: Runtime → Factory reset

---

## After Training Completes

✅ Models available:
- **PyTorch**: `runs/detect/ssl_training/weights/best.pt`
- **ONNX** (for edge): `runs/detect/ssl_training/weights/best.onnx`
- **Local copy**: `models/best_ssl_trained.pt`

📈 **Metrics logged in**:
- `runs/detect/ssl_training/results.csv`
- `runs/detect/ssl_training/results.png`

🚀 **Next steps**:
1. Download trained model to local machine
2. Run `test_real_world.py` with new model
3. Deploy to edge devices via `vision_system_setup.py`

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Dataset not found" | Check `datasets/ssl_v1/` exists with images |
| "GPU not available" | Change runtime type to T4 GPU |
| "Out of memory" | Reduce batch size from 16 to 8 |
| "Training too slow" | Check GPU load with `nvidia-smi` |
| "Models not syncing" | Verify Drive mounted as `/content/drive` |

---

**Status**: ✅ Colab training launcher ready to execute
**Notebook**: `COLAB_TRAINING_AUTO.ipynb` (auto-generated)
**Session time**: ~2-4 hours (GPU dependent)
