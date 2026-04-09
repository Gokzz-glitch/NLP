import cv2
import threading
import time

class RealTimeVideoStream:
    def __init__(self, src):
        self.stream = cv2.VideoCapture(src)
        self.ret, self.frame = self.stream.read()
        self.stopped = False
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()

    def update(self):
        while not self.stopped:
            self.ret, self.frame = self.stream.read()
            if not self.ret:
                self.stop()
                
    def read(self):
        return self.frame

    def stop(self):
        self.stopped = True
        self.stream.release()


def process_frame(frame):
    resized_frame = cv2.resize(frame, (640, 640))
    cv2.putText(resized_frame, "Real-Time Vision Audit Active", (20, 40), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    return resized_frame


def main():
    stream_source = "N0007530_20260406_060330_3min.ts" 
    print(f"[INFO] Starting real-time 360 stream from {stream_source}...")
    video_stream = RealTimeVideoStream(stream_source)
    time.sleep(1.0)
    fps_start_time = time.time()
    fps_counter = 0

    try:
        while True:
            frame = video_stream.read()
            if frame is None:
                break
            output_frame = process_frame(frame)
            fps_counter += 1
            if (time.time() - fps_start_time) > 1:
                fps = fps_counter / (time.time() - fps_start_time)
                print(f"[INFO] Processing at {fps:.2f} FPS")
                fps_counter = 0
                fps_start_time = time.time()
            cv2.imshow("360 Real-Time Analytics", output_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        print("[INFO] Stream stopped by user.")
    finally:
        video_stream.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()