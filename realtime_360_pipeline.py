import cv2
import threading
import time
import os
import logging
from pathlib import Path

from core.agent_bus import bus

logger = logging.getLogger("edge_sentinel.realtime_360_pipeline")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def resolve_video_source() -> str:
    """
    Resolve the video source path in priority order:
    1. VIDEO_SOURCE env var (absolute or relative path to a .ts/.mp4 file).
    2. First .ts or .mp4 file found in raw_data/videos/ (relative to repo root).
    3. Raise FileNotFoundError with an actionable message.
    """
    env_src = os.environ.get("VIDEO_SOURCE", "").strip()
    if env_src:
        src_path = Path(env_src)
        if src_path.exists():
            logger.info(f"[VIDEO] Using VIDEO_SOURCE: {src_path.resolve()}")
            return str(src_path)
        logger.warning(
            f"[VIDEO] VIDEO_SOURCE='{env_src}' not found on disk, "
            "falling back to raw_data/videos/ scan."
        )

    videos_dir = Path(os.environ.get("RAW_DATA_DIR", "raw_data")) / "videos"
    if videos_dir.exists():
        candidates = sorted(
            list(videos_dir.glob("*.ts")) + list(videos_dir.glob("*.mp4"))
        )
        if candidates:
            logger.info(f"[VIDEO] Auto-selected: {candidates[0].resolve()}")
            return str(candidates[0])

    raise FileNotFoundError(
        "No video source found. "
        "Set the VIDEO_SOURCE env var to your .ts or .mp4 file path "
        f"(e.g. VIDEO_SOURCE='G:\\My Drive\\NLP\\raw_data\\videos\\dashcam.ts'), "
        f"or place files in {videos_dir.resolve()}"
    )


class RealTimeVideoStream:
    """Thread-safe, back-pressure-aware video stream reader."""

    def __init__(self, src: str):
        self._src = src
        self.stream = cv2.VideoCapture(src)
        if not self.stream.isOpened():
            raise IOError(f"[VIDEO] Cannot open video source: {src!r}")
        self._lock = threading.Lock()
        ok, frame = self.stream.read()
        self._frame = frame if ok else None
        self._stopped = False
        self._thread = threading.Thread(
            target=self._update, daemon=True, name="VideoReader"
        )
        self._thread.start()

    def _update(self):
        while not self._stopped:
            ok, frame = self.stream.read()
            if not ok:
                self.stop()
                break
            with self._lock:
                self._frame = frame
            # Yield CPU between frame reads to prevent 100% core burn.
            time.sleep(0.001)

    def read(self):
        with self._lock:
            return self._frame

    def stop(self):
        self._stopped = True
        self.stream.release()

    def join(self, timeout: float = 2.0):
        self._thread.join(timeout=timeout)


def process_frame(frame):
    """Resize and annotate frame, then emit a YOLO_DETECTION event to the agent bus."""
    resized_frame = cv2.resize(frame, (640, 640))
    cv2.putText(
        resized_frame,
        "Real-Time Vision Audit Active",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
    )
    # Emit detection event so acoustic UI and legal RAG stay in the loop.
    bus.emit(
        "YOLO_DETECTION",
        {
            "source": "realtime_360_pipeline",
            "frame_shape": list(resized_frame.shape),
            "timestamp": time.time(),
        },
    )
    return resized_frame


def main():
    try:
        stream_source = resolve_video_source()
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return

    logger.info(f"[INFO] Starting real-time 360 stream from {stream_source}...")
    try:
        video_stream = RealTimeVideoStream(stream_source)
    except IOError as exc:
        logger.error(str(exc))
        return

    # Allow the reader thread to buffer one frame before we start processing.
    time.sleep(0.1)
    fps_start_time = time.time()
    fps_counter = 0

    try:
        while True:
            frame = video_stream.read()
            if frame is None:
                logger.info("[INFO] End of stream or no frames available.")
                break
            output_frame = process_frame(frame)
            fps_counter += 1
            elapsed = time.time() - fps_start_time
            if elapsed > 1:
                fps = fps_counter / elapsed
                logger.info(f"[INFO] Processing at {fps:.2f} FPS")
                fps_counter = 0
                fps_start_time = time.time()
            cv2.imshow("360 Real-Time Analytics", output_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        logger.info("[INFO] Stream stopped by user.")
    finally:
        video_stream.stop()
        video_stream.join()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()