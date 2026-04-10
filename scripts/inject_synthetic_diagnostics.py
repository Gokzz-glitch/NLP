import random
import time
from core.knowledge_ledger import KnowledgeLedger

# Instantiate the ledger (uses correct DB path and schema)
ledger = KnowledgeLedger()

hazard_types = [
    "pothole",
    "road_debris",
    "speed_breaker",
    "accident",
    "flooded_road"
]

locations = [
    {"road": "NH-44", "lat": 28.7041, "lon": 77.1025},
    {"road": "NH-48", "lat": 19.0760, "lon": 72.8777},
    {"road": "NH-16", "lat": 13.0827, "lon": 80.2707},
    {"road": "NH-27", "lat": 26.9124, "lon": 75.7873},
    {"road": "NH-19", "lat": 22.5726, "lon": 88.3639}
]

legal_rationales = [
    "Violation of Section 208: Immediate hazard reporting required.",
    "Section 132: Road debris must be cleared within 24 hours.",
    "Section 119: Speed breaker must be marked and visible.",
    "Section 134: Accident site must be cordoned off.",
    "Section 144: Flooded roads require diversion signage."
]

def make_event(i):
    hazard = hazard_types[i % len(hazard_types)]
    loc = locations[i % len(locations)]
    rationale = legal_rationales[i % len(legal_rationales)]
    confidence = round(random.uniform(0.81, 0.97), 3)
    event = {
        "hazard_type": hazard,
        "road": loc["road"],
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "confidence": confidence,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "legal_rationale": rationale
    }
    return event

for i in range(5):
    event = make_event(i)
    ledger.log_finding(
        agent_name="diagnostic_injector",
        finding_type="synthetic_hazard_event",
        content=event
    )
    print(f"Injected: {event}")
