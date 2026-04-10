import datetime
from pathlib import Path
# RTI Drafting Prompt Template
RTI_DRAFTING_PROMPT = """
You are an expert legal assistant. Draft a formal grievance under Section 198A of the Motor Vehicles Act, addressed to the Executive Engineer responsible for the following road segment:

Detected Hazard: {hazard_type}
Confidence: {confidence:.1f}%
Location: {lat:.6f}, {lon:.6f}
Jurisdiction: {authority} ({road_type})
Road Reference: {ref} / {name}
Detection Timestamp: {timestamp}

Instructions:
- Clearly cite Section 198A (contractor liability for road defects).
- Request immediate rectification and legal action as per the Act.
- Format as a formal letter with subject, body, and closing.
"""

def trigger_rti_draft_if_needed(hazard, confidence, lat, lon, jurisdiction_data, model=None, out_dir="rti_letters"):
    """
    If hazard is high-confidence and matches criteria, draft RTI using LLM.
    Args:
        hazard: str (e.g., 'pothole')
        confidence: float (0-100)
        lat, lon: float
        jurisdiction_data: dict from get_jurisdiction
        model: LLM callable (phi-3/gemma)
        out_dir: directory to save draft
    Returns: path to draft or None
    """
    if hazard.lower() in {"pothole", "speed_camera", "speed_trap"} and confidence >= 85.0:
        prompt = RTI_DRAFTING_PROMPT.format(
            hazard_type=hazard,
            confidence=confidence,
            lat=lat,
            lon=lon,
            authority=jurisdiction_data.get("authority", "UNKNOWN"),
            road_type=jurisdiction_data.get("road_type", "UNKNOWN"),
            ref=jurisdiction_data.get("ref", ""),
            name=jurisdiction_data.get("name", ""),
            timestamp=datetime.datetime.now().isoformat(),
        )
        # Call local LLM (phi-3/gemma) to generate draft
        if model is not None:
            draft = model(prompt)
        else:
            draft = f"[MOCK LLM OUTPUT]\n{prompt}"
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        fname = f"RTI_{hazard}_{lat:.5f}_{lon:.5f}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        fpath = Path(out_dir) / fname
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(draft)
        return str(fpath)
    return None
import json
from edge_vector_store import EdgeVectorStore

# [PERSONA 2: THE LEGAL GUARDIAN]
# Task: Implement conflict resolver logic between Legal PDFs (MVA 2019) and vision violation.

class Persona2ConflictResolver:
    """
    Analyzes vision-detected violations against local legal RAG (EdgeVectorStore).
    Determines if a violation is legally defensible.
    """
    def __init__(self, vector_store=None):
        self.vector_store = vector_store or EdgeVectorStore()
        # Seed Section 208 specifically for the resolver test
        self.vector_store.add_statute(
            "Sec_208", 
            "Mandatory advance warning signage for speed enforcement. Violations captured without signage are invalid."
        )

    def resolve_violation(self, violation_data, environmental_context):
        """
        violation_data: { "type": "SPEEDING", "speed": 85, "limit": 60 }
        environmental_context: { "vision_detected_signage": ["CAMERA"], "missing_signage": ["SPEED_LIMIT_SIGN"] }
        """
        violation_type = violation_data.get("type")
        
        # Query Legal RAG for defenses related to the violation type
        query_text = f"defense against {violation_type} violation missing signs"
        legal_precedents = self.vector_store.query(query_text, top_k=1)
        
        if not legal_precedents:
            return {"status": "ENFORCE", "reason": "No legal defense found in local RAG."}
        
        statute_id, content, score = legal_precedents[0]
        
        # Conflict Logic: If Section 208 is triggered by missing signage
        if statute_id == "Sec_208" and "SPEED_LIMIT_SIGN" in environmental_context.get("missing_signage", []):
            return {
                "status": "CHALLENGE_AUTO_GENERATED",
                "legal_basis": f"{statute_id}: {content}",
                "confidence": score,
                "action": "Suppress Violation. Generate Section 208 Audit Request."
            }
        
        return {
            "status": "ENFORCE",
            "legal_basis": f"Confirmed via {statute_id}",
            "confidence": score
        }

if __name__ == "__main__":
    resolver = Persona2ConflictResolver()
    
    # Test Scenario: Speeding detected, but Speed Limit Sign is missing (Sentinel vision audit)
    violation = {"type": "SPEEDING", "speed": 82, "limit": 60}
    context = {"vision_detected_signage": ["CAMERA"], "missing_signage": ["SPEED_LIMIT_SIGN"]}
    
    result = resolver.resolve_violation(violation, context)
    print("\nPERSONA_2_CONFLICT_RESOLVER_REPORT:")
    print(json.dumps(result, indent=2))
