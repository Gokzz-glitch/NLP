# tests/stress_test.py
import asyncio
import time
import random
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_bus import bus
from core.knowledge_ledger import ledger

# Simulating 1k events in 10s (Burst)
TOTAL_EVENTS = 1000
BURST_PERIOD = 10 

async def mock_agent_emitter(name, count):
    """Simulates an agent emitting high-frequency telemetry"""
    for i in range(count):
        bus.emit("CUSTOM_STRESS", {
            "agent": name,
            "val": random.random(),
            "id": i
        })
        # Heavy stress: very low sleep
        await asyncio.sleep(BURST_PERIOD / count)

def on_stress_event(payload):
    """Synchronous receiver (Managed by ThreadPool)"""
    # Simulate DB write stress
    ledger.log_finding(payload["agent"], "stress_telemetry", payload)

async def run_stress_test():
    print(f"--- Edge-Sentinel: High-Frequency Stress Test ({TOTAL_EVENTS} events) ---")
    bus.subscribe("CUSTOM_STRESS", on_stress_event)
    
    start_time = time.perf_counter()
    
    # 5 concurrent agents emitting burst
    tasks = [
        mock_agent_emitter(f"StressAgent-{i}", TOTAL_EVENTS // 5)
        for i in range(5)
    ]
    
    await asyncio.gather(*tasks)
    
    end_time = time.perf_counter()
    duration = end_time - start_time
    
    print(f"--- Stress Complete in {duration:.2f}s ---")
    print(f"Throughput: {TOTAL_EVENTS / duration:.2f} events/sec")
    print("Verifying Ledger Integity...")
    
    # Check if entries are lost
    findings = ledger.get_findings(finding_type="stress_telemetry", limit=TOTAL_EVENTS)
    print(f"Ledger Count: {len(findings)} / {TOTAL_EVENTS}")
    
    if len(findings) >= TOTAL_EVENTS * 0.99:
        print("PASS (99%+ Integrity)")
    else:
        print(f"FAIL (Significant Data Loss: {len(findings)}/{TOTAL_EVENTS})")

if __name__ == "__main__":
    asyncio.run(run_stress_test())
