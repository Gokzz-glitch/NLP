"""
keepalive.py — Auto-restart dashboard_api.py if it crashes
Run this instead of dashboard_api.py directly.
"""
import subprocess
import sys
import time
import os

script = os.path.join(os.path.dirname(__file__), "dashboard_api.py")
python = sys.executable

print("🔁 Keepalive watchdog started for dashboard_api.py")
restarts = 0
while True:
    print(f"▶️  Starting dashboard_api.py (restart #{restarts})…")
    proc = subprocess.run([python, script])
    restarts += 1
    print(f"⚠️  dashboard_api.py exited (code {proc.returncode}) — restarting in 3s…")
    time.sleep(3)
