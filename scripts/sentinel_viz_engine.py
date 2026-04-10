import cv2
import numpy as np
import time
from ultralytics import YOLO
import sys
from core.model_registry import resolve_yolo_pothole_pt

# ==============================================================================
# DESIGN SYSTEM: AEGIS FLIGHT DECK (SmartSalai Edge-Sentinel)
# ==============================================================================
COLORS = {
    "PRIMARY": (255, 213, 142),        # #8ed5ff (BGR: 255, 213, 142)
    "PRIMARY_CONTAINER": (248, 189, 56), # #38bdf8 (BGR: 248, 189, 56)
    "TERTIARY": (68, 68, 239),           # #ef4444 (BGR: 68, 68, 239)
    "SURFACE": (38, 19, 11),             # #0b1326 (BGR: 38, 19, 11)
    "ON_SURFACE": (253, 226, 218),       # #dae2fd (BGR: 253, 226, 218)
    "ACCENT_CYAN": (255, 255, 0),        # Pure Cyan for technical highlights
}

FONTS = {
    "MAIN": cv2.FONT_HERSHEY_SIMPLEX,
    "TECH": cv2.FONT_HERSHEY_DUPLEX,
}

class SentinelHUDEngine:
    def __init__(self, model_path=None):
        print("Initializing AEGIS FLIGHT DECK HUD Engine...")
        model_path = model_path or str(resolve_yolo_pothole_pt())
        try:
            from core.gpu_manager import gpu_manager
            self.gpu_manager = gpu_manager
            
            self.model = YOLO(model_path)
            self.model.to('cuda:0')
            self.model.half() # VRAM Optimization

            print(f"✅ Aegis Vision Brain Online: {model_path} (Forced GPU 0)")
        except Exception as e:
            print(f"❌ FATAL: Model not found at {model_path}. Error: {e}")
            sys.exit(1)
            
        self.start_time = time.time()
        self.speed = 0
        self.g_force = 1.0
        self.voice_text = "STANDING BY: Aegis Flight Deck Online."
        self.alert_level = "NOMINAL" # NOMINAL, WARNING, CRITICAL
        
        # History for G-force graph
        self.g_history = [1.0] * 50

    def draw_glass_panel(self, frame, x, y, w, h, opacity=0.4, blur=15):
        """Creates a glassmorphic panel with backdrop blur simulation."""
        sub_img = frame[y:y+h, x:x+w]
        
        # Backdrop blur simulation (Expensive but high-fidelity)
        blurred_sub = cv2.GaussianBlur(sub_img, (blur, blur), 0)
        
        # Create a semi-transparent surface tint
        overlay = blurred_sub.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), COLORS["SURFACE"], -1)
        
        # Combine
        glass = cv2.addWeighted(blurred_sub, 1 - opacity, overlay, opacity, 0)
        
        # Add a subtle 'Ghost Border' (Aegis Rule 4.4)
        cv2.rectangle(glass, (0, 0), (w, h), COLORS["PRIMARY"], 1, cv2.LINE_AA)
        
        frame[y:y+h, x:x+w] = glass

    def draw_telemetry(self, frame):
        """Renders the main telemetry widgets (Speed, G-force)."""
        h, w = frame.shape[:2]
        
        # 1. Digital Speedometer (Bottom Center)
        panel_w, panel_h = 240, 100
        px, py = (w - panel_w) // 2, h - panel_h - 120
        self.draw_glass_panel(frame, px, py, panel_w, panel_h, opacity=0.5)
        
        speed_text = f"{int(self.speed)}"
        cv2.putText(frame, speed_text, (px + 40, py + 70), FONTS["TECH"], 2.2, COLORS["PRIMARY_CONTAINER"], 3, cv2.LINE_AA)
        cv2.putText(frame, "KM/H", (px + 145, py + 70), FONTS["MAIN"], 0.7, COLORS["ON_SURFACE"], 1, cv2.LINE_AA)
        
        # 2. G-Sensor Monitor (Floating Right)
        gx, gy = w - 180, 150
        self.draw_glass_panel(frame, gx, gy, 150, 150, opacity=0.4)
        cv2.putText(frame, "G-SENSOR", (gx + 10, gy + 25), FONTS["MAIN"], 0.5, COLORS["ON_SURFACE"], 1, cv2.LINE_AA)
        cv2.putText(frame, f"{self.g_force:.2f}G", (gx + 10, gy + 60), FONTS["TECH"], 0.9, COLORS["PRIMARY"], 2, cv2.LINE_AA)
        
        # Simple Sparkline for G-force
        graph_x, graph_y = gx + 10, gy + 130
        for i in range(len(self.g_history) - 1):
            x1 = graph_x + (i * 2)
            y1 = graph_y - int(self.g_history[i] * 20)
            x2 = graph_x + ((i+1) * 2)
            y2 = graph_y - int(self.g_history[i+1] * 20)
            cv2.line(frame, (x1, y1), (x2, y2), COLORS["PRIMARY_CONTAINER"], 1, cv2.LINE_AA)

    def draw_detections(self, frame, results):
        """Draws technical bounding boxes for hazards."""
        for result in results:
            boxes = result.boxes
            for box in boxes:
                cls = int(box.cls[0])
                if cls != 0: continue # Target Potholes
                
                conf = float(box.conf[0])
                if conf < 0.25: continue
                
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                
                # Aegis Technical Box
                # Glowing cyan outline with technical markers
                cv2.rectangle(frame, (x1, y1), (x2, y2), COLORS["PRIMARY_CONTAINER"], 2, cv2.LINE_AA)
                
                # Technical Label
                label = f"HAZARD_ID:POTHOLE | CONF:{conf:.2%}"
                self.draw_glass_panel(frame, x1, y1 - 25, 240, 25, opacity=0.7, blur=1)
                cv2.putText(frame, label, (x1 + 5, y1 - 7), FONTS["TECH"], 0.4, (255, 255, 255), 1, cv2.LINE_AA)
                
                # Distance estimation (MOCK)
                dist = max(10, 50 - (y2 // 10))
                cv2.putText(frame, f"{dist}m", (x2 + 5, y2), FONTS["TECH"], 0.5, COLORS["PRIMARY"], 1)

    def draw_voice_assistant(self, frame):
        """Renders the AI Voice Assistant log at the bottom."""
        h, w = frame.shape[:2]
        panel_h = 60
        self.draw_glass_panel(frame, 0, h - panel_h, w, panel_h, opacity=0.8)
        
        # "Technical Assistant" Header
        cv2.putText(frame, "VOICE SERVICE:", (20, h - 35), FONTS["TECH"], 0.5, COLORS["PRIMARY_CONTAINER"], 1, cv2.LINE_AA)
        
        # Main Narrative
        cv2.putText(frame, f"> {self.voice_text}", (140, h - 35), FONTS["MAIN"], 0.65, COLORS["ON_SURFACE"], 1, cv2.LINE_AA)
        
        # Animated "Listening/Processing" dot
        if int(time.time() * 2) % 2 == 0:
            cv2.circle(frame, (w - 30, h - 30), 5, COLORS["PRIMARY_CONTAINER"], -1)

    def apply_hud(self, frame, results):
        """Orchestrates the entire HUD rendering sequence."""
        # Update dynamic values (MOCK/SIM)
        self.speed = 45 + np.sin(time.time()) * 5
        self.g_force = 1.0 + np.random.normal(0, 0.05)
        self.g_history.append(self.g_force)
        self.g_history.pop(0)

        # 1. Telemetry
        self.draw_telemetry(frame)
        
        # 2. Vision Brain
        self.draw_detections(frame, results)
        
        # 3. Voice Logic
        self.draw_voice_assistant(frame)
        
        # 4. Global Alert Overlays
        if self.alert_level == "CRITICAL":
            # Red flash on frame edges
            cv2.rectangle(frame, (0, 0), (frame.shape[1], frame.shape[0]), COLORS["TERTIARY"], 15)
            cv2.putText(frame, "CRITICAL IMPACT DETECTED", (frame.shape[1]//2 - 200, 100), FONTS["TECH"], 1.2, COLORS["TERTIARY"], 3)

        return frame

def run_demo(video_source=0):
    engine = SentinelHUDEngine()
    # Aegis v3: Force FFMPEG backend to avoid Intel/MSMF hardware capture
    cap = cv2.VideoCapture(video_source, cv2.CAP_FFMPEG)
    
    if not cap.isOpened():
        print(f"⚠️ CAP_FFMPEG failed for {video_source}. Falling back to default.")
        cap = cv2.VideoCapture(video_source)
    
    # Get device from Aegis Governor (Locked to GPU 1 / Index 0)
    # Zero-Fallback Policy: This will raise RuntimeError if RTX 3050 is missing.
    device = engine.gpu_manager.get_device_string()
    print(f"✅ Aegis Force Mode: Locked to {device}")
    
    # Async-bridge for GPU Lock in synchronous CV2 loop
    import asyncio
    loop = asyncio.new_event_loop()

    while True:
        ret, frame = cap.read()
        if not ret: break
        
        # Inference
        async def do_inference():
            await engine.gpu_manager.acquire("SentinelViz-Inference")
            try:
                # Force device=0, half=True (if supported by predict)
                return engine.model.predict(frame, conf=0.25, verbose=False, device=0)[0]
            finally:
                engine.gpu_manager.release("SentinelViz-Inference")

        results_single = loop.run_until_complete(do_inference())
        
        # Custom Logic for Demo Narratives (Simulated Based on Scouting)
        elapsed = time.time() - engine.start_time
        if elapsed < 5:
            engine.voice_text = "Aegis Sentinel Online. Monitoring local road topography."
        elif elapsed < 15:
            engine.voice_text = "Analyzing visual stream... Multiple surface depressions identified."
        
        # Render HUD
        output_frame = engine.apply_hud(frame, results_single)
        
        cv2.imshow("SmartSalai Edge-Sentinel (Aegis Flight Deck)", output_frame)
        
        if cv2.waitKey(1) & 0xFF == 27: # ESC to exit
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    # If a path is provided in ARGS, use it, else default to WEBCAM
    source = sys.argv[1] if len(sys.argv) > 1 else 0
    run_demo(source)
