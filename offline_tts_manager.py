import pyttsx3
import queue
import threading
import time
import logging
from itertools import count

class OfflineTTSManager:
    """
    Sub-100ms latency voice interface. 
    Implements interrupt system for critical hazard TTS overrides.
    """
    def __init__(self):
        self.logger = logging.getLogger("edge_sentinel.tts")
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', 150)
        self.interrupt_queue = queue.PriorityQueue()
        self._seq = count()
        self._setup_worker()

    def _setup_worker(self):
        def worker():
            logger = logging.getLogger("edge_sentinel.tts.worker")
            while True:
<<<<<<< HEAD
                try:
                    priority, _, enqueued_at, message = self.interrupt_queue.get()
                    queue_wait_ms = (time.perf_counter() - enqueued_at) * 1000
                    logger.info("TTS_DEQUEUE: priority=%s queue_wait_ms=%.1f", priority, queue_wait_ms)

                    self.engine.say(message)
                    start = time.perf_counter()
                    self.engine.runAndWait()
                    synth_ms = (time.perf_counter() - start) * 1000
                    logger.info("TTS_SPOKEN: synth_ms=%.1f text=%s", synth_ms, message[:80])
                except Exception as e:
                    logger.error(f"TTS_WORKER_CRASHED: {e}")
=======
                priority, message = self.interrupt_queue.get()
                try:
                    self.engine.say(message)
                    self.engine.runAndWait()
                except Exception as e:
                    print(f"PERSONA_4_ERROR: TTS engine failure: {e}")
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e
                finally:
                    self.interrupt_queue.task_done()
        
        self.worker_thread = threading.Thread(target=worker, daemon=True, name="TTSMonitor")
        self.worker_thread.start()

    def ensure_healthy(self):
        """[REMEDIATION #2]: Restarts the TTS engine if the worker thread died."""
        if not hasattr(self, "worker_thread") or not self.worker_thread.is_alive():
            print("REMEDIATION: TTS worker found dead. Re-initializing engine...")
            try:
                self.engine = pyttsx3.init()
                self._setup_worker()
                return True
            except:
                return False
        return True

    def announce_hazard(self, hazard_text, critical=False):
        if not self.ensure_healthy():
            self.logger.error("TTS unavailable; dropping alert: %s", hazard_text)
            return False

        priority = 0 if critical else 1
        self.interrupt_queue.put((priority, next(self._seq), time.perf_counter(), hazard_text))
        print(f"PERSONA_4_REPORT: QUEUED_TTS: {hazard_text} (PRIORITY={priority})")
        return True

if __name__ == "__main__":
    # Test TTS Manager
    tts = OfflineTTSManager()
    tts.announce_hazard("Caution: Pothole detected ahead.", critical=True)
    time.sleep(2)
    tts.announce_hazard("Traffic congestion clearing.")
    time.sleep(5)
