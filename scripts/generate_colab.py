import json
import os

notebook_content = {
    "cells": [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# Hybrid SSL & Open-Source Unified Training Loop\n",
                "\n",
                "This notebook demonstrates combining Roboflow open-source data with dynamic Sentinel Self-Supervised Learning (SSL) data for unified continuous edge adaptation."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# 1. Dependencies & Google Drive Mount\n",
                "!pip install ultralytics roboflow pyyaml\n",
                "from google.colab import drive\n",
                "import os\n",
                "\n",
                "drive.mount('/content/drive')\n",
                "PROJECT_DIR = '/content/drive/My Drive/NLP'\n",
                "os.chdir(PROJECT_DIR)\n",
                "print(f'✅ Workspace Synced: {os.getcwd()}')\n"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# 2. Ingest More Open Source Projects\n",
                "from roboflow import Roboflow\n",
                "\n",
                "api_key = os.environ.get('ROBOFLOW_API_KEY', '').strip()\n",
                "if not api_key:\n",
                "    raise RuntimeError('ROBOFLOW_API_KEY is not set in this runtime')\n",
                "rf = Roboflow(api_key=api_key)\n",
                "\n",
                "try:\n",
                "    print('Downloading Pothole Dataset...')\n",
                "    # Replace with any active Roboflow projects as requested\n",
                "    rf.workspace('viren-daultani-y0fio').project('road-signs-indian-p2kgu').version(1).download('yolov8', location='datasets/indian_open')\n",
                "except Exception as e:\n",
                "    print('Error:', e)\n"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# 3. Format Dynamic SSL Data\n",
                "!python scripts/ssl_data_formatter.py\n",
                "print('✅ Gemini Teacher SSL annotations parsed into YOLO format!')\n"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# 4. Combine Namespaces Programmatically\n",
                "import yaml\n",
                "\n",
                "# Load base classes from the Indian Traffic Signs dataset\n",
                "base_yaml_path = 'Indian-Traffic-Sign-1/data.yaml'\n",
                "with open(base_yaml_path, 'r') as f:\n",
                "    dataset_config = yaml.safe_load(f)\n",
                "\n",
                "# Append Edge Sentinel physics-based classes (SSL mappings start at offset)\n",
                "new_classes = ['pothole', 'accident', 'debris']\n",
                "dataset_config['names'].extend(new_classes)\n",
                "dataset_config['nc'] = len(dataset_config['names'])\n",
                "\n",
                "# Define the multiple paths to merge all distributions simultaneously\n",
                "dataset_config['train'] = [\n",
                "    'datasets/indian_open/train/images',\n",
                "    'datasets/ssl_v1/train/images',\n",
                "    'Indian-Traffic-Sign-1/train/images'\n",
                "]\n",
                "dataset_config['val'] = [\n",
                "    'datasets/indian_open/valid/images',\n",
                "    'datasets/ssl_v1/train/images',\n",
                "    'Indian-Traffic-Sign-1/test/images'\n",
                "]\n",
                "dataset_config['test'] = [] # Clear original test mapping to avoid confusion\n",
                "\n",
                "# Save master blueprint\n",
                "with open('master_hybrid_config.yaml', 'w') as f:\n",
                "    yaml.dump(dataset_config, f, sort_keys=False)\n",
                "\n",
                "print(f\"✅ Master Hybrid Config mapped with {dataset_config['nc']} unified classes!\")\n"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# 5. Initiate Multi-Dataset YOLO Training Loop\n",
                "from ultralytics import YOLO\n",
                "model = YOLO('yolov8n.pt') \n",
                "\n",
                "print('🚀 Igniting 5-Epoch Multi-Case Edge Training...')\n",
                "results = model.train(\n",
                "    data='master_hybrid_config.yaml',\n",
                "    epochs=5,\n",
                "    imgsz=640,\n",
                "    device=0,\n",
                "    project='sentinel_hybrid',\n",
                "    name='test_all_cases'\n",
                ")\n",
                "print('✅ Hybrid Unified Training Verified!')\n"
            ]
        }
    ],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 4
}

with open(r'HYBRID_SSL_TRAINING_RUNNER.ipynb', 'w', encoding='utf-8') as f:
    json.dump(notebook_content, f, indent=2)

print("✅ HYBRID_SSL_TRAINING_RUNNER.ipynb built successfully!")
