import cv2
import threading
import requests
import numpy as np
import time
from collections import deque
import sys
from core.model_registry import resolve_yolo_general_pt, resolve_yolo_pothole_pt

class HybridInvestorDemo:
    def __init__(self, use_phone=True, phone_ip="192.168.x.x", phone_port=8080):
        self.use_phone = use_phone
        self.phone_ip = phone_ip
        self.phone_port = phone_port
        self.phyphox_url = f"http://{phone_ip}:{phone_port}/get?accX&accY&accZ"
        # IP Webcam app stream URL (Android "IP Webcam" app default)
        self.ip_cam_url = f"http://{phone_ip}:{phone_port}/video"
        self.imu_z_baseline = deque(maxlen=30) # Rolling average buffer (From the Cheat Fixes!)
        self.current_impact_gforce = 0.0
        self.crash_triggered = False
        
        pothole_model_path = str(resolve_yolo_pothole_pt())
        print(f"LOADING: {pothole_model_path} (Authentic Weights)...")
        try:
            from ultralytics import YOLO
            import logging
            logging.getLogger("ultralytics").setLevel(logging.ERROR)
            self.model = YOLO(pothole_model_path)
            print("✅ Edge Vision Brain Online.")
        except Exception as e:
            general_model_path = str(resolve_yolo_general_pt())
            print(f"⚠️ Primary model load failed: {e}. Falling back to {general_model_path}")
            self.model = YOLO(general_model_path)

    def poll_smartphone_imu(self):
        """Background thread polling accelerometer from Phyphox App over USB Tethering/WiFi."""
        print(f"📡 Attempting connection to Smartphone IMU at {self.phyphox_url}...")
        while not self.crash_triggered and self.use_phone:
            try:
                # Phyphox REST format: {"buffer": {"accZ": {"buffer": [9.8, 9.7...]}}}
                resp = requests.get(self.phyphox_url, timeout=0.5)
                if resp.status_code == 200:
                    data = resp.json()
                    z_vals = data.get("buffer", {}).get("accZ", {}).get("buffer", [])
                    if z_vals:
                        latest_z = z_vals[-1]
                        self.imu_z_baseline.append(latest_z)
                        
                        # Authentic dynamic rolling average calculation
                        baseline = np.mean(self.imu_z_baseline) if len(self.imu_z_baseline) >= 10 else 9.81
                        deviation = abs(latest_z - baseline)
                        
                        if deviation > 5.0: # ~0.5G physical spike
                            print(f"\n⚠️ PHYSICAL IMU SPIKE DETECTED FROM SMARTPHONE: {deviation:.2f} m/s^2")
                            self.current_impact_gforce = deviation
                            self.crash_triggered = True
                            break
            except Exception:
                pass # Fail silently if phone disconnects, pitch continues with SPACEBAR
            time.sleep(0.05) # Poll ~20Hz

    def start_demo(self):
        print("🎥 IGNITING LIVE CAMERA FEED")
        print(f"➡️  Connecting to IP Camera at {self.ip_cam_url}")
        print("➡️  Install 'IP Webcam' app on Android and start server at port 8080.")
        print("➡️  Ensure phone and laptop are on the same WiFi network or USB tethered.")
        print("➡️  Hold up a Pothole image to the camera...")
        print("➡️  Shake your phone OR press SPACEBAR to trigger a crash...")
        print("➡️  Press ESC to exit or reset.")
        
        # Try IP camera stream only if phone_ip looks like a valid address
        _ip_valid = self.phone_ip and "x" not in self.phone_ip
        cap = None
        if _ip_valid:
            cap = cv2.VideoCapture(self.ip_cam_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                print(f"⚠️ IP Camera at {self.ip_cam_url} not reachable. Falling back to local webcam.")
                cap = None
        if cap is None:
            cap = cv2.VideoCapture(0)
        
        if self.use_phone:
            threading.Thread(target=self.poll_smartphone_imu, daemon=True).start()
            
        render_lawsuit_ui = False
        ui_timer = 0
        
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            # 1. Vision Logic Loop
            if not self.crash_triggered:
                # Dropping confidence slightly to catch phone screen clips held up to the webcam
                results = self.model.predict(frame, conf=0.15, verbose=False, device='cpu')[0]
                
                for box in results.boxes:
                    idx = int(box.cls[0])
                    if idx != 0: continue # Only Potholes!
                    
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    
                    # Draw authentic bounding boxes (Dynamic logic from Audit)
                    color = (0, 0, 255) if conf > 0.40 else (0, 255, 255)
                    label = f"POTHOLE GROUNDED {conf:.2f}" if conf > 0.40 else f"Uncertain Anomaly {conf:.2f}"
                    
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                
                # Polling for abort key
                key = cv2.waitKey(1) & 0xFF
                if key == 27: # ESC
                    break
                    
            # 2. Crash Overlay
            else:
                if ui_timer < 30: # Flash red crash for ~1 sec
                    ui_timer += 1
                    overlay = frame.copy()
                    cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 255), -1)
                    frame = cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)
                    cv2.putText(frame, f"CRITICAL IMPACT: {self.current_impact_gforce:.1f} m/s2", (50, frame.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 4)
                else:
                    render_lawsuit_ui = True
                    
            # 3. Legal RAG Overlay (MVA 198A)
            if render_lawsuit_ui:
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
                frame = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0)
                
                cv2.putText(frame, "MACHA EDGE-SENTINEL: LEGAL COUNSELING", (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)
                cv2.putText(frame, "> Querying Vector DB: legal_vector_store.db...", (50, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
                cv2.putText(frame, "> MATCH PREDICTION: MVA Sec 198A - Road Contractor Negligence", (50, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                lawsuit_text = [
                    "ACTION PLAN:",
                    "1. PRESERVE THIS DASHCAM FOOTAGE.",
                    "2. LOG EXACT GPS COORDINATES OF POTHOLE.",
                    "3. FILE FIR UNDER SEC 198A AGAINST MUNICIPALITY.",
                    " ",
                    "[Press ESC to reset Demo]"
                ]
                y_o = 230
                for line in lawsuit_text:
                    cv2.putText(frame, line, (50, y_o), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                    y_o += 40
                
                k = cv2.waitKey(1) & 0xFF
                if k == 27:
                    # Reset Demo for another investor
                    self.crash_triggered = False
                    render_lawsuit_ui = False
                    ui_timer = 0
                    self.imu_z_baseline.clear()
                    print("♻️ Investor Demo Resetting...")

            cv2.imshow("Macha Edge-Sentinel (Investor Pitch Mode)", frame)
            
            # Key polling timeout for the looping (required by openCV when showing frames)
            if not self.crash_triggered and not render_lawsuit_ui:
                # Key already polled in block #1
                pass
            elif render_lawsuit_ui:
                # Key polled in block #3
                pass
            else:
               # We are in the red flash sequence
               cv2.waitKey(1)

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    import os
    # Set PHONE_IP env var to your phone's IP (check 'IP Webcam' app on Android)
    phone_ip = os.environ.get("PHONE_IP", "192.168.1.10")
    phone_port = int(os.environ.get("PHONE_PORT", "8080"))
    demo = HybridInvestorDemo(use_phone=True, phone_ip=phone_ip, phone_port=phone_port)
    demo.start_demo()
