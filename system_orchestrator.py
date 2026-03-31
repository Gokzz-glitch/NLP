import time
import json
import logging
from agents.imu_near_miss_detector import NearMissDetector, IMUSample
from section_208_resolver import Section208Resolver
from offline_tts_manager import OfflineTTSManager
from edge_vector_store import EdgeVectorStore

# Configure Orchestrator Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: [ORCHESTRATOR] %(message)s")

class SmartSalaiOrchestrator:
    def __init__(self):
        self.detector = NearMissDetector() # Fallback to DETERMINISTIC mode initially
        self.resolver = Section208Resolver()
        self.tts = OfflineTTSManager()
        self._initialize_components()

    def _initialize_components(self):
        logging.info("INITIALIZING_AGENT_PIPELINE.")
        self.detector.load()
        # Seed initial legal data for RAG unblocking
        try:
            self.vector_store = EdgeVectorStore()
        except Exception:
            logging.warning("VECTOR_STORE_INIT_FAILED. FALLING_BACK_TO_MOCK.")
            self.vector_store = None

    def process_sensor_frame(self, imu_sample, vision_objects):
        """
        Main loop logic for routing data between personas.
        imu_sample: IMUSample object
        vision_objects: list of detected objects (proxy from YOLO)
        """
        # 1. Edge-Vision Check (Persona 3)
        # 2. IMU Near-Miss Check (Persona 3)
        event = self.detector.push_sample(imu_sample)
        
        if event:
            # 3. Legal Audit (Persona 2)
            # Check if vision detected a camera but no signage
            has_camera = any(obj['label'] == 'speed_camera' for obj in vision_objects)
            has_signage = any(obj['label'] == 'speed_limit_sign' for obj in vision_objects)
            
            if has_camera:
                audit = self.resolver.challenge_speed_camera(
                    {"lat": 12.0, "lon": 80.0, "type": "speed_camera"}, 
                    has_signage
                )
                if audit['status'] == 'CHALLENGE_GENERATED':
                    logging.warning(f"LEGAL_INFRASTRUCTURE_CHALLENGE: {audit['legal_basis']}")
                    self.tts.announce_hazard("Warning: Speed enforcement infrastructure lacks signage. Evidence challenged.", critical=True)
            
            # 4. Impact TTS Alert (Persona 4)
            if event.severity.value == "CRITICAL":
                self.tts.announce_hazard("CRITICAL: Near-miss detected. Hard braking triggered.", critical=True)

    def run_simulation(self):
        logging.info("STARTING_SIMULATION_LOOP.")
        t_ms = int(time.time() * 1000)
        # Mocking an IMU spike
        for i in range(130):
            t_ms += 10
            if i < 110:
                ax, ay, az = 0.1, 0.0, 9.8
                vision = []
            else:
                # Hard Swerve
                ax, ay, az = -7.0, 6.0, 10.0
                vision = [{"label": "speed_camera", "conf": 0.9}]
                
            sample = IMUSample(t_ms, ax, ay, az, 0, 0, 90.0 if i > 110 else 0)
            self.process_sensor_frame(sample, vision)
            time.sleep(0.01)

if __name__ == "__main__":
    orchestrator = SmartSalaiOrchestrator()
    orchestrator.run_simulation()
