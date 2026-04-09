import time
import json
import logging
from agents.imu_near_miss_detector import NearMissDetector, IMUSample
from section_208_resolver import Section208Resolver
from offline_tts_manager import OfflineTTSManager
from edge_vector_store import EdgeVectorStore
from vision_audit import VisionAuditEngine

# Configure Orchestrator Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: [ORCHESTRATOR] %(message)s")

class SmartSalaiOrchestrator:
    def __init__(self):
        self.detector = NearMissDetector()
        self.resolver = Section208Resolver()
        self.tts = OfflineTTSManager()
        self._initialize_components()

    def _initialize_components(self):
        logging.info("INITIALIZING_AGENT_PIPELINE.")
        self.detector.load()

        # Vision engine — graceful fallback to mock mode if model absent
        try:
            self.vision = VisionAuditEngine()
            if self.vision.is_mock:
                logging.warning(
                    "VISION_ENGINE_MOCK_MODE. Set VISION_MODEL_PATH to enable real inference."
                )
        except Exception:
            logging.warning("VISION_ENGINE_INIT_FAILED. Continuing without vision.")
            self.vision = None

        # Legal RAG vector store
        try:
            self.vector_store = EdgeVectorStore()
        except Exception:
            logging.warning("VECTOR_STORE_INIT_FAILED. FALLING_BACK_TO_MOCK.")
            self.vector_store = None

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    def process_sensor_frame(self, imu_sample, vision_objects=None, raw_frame=None):
        """
        Main loop logic for routing data between agents.

        Args:
            imu_sample     : IMUSample object from the 100 Hz acquisition loop.
            vision_objects : Pre-detected objects as list of dicts (label, conf).
                             If None and raw_frame is provided, vision inference
                             is run in-line. If both None, skip vision checks.
            raw_frame      : Raw BGR numpy frame from camera (optional).
        """
        # 1. Run vision inference if raw frame provided and no pre-computed objects
        if vision_objects is None and raw_frame is not None and self.vision is not None:
            try:
                vision_objects = self.vision.run_inference(raw_frame)
            except Exception as exc:
                logging.warning(f"VISION_INFERENCE_ERROR: {exc}")
                vision_objects = []

        if vision_objects is None:
            vision_objects = []

        # 2. IMU Near-Miss Check (Persona 3)
        event = self.detector.push_sample(imu_sample)

        if event:
            # 3. Legal Audit (Persona 2) — check camera vs signage
            has_camera  = any(obj.get('label') == 'speed_camera'     for obj in vision_objects)
            has_signage = any(obj.get('label') == 'speed_limit_sign'  for obj in vision_objects)

            if has_camera:
                audit = self.resolver.challenge_speed_camera(
                    {"lat": 12.0, "lon": 80.0, "type": "speed_camera"},
                    has_signage,
                )
                if audit['status'] == 'CHALLENGE_GENERATED':
                    logging.warning(f"LEGAL_INFRASTRUCTURE_CHALLENGE: {audit['legal_basis']}")
                    self.tts.announce_hazard(
                        "Warning: Speed enforcement infrastructure lacks signage. Evidence challenged.",
                        critical=True,
                    )
                    event.triggered_sec208 = True

            # 4. Pothole / road hazard alert from vision
            hazard_labels = {'pothole', 'road_work', 'pedestrian_crossing'}
            hazards_seen = [obj['label'] for obj in vision_objects if obj.get('label') in hazard_labels]
            for hazard in hazards_seen:
                self.tts.announce_hazard(f"Caution: {hazard.replace('_', ' ')} detected ahead.")

            # 5. Impact TTS Alert (Persona 4)
            if event.severity.value == "CRITICAL":
                self.tts.announce_hazard(
                    "CRITICAL: Near-miss detected. Hard braking triggered.", critical=True
                )
            elif event.severity.value == "HIGH":
                self.tts.announce_hazard("Warning: Aggressive driving manoeuvre detected.")

        return event

    # ------------------------------------------------------------------
    # Simulation / smoke-test
    # ------------------------------------------------------------------

    def run_simulation(self):
        logging.info("STARTING_SIMULATION_LOOP.")
        t_ms = int(time.time() * 1000)
        for i in range(130):
            t_ms += 10
            if i < 110:
                ax, ay, az = 0.1, 0.0, 9.8
                vision = []
            else:
                # Hard swerve with speed camera ahead
                ax, ay, az = -7.0, 6.0, 10.0
                vision = [{"label": "speed_camera", "conf": 0.9}]

            sample = IMUSample(t_ms, ax, ay, az, 0, 0, 90.0 if i > 110 else 0)
            self.process_sensor_frame(sample, vision_objects=vision)
            time.sleep(0.01)

if __name__ == "__main__":
    orchestrator = SmartSalaiOrchestrator()
    orchestrator.run_simulation()
