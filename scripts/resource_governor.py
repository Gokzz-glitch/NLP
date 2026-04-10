import psutil
import time
import os
import ctypes

def get_python_processes():
    my_pid = os.getpid()
    python_procs = []
    # Dashboard and essential API keywords to exempt from suspension
    exempt_keywords = ['dashboard_api.py', 'agent2_dashboard\\api.py', 'api.py', 'continuous_training_loop.py']
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'].lower() in ['python.exe', 'python'] and proc.info['pid'] != my_pid:
                # Check for exemptions
                cmdline = " ".join(proc.info['cmdline'] or [])
                is_exempt = any(kw.lower() in cmdline.lower() for kw in exempt_keywords)
                if not is_exempt:
                   python_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return python_procs

def suspend_procs(procs):
    for p in procs:
        try:
            p.suspend()
        except:
            pass

def resume_procs(procs):
    for p in procs:
        try:
            p.resume()
        except:
            pass

def run_governor():
    print("🛡️ Sentinel Resource Governor ONLINE")
    print("Monitoring CPU, RAM, and managing Python workloads to keep system < 80% usage.")
    suspended = False
    
    while True:
        cpu = psutil.cpu_percent(interval=1)
        # Strict Rule: Keep CPU free. Throttle if CPU > 70% or RAM > 80%
        # We allow high GPU usage (100%) as per user's earlier instructions.
        is_stressed = cpu > 70 or mem > 80
        
        if is_stressed and not suspended:
            print(f"⚠️ [CPU/RAM STRESS] CPU: {cpu}% | RAM: {mem}%. Throttling scripts...")
            procs = get_python_processes()
            suspend_procs(procs)
            suspended = True
            
        elif not is_stressed and suspended and cpu < 70 and mem < 70:
            print(f"✅ [STRESS RELIEVED] CPU: {cpu}% | RAM: {mem}%. Resuming processes...")
            procs = get_python_processes()
            resume_procs(procs)
            suspended = False
            
        # Give GPU1 micro-sleep buffers by sleeping
        time.sleep(4)

if __name__ == "__main__":
    try:
        run_governor()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Resource Governor, resuming all processes...")
        resume_procs(get_python_processes())

