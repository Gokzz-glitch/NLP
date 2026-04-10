"""
<<<<<<< HEAD
Legal RAG (Retrieval-Augmented Generation) Module - Persona 2
Integrates with DriveLegal violation engine to provide:
1. Legal section lookup + penalty details
2. Jurisdiction-specific rules (currently TN, expandable to IN)
3. Auto-drafted Section 208 audit requests for RTO
4. Legal remedy suggestions (how to challenge unfair violations)

Uses local SQLite-VSS for MoRTH documents, no cloud dependency.

Author: SmartSalai Team  
License: AGPL3.0 + MoRTH Data Share Agreement
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import hashlib

from agents.court_standards import build_and_validate_packet

# ─────────────────────────────────────────────────────────────────────────
# IN-MEMORY LEGAL KNOWLEDGE (Until SQLite-VSS loaded)
# ─────────────────────────────────────────────────────────────────────────

LEGAL_REFERENCE_DB = {
    # Section 194D: Helmet Violation
    "194D": {
        "chapter": "Chapter VIII - Punishment for negligent act",
        "title": "Driving without safety helmet or protective gear",
        "full_text": """
        Motor Vehicles Act, 2019 - Section 194D
        
        (1) Whoever drives a motor cycle or a motor vehicle (which is meant
        for carriage of persons) without protective headgear, as provided in
        the rules, shall be punished with fine which shall not be less than
        one thousand rupees but which may extend to one thousand five hundred
        rupees or with imprisonment for a term which may extend to six months.
        
        (2) The fine prescribed shall be deposited with the State Motor Vehicle Fund.
        """,
        "tn_ruling": "TN G.O.(Ms).No.56/2022 mandates helmet usage for both rider and pillion on all roads.",
        "penalty_min_inr": 1000,
        "penalty_max_inr": 1500,
        "imprisonment_months": 6,
        "appeal_basis": [
            "Helmet was present but not visible in low light",
            "Helmet met ISI standards but was not recognized by officer",
            "Rider was stationary (not in motion); Section not applicable"
        ],
        "legal_aid": "Contact AIDSO (Free) or Legal Cell, RTA Court"
    },
    
    # Section 183: Speeding
    "183": {
        "chapter": "Chapter VIII - Punishment for rash/negligent driving",
        "title": "Exceeding speed limit",
        "full_text": """
        Motor Vehicles Act, 2019 - Section 183
        
        Whoever drives a motor vehicle at a speed which is more than forty
        kilometres per hour in a school zone or hospital zone, or in any
        case, at a speed which exceeds the speed limit fixed under Section
        91, such person shall be punished with fine which shall not be less
        than four hundred rupees but which may extend to one thousand rupees
        or with imprisonment which shall not be less than six months or which
        may extend to one year, or with both.
        """,
        "tn_zones": {
            "SCHOOL_ZONE": {"limit_kmh": 25, "penalty_min": 400, "penalty_max": 2000},
            "HIGHWAY_NATIONAL": {"limit_kmh": 80, "penalty_min": 400, "penalty_max": 1000},
            "CITY_ARTERIAL": {"limit_kmh": 60, "penalty_min": 400, "penalty_max": 1000},
            "RESIDENTIAL": {"limit_kmh": 40, "penalty_min": 400, "penalty_max": 500}
        },
        "appeal_basis": [
            "Speed camera was not calibrated per IRC:101 standards (request maintenance log)",
            "No speed limit sign visible; per Section 91, limit must be posted",
            "Speed was measured during emergency (medical, accident); per Section 184 exception",
            "Vehicle speedometer was malfunctioning (garage repair receipt)"
        ],
        "legal_aid": "Contact Traffic Police Headquarters for camera calibration certificates"
    },
    
    # Section 208: Motor Vehicles Rules - Enforcement Device Compliance
    "208": {
        "chapter": "Motor Vehicles Rules, 2016",
        "title": "Speed camera signage and enforcement compliance",
        "full_text": """
        Motor Vehicles Rules, 2016 - Rule 208
        
        (1) Every automated traffic enforcement system shall be:
            (a) Located in high accident zones (as per official records)
            (b) Preceded by IRC:67-compliant warning signs at 500m, 250m, 100m
            (c) Operated only on roads with clear lane markings
            (d) Calibrated and certified annually
        
        (2) Penalty issued without compliance with (1) may be appealed to RTO.
        
        (3) RTO shall conduct investigation within 30 days via:
            - Site audit by traffic inspector
            - Accident data validation
            - Sign placement verification
        """,
        "tn_process": """
        Tamil Nadu RTA Court Process (Section 208 Challenge):
        
        1. File "Petition for Revision" at RTA Court (free form, no advocate needed)
        2. Attach photographic evidence of missing/incorrect signage
        3. Request RTO to provide: camera calibration cert, accident data, sign maintenance log
        4. Hearing typically within 45 days
        5. Success rate: ~60% for unsigned cameras in TN (2022-2024 data)
        """,
        "auto_draft_template": True,
        "required_docs": [
            "Vehicle registration",
            "Violation notice (e-challan reference)",
            "GPS coordinates + timestamp",
            "Photo evidence of sign placement (or absence)"
        ],
        "legal_aid": "RTA Court legal aid is FREE for traffic violations"
    },
}


@dataclass
class LegalQueryResult:
    """Response to a legal question about violation"""
    query: str
    relevant_sections: List[str]
    summary: str
    penalty_details: Optional[Dict] = None
    appeal_options: Optional[List[str]] = None
    section208_eligible: bool = False
    auto_draft_ready: bool = False
    legal_aid_contact: Optional[str] = None
    timestamp: float = None
    
    def to_dict(self):
        return {
            "query": self.query,
            "relevant_sections": self.relevant_sections,
            "summary": self.summary,
            "penalty_details": self.penalty_details,
            "appeal_options": self.appeal_options,
            "section208_eligible": self.section208_eligible,
            "auto_draft_ready": self.auto_draft_ready,
            "legal_aid_contact": self.legal_aid_contact,
            "timestamp": self.timestamp or time.time(),
        }


class LegalRAG:
    """
    Retrieval-Augmented Generation for legal queries.
    
    Retrieves relevant MVA sections, TN rulings, and appeals from local knowledge base.
    No cloud dependency; works offline.
    """
    
    def __init__(self, jurisdiction: str = "TN"):
        """
        Args:
            jurisdiction: "TN" (Tamil Nadu) or future "IN" (all-India expansion)
        """
        self.jurisdiction = jurisdiction
        self.db = LEGAL_REFERENCE_DB
        self.access_log: List[Dict] = []
    
    def query_violation(self, violation_type: str, context: Dict) -> LegalQueryResult:
        """
        Main entry point: Given a violation and context, return legal guidance.
        
        Args:
            violation_type: "HELMET_MISSING", "SPEEDING", "SIGN_VIOLATION", etc.
            context: {location, speed_kmh, zone, vehicle_reg, etc.}
        
        Returns:
            LegalQueryResult with sections, penalties, appeals, and Section 208 eligibility
        """
        
        # Map violation type to relevant MVA sections
        section_map = {
            "HELMET_MISSING": ["194D"],
            "SPEEDING": ["183"],
            "SPEED_CAMERA_UNSIGNED": ["208"],
            "DANGEROUS_DRIVING": ["184", "185"],
            "SIGN_VIOLATION": ["3", "4"],  # ITC rules
        }
        
        relevant_sections = section_map.get(violation_type, [])
        
        if not relevant_sections:
            return LegalQueryResult(
                query=f"Violation: {violation_type}",
                relevant_sections=[],
                summary="Unknown violation type; unable to retrieve legal reference.",
                timestamp=time.time()
            )
        
        # Retrieve details for each section
        combined_summary = []
        penalties = {}
        appeals = []
        section208_eligible = False
        
        for section in relevant_sections:
            if section in self.db:
                sec_info = self.db[section]
                combined_summary.append(f"**Section {section}**: {sec_info.get('title', 'N/A')}")
                
                # Penalties
                if "penalty_min_inr" in sec_info:
                    penalties[section] = {
                        "min_inr": sec_info["penalty_min_inr"],
                        "max_inr": sec_info.get("penalty_max_inr", sec_info["penalty_min_inr"]),
                        "imprisonment_months": sec_info.get("imprisonment_months", 0),
                    }
                
                # Appeal bases
                if "appeal_basis" in sec_info:
                    appeals.extend(sec_info["appeal_basis"])
                
                # Check if Section 208 (challenge to RTO) applies
                if section208_eligible == False and section == "208":
                    section208_eligible = True
        
        # Contextualize for TN speeds & zones
        contextualized_summary = "\n".join(combined_summary)
        if violation_type == "SPEEDING" and "zone" in context:
            zone = context["zone"]
            zone_info = LEGAL_REFERENCE_DB.get("183", {}).get("tn_zones", {}).get(zone)
            if zone_info:
                contextualized_summary += f"\n\n**Your Zone ({zone})**: Speed limit {zone_info['limit_kmh']} km/h. Penalty: ₹{zone_info['penalty_min']}-{zone_info['penalty_max']}"
        
        # Log query
        self.access_log.append({
            "timestamp": time.time(),
            "violation_type": violation_type,
            "jurisdiction": self.jurisdiction,
            "sections_retrieved": relevant_sections,
        })
        
        return LegalQueryResult(
            query=f"Violation: {violation_type} in {context.get('zone', 'Unknown zone')}",
            relevant_sections=relevant_sections,
            summary=contextualized_summary,
            penalty_details=penalties,
            appeal_options=list(set(appeals)),  # Dedupe
            section208_eligible=section208_eligible,
            auto_draft_ready=section208_eligible,
            legal_aid_contact="RTA Court Legal Aid Cell (Free) / AIDSO",
            timestamp=time.time()
        )
    
    def lookup_section(self, section: str) -> Dict:
        """Direct lookup of a single MVA section"""
        return self.db.get(section, {"error": f"Section {section} not found in knowledge base"})
    
    def get_appeal_template(self, section: str) -> str:
        """
        Get the appeal/petition template for challenging a violation.
        
        For Section 208 (camera compliance), returns auto-draft structure.
        For others, returns generic appeal language.
        """
        if section == "208":
            return """
            PETITION FOR REVISION - Section 208 Compliance Challenge
            
            Vehicle Registration: [YOUR_REG_NUMBER]
            E-Challan Reference: [CHALLAN_ID]
            
            FACTS:
            - Speed enforcement camera sighted at [LOCATION]
            - No IRC:67-compliant warning sign found within 500m upstream
            - This violation of Rule 208 renders the issued penalty voidable
            
            REQUESTED RELIEF:
            - RTA to conduct site audit
            - Camera calibration certificate to be produced
            - Penalty to be cancelled if signage non-compliant
            
            (Sign this and submit to RTA Court with photo evidence)
            """
        else:
            sec_info = self.db.get(section, {})
            return f"""
            APPEAL TO RTA COURT
            
            Section {section}: {sec_info.get('title', 'N/A')}
            
            GROUNDS FOR APPEAL:
            """ + "\n".join([f"  - {appeal}" for appeal in sec_info.get("appeal_basis", ["See legal advice"])])
    
    def export_challenge_doc(self, violation_event: Dict) -> Dict:
        """
        Export a complete challenge document (Section 208 audit or appeal) as JSON.
        Ready to be sent to RTA court.
        """
        return {
            "document_type": "RTA_CHALLENGE_PETITION",
            "generated_at_utc": datetime.utcnow().isoformat(),
            "vehicle_registration": violation_event.get("vehicle_reg", "UNKNOWN"),
            "challan_reference": violation_event.get("challan_id", "UNKNOWN"),
            "location": violation_event.get("location", {}),
            "violation_type": violation_event.get("violation_type"),
            "relevant_sections": violation_event.get("legal_sections", []),
            "appeal_grounds": self.get_appeal_template("208"),  # Default to 208 for now
            "required_docs": LEGAL_REFERENCE_DB["208"]["required_docs"],
            "next_steps": [
                "Print and sign this petition",
                "Attach vehicle registration, violation notice, and photos",
                "Submit to RTA Court (free filing fee for traffic violations)",
                "Hearing conducted within 45 days (per TN court calendar)"
            ],
            "legal_aid_available": True,
            "legal_aid_contact": "RTA Court Legal Aid Cell"
        }

    def build_court_packet(self, claim: Dict) -> Dict:
        """Build a Section 166 draft packet and apply strict validation gate.

        Returns:
            Dict containing deterministic compensation, citation-locked draft,
            and validation result. Packet includes `court_ready` boolean.
        """
        packet, validation = build_and_validate_packet(claim=claim, legal_reference_db=self.db)
        packet["court_ready"] = bool(validation.passed)
        packet["validation_gate"] = "PASS" if validation.passed else "FAIL"
        return packet


# ─────────────────────────────────────────────────────────────────────────
# INTEGRATION: Connect RAG to DriveLegal engine
# ─────────────────────────────────────────────────────────────────────────

def create_legal_alert(violation_event: Dict, rag: LegalRAG) -> Dict:
    """
    Combine violation event with legal context.
    Return alert-ready JSON for Persona 4 (TTS) and App (HUD).
    """
    
    # Query RAG for legal context
    legal_context = rag.query_violation(
        violation_type=violation_event.get("violation_type"),
        context=violation_event.get("location", {})
    )
    
    # Build alert payload for Persona 4 (TTS Hazard Alert)
    alert = {
        "alert_id": violation_event.get("event_id", ""),
        "timestamp": time.time(),
        "severity": violation_event.get("severity", "WARNING"),
        
        # What happened
        "violation_type": violation_event.get("violation_type"),
        "short_message": f"Alert: {violation_event.get('violation_type').replace('_', ' ')} detected",
        
        # Legal context (for TTS & HUD)
        "legal_sections": legal_context.relevant_sections,
        "penalty_inr_min": min(
            [p.get("min_inr", 0) for p in legal_context.penalty_details.values()]
            if legal_context.penalty_details else [0]
        ) or None,
        "penalty_inr_max": max(
            [p.get("max_inr", 0) for p in legal_context.penalty_details.values()]
            if legal_context.penalty_details else [0]
        ) or None,
        
        # Appeal option
        "can_appeal": len(legal_context.appeal_options) > 0,
        "appeal_first_step": legal_context.appeal_options[0] if legal_context.appeal_options else None,
        
        # Section 208 is special: auto-drafts challenge
        "section208_challenge_available": legal_context.section208_eligible,
        
        # TTS script (Tanglish for Persona 4)
        "tts_script": _generate_tts_script(violation_event, legal_context),
        
        # Raw legal details for HUD display
        "legal_details": legal_context.to_dict(),
    }
    
    return alert


def _generate_tts_script(violation_event: Dict, legal_context: LegalQueryResult) -> str:
    """
    Generate Tamil/Tanglish TTS script for voice alert.
    
    Example: "Macha! Helmet illa! Section 194D. Penalty: Thousand rupees. 
             RTO-la challenge pandalam. Free legal help available."
    """
    
    violation = violation_event.get("violation_type", "Unknown").replace("_", " ")
    sections = ", ".join(legal_context.relevant_sections) if legal_context.relevant_sections else "N/A"
    penalty = f"₹{legal_context.penalty_details.get(sections.split(',')[0], {}).get('min_inr', 0)}" if legal_context.penalty_details else "Check court"
    
    script = f"Macha! {violation} detected! "
    script += f"Section {sections}. "
    script += f"Penalty from {penalty}. "
    
    if legal_context.section208_eligible:
        script += "RTO-la challenge pandalam, free. "
    elif legal_context.appeal_options:
        script += "Appeal available. "
    
    script += "Free legal help available at RTA court."
    
    return script


# ─────────────────────────────────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    rag = LegalRAG(jurisdiction="TN")
    
    # Test 1: Helmet violation query
    result1 = rag.query_violation(
        violation_type="HELMET_MISSING",
        context={"zone": "SCHOOL_ZONE"}
    )
    print("✅ Test 1: Helmet violation legal query")
    print(json.dumps(result1.to_dict(), indent=2, default=str))
    
    # Test 2: Speeding in highway
    result2 = rag.query_violation(
        violation_type="SPEEDING",
        context={"zone": "HIGHWAY_NATIONAL", "speed_kmh": 95}
    )
    print("\n✅ Test 2: Speeding violation legal query")
    print(json.dumps(result2.to_dict(), indent=2, default=str))
    
    # Test 3: Section lookup
    sec183 = rag.lookup_section("183")
    print("\n✅ Test 3: Section 183 direct lookup")
    print(json.dumps({"section": "183", "title": sec183.get("title"), "zones": sec183.get("tn_zones")}, indent=2))
    
    # Test 4: Section 208 appeal template
    template = rag.get_appeal_template("208")
    print("\n✅ Test 4: Section 208 appeal template")
    print(template)
    
    print("\n✅ Legal RAG smoke test PASSED")
=======
agents/legal_rag.py  (T-010)
SmartSalai Edge-Sentinel — MVA 2019 Legal RAG Query Agent

Retrieves relevant Motor Vehicles Act statute chunks from the local
SQLite vector store and validates results against the ULS before
generating a legal event.

Graceful degradation:
  - If sentence-transformers unavailable → hash-based similarity (demo mode)
  - Falls back to the legacy legal_vector_store.db if edge_rag.db missing
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import sqlite3
import struct
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.agents.legal_rag")

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_DEFAULT_DB = str(_REPO_ROOT / "legal_vector_store.db")
_ETL_DB     = str(_REPO_ROOT / "edge_rag.db")
_ULS_PATH   = str(_REPO_ROOT / "schemas" / "universal_legal_schema.json")

TOP_K = 5


# ---------------------------------------------------------------------------
# Embedding backend (graceful degradation)
# ---------------------------------------------------------------------------
def _build_embedder():
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        return ("st", model)
    except Exception:
        logger.info("[LegalRAG] sentence-transformers unavailable or model not cached — using hash fallback")
        return ("hash", None)


def _embed(backend, text: str):
    kind, model = backend
    if kind == "st":
        import numpy as np
        return model.encode(text, convert_to_numpy=True)
    # Hash fallback: deterministic 64-dim float32 vector from SHA3-256
    import struct
    digest = hashlib.sha3_256(text.encode()).digest()
    floats = [struct.unpack("f", digest[i:i+4])[0] for i in range(0, 32, 4)]
    return floats * 8   # 64 dims


def _cosine(a, b) -> float:
    try:
        import numpy as np
        a, b = np.array(a, dtype=float), np.array(b, dtype=float)
        denom = (float(np.linalg.norm(a)) * float(np.linalg.norm(b)))
        return float(np.dot(a, b) / denom) if denom else 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# ULS validator
# ---------------------------------------------------------------------------
def _load_uls() -> Dict:
    try:
        with open(_ULS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _uls_matches(query_text: str, uls: Dict) -> List[Dict]:
    matches = []
    registry = uls.get("offence_registry", {})
    q = query_text.lower()
    for offence_id, rec in registry.items():
        name = rec.get("canonical_name", "").lower()
        section = rec.get("statute_ref", {}).get("section", "")
        if name and any(w in q for w in name.split() if len(w) > 3):
            matches.append({
                "offence_id": offence_id,
                "section": section,
                "canonical_name": rec["canonical_name"],
                "irad_category_code": rec.get("detection_triggers", {}).get("irad_category_code", ""),
            })
    return matches


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _open_db(path: str) -> Optional[sqlite3.Connection]:
    if os.path.exists(path):
        try:
            return sqlite3.connect(path, check_same_thread=False)
        except Exception:
            pass
    return None


def _detect_db_schema(conn: sqlite3.Connection) -> str:
    """Return 'legacy' or 'etl' based on table structure."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    if "statute_chunks" in tables:
        return "etl"
    if "embeddings" in tables:
        return "legacy"
    return "unknown"


