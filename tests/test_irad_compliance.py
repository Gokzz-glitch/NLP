import sys
import os
import time
import asyncio
import logging

# Ensure project root is in path
sys.path.append(os.getcwd())

from core.agent_bus import bus
from agents.irad_reporter_agent import IRADReporterAgent

async def test_irad_generation():
    logging.basicConfig(level=logging.INFO)
    print("🚀 SMOKE TEST: iRAD Compliance Reporting")
    
    # Initialize Agent
    reporter = IRADReporterAgent()
    
    # Simulate an accident trigger
    test_payload = {
        "fusion_id": "TEST_INCIDENT_999",
        "lat": 13.0827,
        "lon": 80.2707,
        "impact_x": 5.2,
        "impact_y": 0.8,
        "timestamp": time.time()
    }
    
    print("📢 Emitting IMU_ACCIDENT_DETECTED...")
    bus.emit("IMU_ACCIDENT_DETECTED", test_payload)
    
    # Wait for processing
    await asyncio.sleep(2)
    
    # Check for file
    report_file = os.path.join(os.getcwd(), "reports", "irad", "TEST_INCIDENT_999_IRAD_REPORT.md")
    if os.path.exists(report_file):
        print(f"✅ SUCCESS: iRAD Report generated at {report_file}")
    else:
        print(f"❌ FAILURE: iRAD Report not found at {report_file}")

if __name__ == "__main__":
    asyncio.run(test_irad_generation())
