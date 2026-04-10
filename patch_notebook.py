import json
import os

path = r'g:\My Drive\NLP\notebooks\training\SENTINEL_COLAB_HEAVY_V3.ipynb'
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        nb = json.load(f)
    
    # Cell indices are 0-based. Cell 4 is index 4.
    nb['cells'][4]['source'] = [
        "import torch\n",
        "DEVICE = 'cuda:0' if torch.cuda.is_available() else 'cpu'\n",
        "if DEVICE == 'cpu':\n",
        "    print('⚠️ WARNING: GPU not available. Falling back to CPU. Training will be SLOW.')\n",
        "\n",
        "# ─── Cell 4: ULTRA HEAVY TRAINING (YOLOv8l) ────────────────────────────────\n",
        "model = YOLO(STARTING_WEIGHTS)\n",
        "results = model.train(\n",
        "    data=yaml_path,\n",
        "    epochs=500,\n",
        "    imgsz=1280,\n",
        "    batch=8,\n",
        "    device=DEVICE,\n",
        "    workers=8 if DEVICE != 'cpu' else 1,\n",
        "    patience=100,\n",
        "    save=True,\n",
        "    cache=True,\n",
        "    amp=(DEVICE != 'cpu'),\n",
        "    cos_lr=True,\n",
        "    close_mosaic=100,\n",
        "    augment=True,\n",
        "    mixup=0.2,\n",
        "    degrees=10.0,\n",
        "    project='/content/drive/MyDrive/NLP/runs/detect/sentinel_audit',\n",
        "    name='heavy_v3',\n",
        "    exist_ok=True\n",
        ")\n",
        "print('✅ V3 TRAINING COMPLETE')"
    ]
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1)
    print("Notebook patched successfully.")
else:
    print(f"File not found: {path}")
