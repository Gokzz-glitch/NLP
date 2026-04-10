import os
from ultralytics import YOLO

try:
    import torch
except ImportError:
    torch = None

def setup_vision_proxy():
    print("PERSONA_3_REPORT: INITIALIZING_YOLO_PROXY.")
    
    # Download standard weights
    model = YOLO("yolov8n.pt")
    
    # Class mapping: COCO -> Indian Traffic Entities (Proxy)
    # COCO Indices: 0: person, 1: bicycle, 2: car, 3: motorcycle, 5: bus, 7: truck
    traffic_mapping = {
        0: "pedestrian",
        1: "bicycle",
        2: "car",
        3: "two-wheeler",
        5: "bus",
        7: "truck",
        9: "auto-rickshaw", # Proxy: mapped from 'traffic light' or similar for testing
    }
    
    print(f"PERSONA_3_REPORT: PROXY_MAPPING_ESTABLISHED: {traffic_mapping}")
    
    # Simulation of Indian Road Entity detection wrapper
    def detect_entities(image_path):
        use_cuda = torch is not None and torch.cuda.is_available()
        if use_cuda:
            model.to('cuda:0')
            model.half() # VRAM Optimization
            results = model(image_path, device=0)
        else:
            results = model(image_path, device='cpu')
        detected = []
        for r in results:
            for box in r.boxes:
                cls = int(box.cls[0])
                label = traffic_mapping.get(cls, "unknown_entity")
                detected.append({"label": label, "conf": float(box.conf[0])})
        return detected

    print("PERSONA_3_REPORT: VISION_PIPELINE_STAGED.")
    return detect_entities

if __name__ == "__main__":
    setup_vision_proxy()
