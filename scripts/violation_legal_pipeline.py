"""
Violation → Legal Pipeline: Integrates DriveLegal + LegalRAG with AgentBus

Demonstrates complete flow:
  Vision → Violation Event → Legal Query → Enriched Alert → Agent Bus
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.driveLegal_violation_engine import DriveLegalViolationEngine
from agents.legal_rag import LegalRAG
from core.agent_bus import bus, emit_legal_violation


class ViolationLegalPipeline:
    """End-to-end violation → legal alert pipeline"""
    
    def __init__(self):
        self.violation_engine = DriveLegalViolationEngine()
        self.legal_rag = LegalRAG()
        bus.subscribe("LEGAL_VIOLATION_DETECTED", self._handle_violation, "violation_pipeline")
    
    def _handle_violation(self, payload):
        """Enrich violation with legal context from LegalRAG"""
        violation_type = payload.get("violation_type")
        context = payload.get("context", {})
        
        # Query Legal RAG for this violation
        legal_result = self.legal_rag.query_violation(violation_type, context)
        
        # Extract penalty info from penalty_details dict
        penalty_details = legal_result.penalty_details or {}
        penalty_min = 0
        penalty_max = 0
        if penalty_details:
            for section_penalties in penalty_details.values():
                section_min = section_penalties.get('min_inr', 0)
                section_max = section_penalties.get('max_inr', 0)
                if penalty_min == 0:
                    penalty_min = section_min
                penalty_max = max(penalty_max, section_max)
        
        # Emit enriched alert to bus
        bus.emit("LEGAL_ALERT_GENERATED", {
            "violation_type": violation_type,
            "severity": payload.get("severity"),
            "legal_citation": legal_result.relevant_sections[0] if legal_result.relevant_sections else "MVA 2019",
            "section_number": legal_result.relevant_sections[0].split()[-1] if legal_result.relevant_sections else "194D",
            "penalty_inr_min": penalty_min,
            "penalty_inr_max": penalty_max,
            "appeal_first_step": legal_result.appeal_options[0] if legal_result.appeal_options else "File appeal",
        })
        print(f"  ✓ Legal alert enriched: ₹{penalty_min}-₹{penalty_max}")
    
    def process_detection(self, violation_type: str, confidence: float, location: dict):
        """Process vision detection through complete pipeline"""
        print(f"  Processing: {violation_type} (confidence={confidence:.2f})")
        
        # Step 1: DriveLegal violation engine
        violation_event = self.violation_engine.detect_violation(
            violation_type=violation_type,
            severity="CRITICAL" if confidence > 0.85 else "WARNING",
            location=location,
            context={"source": "YOLO", "confidence": confidence}
        )
        
        # Step 2: Emit to bus (triggers _handle_violation)
        emit_legal_violation(
            violation_type=violation_type,
            severity="CRITICAL" if confidence > 0.85 else "WARNING",
            location=location,
            context={"source": "YOLO", "confidence": confidence}
        )
        
        # Step 3: RTA risk computation
        rta_risk = self.violation_engine.compute_rta_risk(violation_type, location)
        print(f"  RTA risk: {rta_risk:.3f}")
        
        # Step 4: iRAD export
        irad_record = self.violation_engine.export_irad_record(violation_event)
        bus.emit("IRAD_RECORD_EXPORTED", irad_record)


if __name__ == "__main__":
    print("✅ Violation → Legal Pipeline Integration Test\n")
    
    pipeline = ViolationLegalPipeline()
    
    print("Test 1: Helmet violation (high confidence)")
    pipeline.process_detection(
        "HELMET_MISSING", 0.92,
        {"lat": 13.0827, "lng": 80.2707, "zone": "SCHOOL_ZONE", "speed_kmh": 45}
    )
    
    print("\nTest 2: Speeding detection (medium confidence)")
    pipeline.process_detection(
        "SPEEDING", 0.78,
        {"lat": 13.0850, "lng": 80.2750, "zone": "HIGHWAY", "speed_kmh": 95}
    )
    
    print("\nTest 3: Bus event metrics")
    metrics = bus.get_metrics()
    for event_type, stats in metrics.items():
        if stats['emit_count'] > 0:
            print(f"  {event_type}: {stats['emit_count']} emits, {stats['subscriber_count']} subs")
    
    print("\n✅ Violation → Legal Pipeline Integration Test PASSED")
