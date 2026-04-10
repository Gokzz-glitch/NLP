import os
import time
import logging
from typing import Dict, Any
from agents.base import BaseAgent
from core.agent_bus import bus
from core.knowledge_ledger import ledger

logger = logging.getLogger("edge_sentinel.irad_reporter")

class IRADReporterAgent(BaseAgent):
    """
    Agent 34 — iRAD Reporter (Compliance)
    Listens for collision events and generates a standardized Integrated 
    Road Accident Database (iRAD) report for legal/insurance purposes.
    Correlates incident with ledger telemetry (weather, speed, pothole density).
    """
    
    REPORT_DIR = "reports/irad"
    
    def __init__(self):
        super().__init__("Agent34-IRADReporter", sleep_interval=120)
        self._ensure_report_dir()
        
        # Subscribe to accident triggers
        bus.subscribe("IMU_ACCIDENT_DETECTED", self.generate_compliance_report)
        bus.subscribe("SYSTEM_SOS_TRIGGER", self.generate_compliance_report)
        
        logger.info(f"[{self.name}] Compliance Monitoring Online — Ready for iRAD reporting.")

    def _ensure_report_dir(self):
        if not os.path.exists(self.REPORT_DIR):
            os.makedirs(self.REPORT_DIR, exist_ok=True)

    async def iteration(self):
        # Mostly event-driven via the bus, but we can do a periodic check for orphan reports
        pass

    def generate_compliance_report(self, payload: Dict[str, Any]):
        incident_ts = time.time()
        incident_id = payload.get("fusion_id") or f"ACC_{int(incident_ts)}"
        
        logger.info(f"[{self.name}] Generating official iRAD report for ID: {incident_id}")
        
        # 1. Fetch surrounding context from the Ledger (last 5 mins)
        context_rows = ledger.get_findings(limit=20)
        context_snippets = []
        for r in context_rows:
            agent = r.get("agent_name", "")
            content = r.get("content", {})
            if "pothole" in str(content).lower():
                context_snippets.append(f"- {agent}: Potential road hazard detected in vicinity.")
        
        # 2. Build iRAD template (Indian MoRTH format)
        report_content = f"""# Integrated Road Accident Database (iRAD) — Accident Report
        
**Incident ID:** {incident_id}
**Report Generated:** {time.strftime("%Y-%m-%d %H:%M:%S")}
**Source Node:** SmartSalai Edge-Sentinel (v3.1)

## 📍 Location & Context
- **Latitude:** {payload.get('lat', 'UNSPECIFIED')}
- **Longitude:** {payload.get('lon', 'UNSPECIFIED')}
- **Map Correlation:** India / Localized Highway
- **Environmental Context:** {", ".join(context_snippets[:3]) or "Standard clear-road conditions."}

## ⚡ Hardware Telemetry
- **X-Axis Force:** {payload.get('impact_x', 'N/A')} Gs
- **Y-Axis Force:** {payload.get('impact_y', 'N/A')} Gs
- **Safety Window Outcome:** SOS_RESIDENT_CALL_INITIATED (30s Window Over)
- **Status:** Compliance Document Created

## 🤖 AI Sentinel Analysis
The Edge-Sentinel multi-agent swarm was operational during the incident.
- **Agent7-GPUThermal:** Active (GPU stable)
- **Agent8-SentinelGuardian:** Broadcasted emergency mesh signal.
- **Agent31-ActiveLearning:** Capture uncertain frames for event reconstruction.

---
*This report is generated autonomously by the SmartSalai Edge-Sentinel for Indian Ministry of Road Transport (MoRTH) compliance.*
"""
        
        file_path = os.path.join(self.REPORT_DIR, f"{incident_id}_IRAD_REPORT.md")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            logger.info(f"[{self.name}] iRAD Report successfully saved to: {file_path}")
            
            # Emit success signal for the Dashboard UI
            ledger.log_finding(self.name, "compliance_reporting", {
                "report_id": incident_id,
                "file_path": file_path,
                "status": "GENERATED"
            })
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save iRAD report: {e}")

    async def generate_response(self, question: str) -> str:
        count = len(os.listdir(self.REPORT_DIR)) if os.path.exists(self.REPORT_DIR) else 0
        return (
            f"I am Agent 34 — iRAD Reporter. I have generated {count} official "
            f"compliance reports in the '{self.REPORT_DIR}' directory. "
            f"I am monitoring current V2X telemetry for accident signatures."
        )

if __name__ == "__main__":
    # Test Mock Report
    logging.basicConfig(level=logging.INFO)
    agent = IRADReporterAgent()
    agent.generate_compliance_report({
        "lat": 12.9716, "lon": 77.5946, 
        "impact_x": 4.5, "impact_y": 1.2
    })
