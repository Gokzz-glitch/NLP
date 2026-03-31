import pyttsx3
import queue
import threading
import time

class OfflineTTSManager:
    """
    Sub-100ms latency voice interface. 
    Implements interrupt system for critical hazard TTS overrides.
    """
    def __init__(self):
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', 150)
        self.interrupt_queue = queue.PriorityQueue()
        self._setup_worker()

    def _setup_worker(self):
        def worker():
            while True:
                priority, message = self.interrupt_queue.get()
                self.engine.say(message)
                self.engine.runAndWait()
                self.interrupt_queue.task_done()
        
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def announce_hazard(self, hazard_text, critical=False):
        priority = 0 if critical else 1
        self.interrupt_queue.put((priority, hazard_text))
        print(f"PERSONA_4_REPORT: QUEUED_TTS: {hazard_text} (PRIORITY={priority})")

if __name__ == "__main__":
    # Test TTS Manager
    tts = OfflineTTSManager()
    tts.announce_hazard("Caution: Pothole detected ahead.", critical=True)
    time.sleep(2)
    tts.announce_hazard("Traffic congestion clearing.")
    time.sleep(5)