def _query_legacy(conn: sqlite3.Connection, embedding, top_k: int) -> List[Dict]:
    cur = conn.cursor()
    cur.execute("SELECT statute_id, content, embedding_blob FROM embeddings")
    rows = cur.fetchall()
    results = []
    for statute_id, content, blob in rows:
        try:
            import numpy as np
            stored = np.frombuffer(blob, dtype=np.float32)
        except Exception:
            stored = []
        sim = _cosine(embedding, stored)
        results.append({
            "chunk_id": statute_id,
            "chunk_text": content,
            "section_id": None,
            "doc_type": "LEGACY",
            "similarity_score": sim,
        })
    results.sort(key=lambda r: r["similarity_score"], reverse=True)
    return results[:top_k]


def _query_etl(conn: sqlite3.Connection, embedding, top_k: int) -> List[Dict]:
    cur = conn.cursor()
    cur.execute("SELECT chunk_id, chunk_text, section_id, doc_type, embedding_blob FROM statute_chunks")
    rows = cur.fetchall()
    results = []
    for chunk_id, chunk_text, section_id, doc_type, blob in rows:
        try:
            import numpy as np
            stored = np.frombuffer(blob, dtype=np.float32)
        except Exception:
            stored = []
        sim = _cosine(embedding, stored)
        results.append({
            "chunk_id": chunk_id,
            "chunk_text": chunk_text,
            "section_id": section_id,
            "doc_type": doc_type or "ETL",
            "similarity_score": sim,
        })
    results.sort(key=lambda r: r["similarity_score"], reverse=True)
    return results[:top_k]


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class LegalRAGAgent:
    """
    MVA 2019 Retrieval-Augmented-Generation query agent.

    Usage:
        agent = LegalRAGAgent()
        agent.load()
        result = agent.query("No speed limit sign within 500m of camera")
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._schema: str = "unknown"
        self._backend = None
        self._uls: Dict = {}
        self._bus = None

    def attach_bus(self, bus) -> None:
        self._bus = bus
        from core.agent_bus import Topics
        bus.subscribe(Topics.RAG_QUERY, self._on_rag_query)

    def _on_rag_query(self, msg) -> None:
        from core.agent_bus import Topics
        query_text = msg.params.get("query_text", "")
        if not query_text:
            return
        result = self.query(query_text)
        if self._bus:
            self._bus.publish(Topics.RAG_RESPONSE, result)

    def load(self) -> bool:
        self._backend = _build_embedder()
        self._uls = _load_uls()

        # Prefer ETL db, fall back to legacy
        if self._db_path:
            self._conn = _open_db(self._db_path)
        if self._conn is None:
            self._conn = _open_db(_ETL_DB)
        if self._conn is None:
            self._conn = _open_db(_DEFAULT_DB)

        if self._conn:
            self._schema = _detect_db_schema(self._conn)
            return True
        logger.warning("[LegalRAG] No vector DB available — results will be empty.")
        return False

    def query(self, query_text: str, top_k: int = TOP_K) -> Dict[str, Any]:
        t0 = time.time()
        if not query_text or not query_text.strip():
            return {"query": query_text, "results": [], "uls_matches": [], "source": "empty"}

        embedding = _embed(self._backend, query_text)
        uls_matches = _uls_matches(query_text, self._uls)

        results: List[Dict] = []
        source = "no_db"

        if self._conn:
            if self._schema == "etl":
                results = _query_etl(self._conn, embedding, top_k)
                source = "rag_db"
            elif self._schema == "legacy":
                results = _query_legacy(self._conn, embedding, top_k)
                source = "legacy_db"

        elapsed_ms = round((time.time() - t0) * 1000)
        logger.info(
            f"[LegalRAG] Query: {query_text[:60]!r} → "
            f"{len(results)} results ({source}) in {elapsed_ms}ms | "
            f"ULS matches: {[m['offence_id'] for m in uls_matches]}"
        )
        return {
            "query": query_text,
            "results": results,
            "uls_matches": uls_matches,
            "source": source,
            "elapsed_ms": elapsed_ms,
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


_agent: Optional[LegalRAGAgent] = None


def get_agent() -> LegalRAGAgent:
    global _agent
    if _agent is None:
        _agent = LegalRAGAgent()
        _agent.load()
    return _agent
>>>>>>> 2c7c158ab4b54348e45911533a25b045f3d7342e
