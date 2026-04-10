import psutil
import os

KEYWORDS = ['dashboard_api', 'agent4_monitor', 'system_orchestrator_v2']

def kill_redundant():
    print("Searching for redundant processes...")
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['pid'] == current_pid:
                continue
            
            cmdline = " ".join(proc.info['cmdline'] or [])
            if any(kw in cmdline for kw in KEYWORDS):
                print(f"Killing {proc.info['pid']}: {cmdline}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

if __name__ == "__main__":
    kill_redundant()
