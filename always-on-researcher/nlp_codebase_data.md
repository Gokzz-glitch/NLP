# NLP Codebase Data Extraction

## README.md (Main Purpose & Overview)

SmartSalai Edge-Sentinel is an edge-native, offline-first, multi-agent AI framework that acts as a proactive bio-legal shield for two-wheeler drivers in Tamil Nadu. It combines real-time computer vision, sensor fusion, and statutory law to protect drivers from both physical harm and legal liability — entirely on-device.

- Hardware Target: Android mid-range NPU (Dimensity 700 / SD 680 class)
- Inference Backend: ONNX Runtime NNAPI delegate — INT8 quantized
- Vision Model: YOLOv8-nano (IDD-trained weights only)
- IMU Model: TCN (3-layer dilated, receptive field 1.2 s, 6-DOF @100 Hz)
- Language: AI4Bharat IndicTrans2 / Bhashini offline TTS
- Cloud Dependency: ZERO (all inference on-device)
- Privacy: ZKP envelope (Pedersen Commitment) on all telemetry emits
- Legal Dataset: MoRTH Gazette S.O. 2224(E); TN G.O.(Ms).No.56/2022
- Telemetry Schema: iRAD (MoRTH Integrated Road Accident Database, 2022)

## Core Python Files

### agents/imu_near_miss_detector.py
- Fuses 6-DOF IMU telemetry (3-axis accelerometer + gyroscope) via a Temporal Convolutional Network (TCN) to detect "Near-Miss" behavioral anomalies in real-time on-device.
- Hardware target: Android NPU, ONNX Runtime with NNAPI delegate (INT8 quantized)
- Zero cloud API calls, privacy-preserving, iRAD-schema-compatible output.

### section_208_resolver.py
- Protocol to challenge infrastructure infractions based on legal precedents (e.g. MVA 2019).
- Generates audit requests for unlawful enforcement infrastructure (e.g., speed cameras without signage).

### vision_system_setup.py
- Sets up YOLOv8 vision proxy for Indian traffic entity detection.
- Maps COCO indices to Indian traffic entities.

### etl/pdf_extractor.py
- Extracts text from government legal PDFs using pdfplumber and Tesseract OCR fallback.
- Handles multi-column, bilingual (Hindi/Tamil/English) scanned gazettes.

### etl/pipeline.py
- Unified ETL pipeline: monitors /raw_data, executes extract → chunk → embed → ingest.
- Thread-safe, multi-file batch, retry logic for OCR failures.

### edge_vector_store.py
- Local vector store for legal text embeddings using SentenceTransformer.
- Supports legal statute queries and ingestion.

### offline_tts_manager.py
- Sub-100ms latency voice interface using pyttsx3.
- Implements interrupt system for critical hazard TTS overrides.

### ingest_legal_pdfs.py
- Ingests legal PDFs, extracts and chunks text, stores in vector DB.

### fetch_vision_models.py / finalize_models.py
- Downloads and exports vision models (YOLOv8) and LLMs for edge deployment.

### Additional Files
- README.md: Project overview, architecture, Kanban board, quick start.
- tasks.md: Kanban board for project management.
- CHANGELOG.md: Project changelog.

---

(Extracted by Scraper Agent using Firecrawl skill)
