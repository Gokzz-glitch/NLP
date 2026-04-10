from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]


def _norm(path: Path) -> Path:
    return path.resolve()


def first_existing(candidates: Iterable[Path]) -> Optional[Path]:
    for candidate in candidates:
        if candidate.exists():
            return _norm(candidate)
    return None


def first_or_default(candidates: Iterable[Path], default: Path) -> Path:
    found = first_existing(candidates)
    return found if found is not None else _norm(default)


GEMMA_GGUF_CANDIDATES = [
    ROOT / "models" / "llm" / "gemma-2-2b-it-q4_k_m.gguf",
    ROOT / "models" / "llm" / "gemma-2b-it-q4_k_m.gguf",
    ROOT / "raw_data" / "gemma-2-2b-it-q4_k_m.gguf",
    ROOT / "raw_data" / "gemma-2b-it-q4_k_m.gguf",
]

PHI3_GGUF_CANDIDATES = [
    ROOT / "models" / "weights" / "Phi-3-mini-4k-instruct-q4.gguf",
    ROOT / "models" / "llm" / "Phi-3-mini-4k-instruct-q4.gguf",
    ROOT / "raw_data" / "Phi-3-mini-4k-instruct-q4.gguf",
]

POTHOLE_ONNX_CANDIDATES = [
    ROOT / "raw_data" / "indian_potholes_yolov8n.onnx",
    ROOT / "models" / "weights" / "yolov8_pothole.onnx",
    ROOT / "raw_data" / "pothole_v1.onnx",
]

TRAFFIC_SIGNS_ONNX_CANDIDATES = [
    ROOT / "raw_data" / "indian_traffic_signs_yolov8n.onnx",
]

VEHICLES_CHAOS_ONNX_CANDIDATES = [
    ROOT / "raw_data" / "indian_vehicles_chaos_yolov8n.onnx",
    ROOT / "models" / "vision" / "indian_vehicles_chaos_yolov8n.onnx",
]

YOLO_POTHOLE_PT_CANDIDATES = [
    ROOT / "models" / "weights" / "yolov8_pothole_refined.pt",
    ROOT / "models" / "weights" / "yolov8_pothole.pt",
    ROOT / "yolov8_pothole_refined.pt",
    ROOT / "yolov8_pothole.pt",
]

YOLO_GENERAL_PT_CANDIDATES = [
    ROOT / "models" / "weights" / "yolov8n.pt",
    ROOT / "yolov8n.pt",
]


def resolve_gemma_gguf() -> Path:
    return first_or_default(GEMMA_GGUF_CANDIDATES, GEMMA_GGUF_CANDIDATES[0])


def resolve_phi3_gguf() -> Path:
    return first_or_default(PHI3_GGUF_CANDIDATES, PHI3_GGUF_CANDIDATES[0])


def resolve_pothole_onnx() -> Path:
    return first_or_default(POTHOLE_ONNX_CANDIDATES, POTHOLE_ONNX_CANDIDATES[0])


def resolve_traffic_signs_onnx() -> Path:
    return first_or_default(TRAFFIC_SIGNS_ONNX_CANDIDATES, TRAFFIC_SIGNS_ONNX_CANDIDATES[0])


def resolve_vehicles_chaos_onnx() -> Path:
    return first_or_default(VEHICLES_CHAOS_ONNX_CANDIDATES, VEHICLES_CHAOS_ONNX_CANDIDATES[0])


def resolve_yolo_pothole_pt() -> Path:
    return first_or_default(YOLO_POTHOLE_PT_CANDIDATES, YOLO_POTHOLE_PT_CANDIDATES[0])


def resolve_yolo_general_pt() -> Path:
    return first_or_default(YOLO_GENERAL_PT_CANDIDATES, YOLO_GENERAL_PT_CANDIDATES[0])
