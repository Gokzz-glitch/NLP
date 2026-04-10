from huggingface_hub import hf_hub_download
import os
import shutil

print('Downloading YOLOv8 Pothole Model from Hugging Face...')
try:
    model_path = hf_hub_download(repo_id='foduucom/pothole-detection-yolov8', filename='best.pt')
    shutil.copy(model_path, 'yolov8_pothole.pt')
    print('Successfully downloaded custom weights to: yolov8_pothole.pt')
except Exception as e:
    print(f'Error downloading model: {e}')
    print('Falling back to yolov8n.pt if download fails.')
